"""Auric V3 production control plane.

Local-first operational controls shared by the API and autonomous engines:
RBAC/API-key authentication, rate limiting, persistent circuit state, execution
promotion stages, news blackout windows, portfolio policy, audit logs and
reconciliation metadata.  Uses SQLite so desktop deployments do not require an
external control service; larger deployments can replace this adapter without
changing trading logic.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any

ROLE_LEVEL = {"viewer": 0, "trader": 1, "admin": 2}
EXECUTION_STAGES = {"shadow", "paper", "assisted", "auto"}


@dataclass(frozen=True)
class Principal:
    name: str
    role: str
    authenticated: bool


class ProductionControlPlane:
    def __init__(self, db_path: str):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._db_lock = Lock()
        self._rate_lock = Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

        self.auth_required = os.getenv("AURIC_AUTH_REQUIRED", "false").lower() == "true"
        self.news_guard_enabled = os.getenv("NEWS_GUARD_ENABLED", "true").lower() == "true"
        self.news_min_impact = os.getenv("NEWS_GUARD_MIN_IMPACT", "high").lower()
        self.read_rpm = int(os.getenv("AURIC_READ_RPM", "240"))
        self.write_rpm = int(os.getenv("AURIC_WRITE_RPM", "60"))
        self._keys = self._parse_keys(os.getenv("AURIC_API_KEYS_JSON", ""))

        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_state(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                request_id TEXT,
                actor TEXT NOT NULL,
                role TEXT NOT NULL,
                action TEXT NOT NULL,
                path TEXT NOT NULL,
                status INTEGER NOT NULL,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
            CREATE TABLE IF NOT EXISTS news_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                impact TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                symbols TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_window ON news_events(start_ms, end_ms);
            CREATE TABLE IF NOT EXISTS reconciliation_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL
            );
            """
        )
        self.db.commit()

        self._set_default("execution_stage", os.getenv("AURIC_EXECUTION_STAGE", "paper").lower())
        self._set_default("global_halt", "false")
        self._set_default("halt_reason", "")
        self._set_default("halted_at", "0")

    @staticmethod
    def _parse_keys(raw: str) -> dict[str, Principal]:
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        out: dict[str, Principal] = {}
        if not isinstance(payload, dict):
            return out
        for token, value in payload.items():
            if not isinstance(token, str) or not token:
                continue
            if isinstance(value, str):
                role = value.lower()
                name = role
            elif isinstance(value, dict):
                role = str(value.get("role", "viewer")).lower()
                name = str(value.get("name", role))
            else:
                continue
            if role in ROLE_LEVEL:
                out[token] = Principal(name=name, role=role, authenticated=True)
        return out

    def _set_default(self, key: str, value: str) -> None:
        with self._db_lock:
            self.db.execute(
                "INSERT OR IGNORE INTO runtime_state(key,value,updated_at) VALUES(?,?,?)",
                (key, value, int(time.time() * 1000)),
            )
            self.db.commit()

    def _get_state(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def _set_state(self, key: str, value: str) -> None:
        now = int(time.time() * 1000)
        with self._db_lock:
            self.db.execute(
                "INSERT INTO runtime_state(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, now),
            )
            self.db.commit()

    def authenticate(self, token: str | None) -> Principal:
        if token and token in self._keys:
            return self._keys[token]
        if not self.auth_required:
            return Principal(name="local", role="admin", authenticated=False)
        return Principal(name="anonymous", role="viewer", authenticated=False)

    @staticmethod
    def allowed(principal: Principal, minimum_role: str) -> bool:
        return (
            principal.authenticated or principal.name == "local"
        ) and ROLE_LEVEL.get(principal.role, -1) >= ROLE_LEVEL[minimum_role]

    def rate_allowed(self, identity: str, method: str, path: str) -> tuple[bool, int]:
        now = time.monotonic()
        mutating = method.upper() not in {"GET", "HEAD", "OPTIONS"}
        limit = self.write_rpm if mutating else self.read_rpm
        bucket_name = f"{identity}:{'write' if mutating else 'read'}:{path.split('?')[0]}"
        with self._rate_lock:
            q = self._buckets[bucket_name]
            while q and now - q[0] >= 60.0:
                q.popleft()
            if len(q) >= limit:
                retry = max(1, int(60 - (now - q[0]))) if q else 60
                return False, retry
            q.append(now)
        return True, 0

    def audit(
        self,
        *,
        request_id: str,
        principal: Principal,
        action: str,
        path: str,
        status: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        with self._db_lock:
            self.db.execute(
                "INSERT INTO audit_log(ts,request_id,actor,role,action,path,status,detail) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    int(time.time() * 1000),
                    request_id,
                    principal.name,
                    principal.role,
                    action,
                    path,
                    int(status),
                    json.dumps(detail or {}, default=str),
                ),
            )
            self.db.commit()

    def audit_rows(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)
        ).fetchall()
        return [dict(r) for r in rows]

    def execution_stage(self) -> str:
        stage = self._get_state("execution_stage", "paper")
        return stage if stage in EXECUTION_STAGES else "paper"

    def set_execution_stage(self, stage: str) -> str:
        stage = stage.lower()
        if stage not in EXECUTION_STAGES:
            raise ValueError(f"Unknown execution stage: {stage}")
        self._set_state("execution_stage", stage)
        return stage

    def is_halted(self) -> bool:
        return self._get_state("global_halt", "false").lower() == "true"

    def halt(self, reason: str) -> None:
        self._set_state("global_halt", "true")
        self._set_state("halt_reason", reason[:500])
        self._set_state("halted_at", str(int(time.time() * 1000)))

    def resume(self) -> None:
        self._set_state("global_halt", "false")
        self._set_state("halt_reason", "")
        self._set_state("halted_at", "0")

    def circuit_snapshot(self) -> dict[str, Any]:
        return {
            "halted": self.is_halted(),
            "reason": self._get_state("halt_reason", ""),
            "haltedAt": int(self._get_state("halted_at", "0") or 0),
        }

    @staticmethod
    def _impact_rank(value: str) -> int:
        return {"low": 1, "medium": 2, "high": 3}.get(value.lower(), 0)

    def active_news(self, symbol: str, now_ms: int | None = None) -> list[dict[str, Any]]:
        if not self.news_guard_enabled:
            return []
        now_ms = int(now_ms or time.time() * 1000)
        rows = self.db.execute(
            "SELECT * FROM news_events WHERE enabled=1 AND start_ms<=? AND end_ms>=? "
            "ORDER BY impact DESC,start_ms ASC",
            (now_ms, now_ms),
        ).fetchall()
        threshold = self._impact_rank(self.news_min_impact)
        out = []
        for row in rows:
            if self._impact_rank(str(row["impact"])) < threshold:
                continue
            try:
                symbols = json.loads(row["symbols"])
            except Exception:
                symbols = ["ALL"]
            if "ALL" in symbols or symbol.upper() in {str(x).upper() for x in symbols}:
                item = dict(row)
                item["symbols"] = symbols
                out.append(item)
        return out

    def list_news(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT * FROM news_events ORDER BY start_ms DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["symbols"] = json.loads(item["symbols"])
            except Exception:
                item["symbols"] = ["ALL"]
            out.append(item)
        return out

    def add_news(
        self,
        *,
        title: str,
        impact: str,
        start_ms: int,
        end_ms: int,
        symbols: list[str],
        source: str = "manual",
    ) -> int:
        if impact.lower() not in {"low", "medium", "high"}:
            raise ValueError("impact must be low, medium or high")
        if end_ms <= start_ms:
            raise ValueError("end_ms must be after start_ms")
        cleaned = [s.upper() for s in symbols if s] or ["ALL"]
        with self._db_lock:
            cur = self.db.execute(
                "INSERT INTO news_events(title,impact,start_ms,end_ms,symbols,source,enabled,created_at) "
                "VALUES(?,?,?,?,?,?,1,?)",
                (
                    title[:300], impact.lower(), int(start_ms), int(end_ms),
                    json.dumps(cleaned), source[:80], int(time.time() * 1000),
                ),
            )
            self.db.commit()
            return int(cur.lastrowid)

    def set_news_enabled(self, event_id: int, enabled: bool) -> bool:
        with self._db_lock:
            cur = self.db.execute(
                "UPDATE news_events SET enabled=? WHERE id=?", (1 if enabled else 0, int(event_id))
            )
            self.db.commit()
            return cur.rowcount > 0

    def trade_gate(self, symbol: str, mode: str, *, autonomous: bool = False) -> tuple[bool, str]:
        if self.is_halted():
            return False, self._get_state("halt_reason", "Global circuit breaker is active")
        stage = self.execution_stage()
        if mode == "live":
            if autonomous and stage != "auto":
                return False, f"Autonomous live execution requires stage=auto (current={stage})"
            if not autonomous and stage not in {"assisted", "auto"}:
                return False, f"Manual live execution requires stage=assisted or auto (current={stage})"
            events = self.active_news(symbol)
            if events:
                return False, f"News blackout active: {events[0]['title']}"
        return True, "ok"

    def risk_policy(self) -> dict[str, float | int]:
        return {
            "maxOpenPositions": int(os.getenv("MAX_OPEN_POSITIONS", "5")),
            "maxTotalLots": float(os.getenv("MAX_TOTAL_LOTS", "5.0")),
            "maxSymbolLots": float(os.getenv("MAX_SYMBOL_LOTS", "2.0")),
            "minMarginLevelPct": float(os.getenv("MIN_MARGIN_LEVEL_PCT", "150")),
            "maxMarginUsagePct": float(os.getenv("MAX_MARGIN_USAGE_PCT", "35")),
            "maxRiskPerTradePct": float(os.getenv("MAX_RISK_PER_TRADE_PCT", "2")),
        }

    def portfolio_gate(
        self,
        *,
        requested_lots: float,
        symbol_lots: float,
        total_lots: float,
        open_positions: int,
        margin_level: float | None,
        margin_used: float | None,
        equity: float | None,
    ) -> tuple[bool, list[str]]:
        policy = self.risk_policy()
        reasons: list[str] = []
        if open_positions >= int(policy["maxOpenPositions"]):
            reasons.append("Maximum open positions reached")
        if symbol_lots + requested_lots > float(policy["maxSymbolLots"]):
            reasons.append("Per-symbol exposure cap exceeded")
        if total_lots + requested_lots > float(policy["maxTotalLots"]):
            reasons.append("Portfolio lot exposure cap exceeded")
        if margin_level is not None and margin_level > 0 and margin_level < float(policy["minMarginLevelPct"]):
            reasons.append("Margin level below production threshold")
        if margin_used is not None and equity and equity > 0:
            usage = margin_used / equity * 100.0
            if usage > float(policy["maxMarginUsagePct"]):
                reasons.append("Account margin usage cap exceeded")
        return not reasons, reasons

    def record_reconciliation(self, status: str, summary: dict[str, Any]) -> None:
        with self._db_lock:
            self.db.execute(
                "INSERT INTO reconciliation_log(ts,status,summary) VALUES(?,?,?)",
                (int(time.time() * 1000), status, json.dumps(summary, default=str)),
            )
            self.db.commit()

    def last_reconciliation(self) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM reconciliation_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        try:
            out["summary"] = json.loads(out["summary"])
        except Exception:
            pass
        return out

    def status(self) -> dict[str, Any]:
        return {
            "authRequired": self.auth_required,
            "configuredPrincipals": len(self._keys),
            "executionStage": self.execution_stage(),
            "circuit": self.circuit_snapshot(),
            "newsGuard": {
                "enabled": self.news_guard_enabled,
                "minImpact": self.news_min_impact,
            },
            "riskPolicy": self.risk_policy(),
            "lastReconciliation": self.last_reconciliation(),
        }
