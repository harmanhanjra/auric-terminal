"""Kronos forecast engine for AuricTerminal.

Lazy-loads a Kronos model + tokenizer from Hugging Face and exposes a
thread-safe ``forecast`` function that the FastAPI backend can call.
"""

import os
import sys
import threading
from typing import Dict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kronos"))

from model import Kronos, KronosTokenizer, KronosPredictor

_MODEL_LOCK = threading.Lock()
_PREDICT_LOCK = threading.Lock()
_PREDICTOR = None

# model_id -> (tokenizer_repo, model_repo)
MODELS = {
    "mini": ("NeoQuasar/Kronos-Tokenizer-2k", "NeoQuasar/Kronos-mini"),
    "small": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-small"),
    "base": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-base"),
}

DEFAULT_MODEL = os.environ.get("KRONOS_MODEL", "mini")


def _get_predictor(model_id: str = DEFAULT_MODEL):
    global _PREDICTOR
    if model_id not in MODELS:
        raise ValueError(f"Unknown Kronos model '{model_id}'. Choose from {list(MODELS)}")
    tokenizer_repo, model_repo = MODELS[model_id]
    with _MODEL_LOCK:
        if _PREDICTOR is None:
            tokenizer = KronosTokenizer.from_pretrained(tokenizer_repo)
            model = Kronos.from_pretrained(model_repo)
            _PREDICTOR = KronosPredictor(model, tokenizer, max_context=512)
        return _PREDICTOR


def load_dataset(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["timestamps"] = pd.to_datetime(df["timestamps"])
    df = df.sort_values("timestamps").reset_index(drop=True)
    for col in ("open", "close", "high", "low", "volume", "amount"):
        if col not in df.columns:
            df[col] = 0.0
    return df


def forecast(
    csv_path: str,
    lookback: int = 400,
    pred_len: int = 60,
    T: float = 1.0,
    top_p: float = 0.9,
    sample_count: int = 3,
    model_id: str = DEFAULT_MODEL,
    verbose: bool = False,
) -> Dict:
    """Run a Kronos forecast over the tail of a local OHLCV CSV.

    Returns JSON-safe dict: {historical: [...], forecast: [...], metadata}
    Each point: {time, open, high, low, close, volume, amount}
    """
    df = load_dataset(csv_path)
    if len(df) < lookback + 1:
        raise ValueError(f"CSV has {len(df)} rows; need at least {lookback + 1}")

    tail = df.tail(lookback).reset_index(drop=True)
    last_ts = df["timestamps"].iloc[-1]

    x_df = tail[["open", "high", "low", "close", "volume", "amount"]]
    x_timestamp = tail["timestamps"]
    step = (df["timestamps"].iloc[-1] - df["timestamps"].iloc[-2])
    y_timestamp = pd.Series(
        pd.date_range(start=last_ts + step, periods=pred_len, freq=step)
    )

    predictor = _get_predictor(model_id)

    with _PREDICT_LOCK:
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=T,
            top_p=top_p,
            sample_count=sample_count,
            verbose=verbose,
        )

    hist = [
        {
            "time": str(row.timestamps),
            "open": round(float(row.open), 4),
            "high": round(float(row.high), 4),
            "low": round(float(row.low), 4),
            "close": round(float(row.close), 4),
            "volume": round(float(row.volume), 2),
            "amount": round(float(row.amount), 2),
        }
        for _, row in tail.iterrows()
    ]
    fore = [
        {
            "time": str(ts),
            "open": round(float(row.open), 4),
            "high": round(float(row.high), 4),
            "low": round(float(row.low), 4),
            "close": round(float(row.close), 4),
            "volume": round(float(row.volume), 2),
            "amount": round(float(row.amount), 2),
        }
        for ts, row in pred_df.iterrows()
    ]
    last_close = float(tail["close"].iloc[-1])
    f_close = float(pred_df["close"].iloc[-1])
    return {
        "historical": hist,
        "forecast": fore,
        "metadata": {
            "model": model_id,
            "lookback": lookback,
            "pred_len": pred_len,
            "last_close": last_close,
            "forecast_close": f_close,
            "pct_change": round((f_close - last_close) / last_close * 100.0, 4) if last_close else 0.0,
            "rows": int(len(df)),
        },
    }


def forecast_from_candles(
    candles: list,
    lookback: int = 400,
    pred_len: int = 60,
    T: float = 1.0,
    top_p: float = 0.9,
    sample_count: int = 3,
    model_id: str = DEFAULT_MODEL,
    verbose: bool = False,
) -> Dict:
    """Run a Kronos forecast directly from a list of OHLCV candle dicts."""
    if len(candles) < lookback + 1:
        raise ValueError(f"Got {len(candles)} candles; need at least {lookback + 1}")

    tail = candles[-lookback:]
    df = pd.DataFrame(tail)
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["amount"] = df["volume"] * ((df["open"] + df["high"] + df["low"] + df["close"]) / 4.0)

    if "time" in df.columns:
        try:
            timestamps = pd.to_datetime(df["time"], unit="s")
        except Exception:
            timestamps = pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq="1min")
    else:
        timestamps = pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq="1min")
    df["timestamps"] = timestamps

    predictor = _get_predictor(model_id)

    x_df = df[["open", "high", "low", "close", "volume", "amount"]].copy()
    x_timestamp = df["timestamps"]
    step = pd.Timedelta(minutes=1)
    last_ts = df["timestamps"].iloc[-1]
    y_timestamp = pd.Series(
        pd.date_range(start=last_ts + step, periods=pred_len, freq=step)
    )

    with _PREDICT_LOCK:
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=T,
            top_p=top_p,
            sample_count=sample_count,
            verbose=verbose,
        )

    hist = [
        {
            "open": round(float(row.open), 4),
            "high": round(float(row.high), 4),
            "low": round(float(row.low), 4),
            "close": round(float(row.close), 4),
            "volume": round(float(row.volume), 2),
        }
        for _, row in df.iterrows()
    ]
    fore = [
        {
            "time": str(ts),
            "open": round(float(row.open), 4),
            "high": round(float(row.high), 4),
            "low": round(float(row.low), 4),
            "close": round(float(row.close), 4),
            "volume": round(float(row.volume), 2),
        }
        for ts, row in pred_df.iterrows()
    ]

    last_close = float(df["close"].iloc[-1])
    f_close = float(pred_df["close"].iloc[-1])
    f_high = float(pred_df["high"].max())
    f_low = float(pred_df["low"].min())
    pct = (f_close - last_close) / last_close * 100.0 if last_close else 0.0

    confidence = min(abs(pct) / 2.0, 1.0)
    if pct > 0.05:
        direction = 1
    elif pct < -0.05:
        direction = -1
    else:
        direction = 0

    return {
        "historical": hist,
        "forecast": fore,
        "direction": direction,
        "confidence": round(confidence, 4),
        "metadata": {
            "model": model_id,
            "lookback": lookback,
            "pred_len": pred_len,
            "last_close": last_close,
            "forecast_close": f_close,
            "pct_change": round(pct, 4),
            "direction": direction,
            "confidence": round(confidence, 4),
        },
    }
