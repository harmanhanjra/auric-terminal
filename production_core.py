"""Production controls for Auric Terminal.

This module deliberately uses the Python standard library so the local MT5 desktop
deployment does not gain a large authentication/runtime dependency surface.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = ("shadow", "paper", "assisted", "auto")


class ExecutionPolicy:
    def __init__(self, stage: str | None = None):
        value = (stage or os.getenv("AURIC_EXECUTION_STAGE", "paper")).lower().strip()
        if value not in STAGES:
            raise ValueError(f"AURIC_EXECUTION_STAGE must be one of {STAGES}")
        self.stage = value

    @property
    def live_manual_allowed(self) -> bool:
        return self.stage in ("assisted", "auto")

    @property
    def auto_live_allowed(self) -> bool:
        return self.stage == "auto"

    @property
    def paper_allowed(self) -> bool:
        return self.stage in ("paper", "assisted", "auto")

    def payload(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "shadow": self.stage == "shadow",
            "paperAllowed": self.paper_allowed,
            "manualLiveAllowed": self.live_manual_allowed,
            "autoLiveAllowed": self.auto_live_allowed,
        }


class OperatorAuth:
    """Small HMAC-signed operator token for a single-operator/local deployment.

    For internet-facing multi-user deployment this should sit behind OIDC/RBAC.
    """

    def __init__(self):
        self.secret = os.getenv("AURIC_AUTH_SECRET", "")
        self.operator_password = os.getenv("AURIC_OPERATOR_PASSWORD", "")
        self.require_auth = os.getenv("AURIC_REQUIRE_AUTH", "false").lower() == "true"
        self.ttl_seconds = int(os.getenv("AURIC_SESSION_TTL_SECONDS", "28800"))

    @property
    def configured(self) -> bool:
        return bool(self.secret and self.operator_password)

    def issue(self, username: str, password: str, role: str = "operator") -> str:
        if not self.configured:
            raise ValueError("Operator auth is not configured")
        expected_user = os.getenv("AURIC_OPERATOR_USERNAME", "operator")
        if not hmac.compare_digest(username, expected_user):
            raise PermissionError("Invalid credentials")
        if not hmac.compare_digest(password, self.operator_password):
            raise PermissionError("Invalid credentials")
        now = int(time.time())
        payload = {
            "sub": username,
            "role": role,
            "iat": now,
            "exp": now + self.ttl_seconds,
            "nonce": os.urandom(8).hex(),
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        body = base64.urlsafe_b64encode(raw).rstrip(b"=")
        sig = hmac.new(self.secret.encode(), body, hashlib.sha256).digest()
        return body.decode() + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    def verify(self, token: str) -> dict[str, Any]:
        if not self.configured:
            raise PermissionError("Operator auth is not configured")
        try:
            body_s, sig_s = token.split(".", 1)
            body = body_s.encode()
            pad = "=" * (-len(sig_s) % 4)
            supplied = base64.urlsafe_b64decode(sig_s + pad)
            expected = hmac.new(self.secret.encode(), body, hashlib.sha256).digest()
            if not hmac.compare_digest(supplied, expected):
                raise PermissionError("Invalid session")
            payload_pad = "=" * (-len(body_s) % 4)
            payload = json.loads(base64.urlsafe_b64decode(body_s + payload_pad))
            if int(payload.get("exp", 0)) < int(time.time()):
                raise PermissionError("Session expired")
            return payload
        except PermissionError:
            raise
        except Exception as exc:
            raise PermissionError("Invalid session") from exc


class TokenBucketLimiter:
    def __init__(self, capacity: int = 30, refill_per_sec: float = 0.5):
        self.capacity = max(1, capacity)
        self.refill = max(0.01, refill_per_sec)
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._state.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last) * self.refill)
            if tokens < cost:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - cost, now)
            return True


class AuditLog:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS audit_events("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, actor TEXT NOT NULL, "
            "action TEXT NOT NULL, resource TEXT NOT NULL, outcome TEXT NOT NULL, "
            "request_id TEXT, remote TEXT, details TEXT NOT NULL)"
        )
        self.db.commit()

    def write(
        self,
        *,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        request_id: str | None = None,
        remote: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO audit_events(ts,actor,action,resource,outcome,request_id,remote,details) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    int(time.time() * 1000), actor[:100], action[:100], resource[:200],
                    outcome[:50], request_id, remote, json.dumps(details or {}, default=str),
                ),
            )
            self.db.commit()

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id,ts,actor,action,resource,outcome,request_id,remote,details "
            "FROM audit_events ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            try:
                item["details"] = json.loads(item["details"])
            except Exception:
                pass
            out.append(item)
        return out


@dataclass(frozen=True)
class BlackoutEvent:
    start_ms: int
    end_ms: int
    title: str
    symbols: tuple[str, ...]
    importance: str


class BlackoutGuard:
    """Economic/news blackout guard.

    Reads a provider-normalized JSON file. Expected rows:
    {"timestamp":"2026-09-19T12:30:00Z","title":"CPI","symbols":["XAUUSD","EURUSD"],
     "importance":"high","minutes_before":15,"minutes_after":15}
    """

    def __init__(self):
        self.path = os.getenv("ECONOMIC_CALENDAR_FILE", "")
        self.default_before = int(os.getenv("NEWS_BLACKOUT_MINUTES_BEFORE", "15"))
        self.default_after = int(os.getenv("NEWS_BLACKOUT_MINUTES_AFTER", "15"))
        self._mtime = -1.0
        self._events: list[BlackoutEvent] = []

    def _load(self) -> None:
        if not self.path:
            self._events = []
            return
        p = Path(self.path)
        if not p.exists():
            self._events = []
            return
        stat = p.stat()
        if stat.st_mtime == self._mtime:
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        events: list[BlackoutEvent] = []
        for row in data if isinstance(data, list) else data.get("events", []):
            if str(row.get("importance", "high")).lower() not in ("high", "critical"):
                continue
            raw_ts = str(row["timestamp"]).replace("Z", "+00:00")
            event_dt = datetime.fromisoformat(raw_ts)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            event_ms = int(event_dt.timestamp() * 1000)
            before = int(row.get("minutes_before", self.default_before)) * 60_000
            after = int(row.get("minutes_after", self.default_after)) * 60_000
            events.append(BlackoutEvent(
                event_ms - before,
                event_ms + after,
                str(row.get("title", "Economic event")),
                tuple(str(s).upper() for s in row.get("symbols", [])),
                str(row.get("importance", "high")).lower(),
            ))
        self._mtime = stat.st_mtime
        self._events = events

    def check(self, symbol: str, now_ms: int | None = None) -> dict[str, Any]:
        try:
            self._load()
        except Exception as exc:
            # For live trading, malformed configured calendar data should fail closed.
            return {"allowed": False, "reason": f"Calendar guard error: {exc}", "event": None}
        if not self.path:
            return {"allowed": True, "reason": "No calendar provider file configured", "event": None}
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        sym = symbol.upper()
        for ev in self._events:
            if ev.start_ms <= now <= ev.end_ms and (not ev.symbols or sym in ev.symbols):
                return {
                    "allowed": False,
                    "reason": f"{ev.importance.title()}-impact blackout: {ev.title}",
                    "event": {
                        "title": ev.title, "importance": ev.importance,
                        "startMs": ev.start_ms, "endMs": ev.end_ms,
                        "symbols": list(ev.symbols),
                    },
                }
        return {"allowed": True, "reason": "No active high-impact blackout", "event": None}


class ReconciliationState:
    def __init__(self):
        self.last_sync_ms = 0
        self.ok = False
        self.broker_connected = False
        self.position_count = 0
        self.pending_count = 0
        self.unmatched_tickets: list[str] = []
        self.error: str | None = None

    def payload(self) -> dict[str, Any]:
        age = None if not self.last_sync_ms else max(0, int(time.time() * 1000) - self.last_sync_ms)
        return {
            "ok": self.ok,
            "brokerConnected": self.broker_connected,
            "lastSyncMs": self.last_sync_ms,
            "ageMs": age,
            "positionCount": self.position_count,
            "pendingCount": self.pending_count,
            "unmatchedTickets": list(self.unmatched_tickets),
            "error": self.error,
        }


def production_readiness(
    *,
    env_name: str,
    policy: ExecutionPolicy,
    auth: OperatorAuth,
    live_enabled: bool,
    auto_live_enabled: bool,
    live_api_key: str,
    mt5_connected: bool,
    reconciliation: ReconciliationState,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    prod = env_name.lower() == "production"
    add("auth", (not prod) or (auth.require_auth and auth.configured),
        "operator authentication configured" if auth.configured else "operator authentication not configured")
    add("live-key", (not (live_enabled or auto_live_enabled)) or len(live_api_key) >= 24,
        "live mutation key configured" if live_api_key else "live mutation key missing")
    add("stage/manual-live", (not live_enabled) or policy.live_manual_allowed,
        f"execution stage is {policy.stage}")
    add("stage/auto-live", (not auto_live_enabled) or policy.auto_live_allowed,
        f"execution stage is {policy.stage}")
    add("broker", (not (live_enabled or auto_live_enabled)) or mt5_connected,
        "MT5 connected" if mt5_connected else "MT5 not connected")
    recon = reconciliation.payload()
    add("reconciliation", (not (live_enabled or auto_live_enabled)) or recon["ok"],
        recon["error"] or ("broker reconciliation healthy" if recon["ok"] else "reconciliation not healthy"))

    ready = all(c["ok"] for c in checks)
    return {"ready": ready, "environment": env_name, "policy": policy.payload(), "checks": checks}
