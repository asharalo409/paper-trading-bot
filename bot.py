#!/usr/bin/env python3
"""
Paper-trading bot (NO real money).
Strategy: SMA crossover on 15-minute BTC/USD candles (Kraken public API).
State: public/state.json (the Vercel dashboard reads this file)
Run: python bot.py        |   offline test: python bot.py --simulate
"""
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone

# ---------------- settings ----------------
PAIR = "XBTUSD"
INTERVAL_MIN = 15
FAST, SLOW = 10, 30
START_CASH = 1000.0
FEE = 0.0026
STOP_LOSS = 0.02
MAX_DAILY_LOSS = 0.05
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public", "state.json")
MAX_HISTORY = 2000
# -------------------------------------------


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_closes():
    url = f"https://api.kraken.com/0/public/OHLC?pair={PAIR}&interval={INTERVAL_MIN}"
    req = urllib.request.Request(url, headers={"User-Agent": "paper-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    if data.get("error"):
        raise RuntimeError(f"Kraken error: {data['error']}")
    result = data["result"]
    key = next(k for k in result if k != "last")
    candles = result[key][:-1]
    return [float(c[4]) for c in candles]


def fake_closes(n=200, seed=None):
    rnd = random.Random(seed)
    price, out = 60000.0, []
    for i in range(n):
        price *= 1 + rnd.gauss(0, 0.004) + 0.0008 * math.sin(i / 12)
        out.append(price)
    return out


def sma(values, n):
    return sum(values[-n:]) / n


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "start_cash": START_CASH,
        "cash": START_CASH,
        "qty": 0.0,
        "entry_price": None,
        "last_signal": None,
        "day": None,
        "day_start_equity": START_CASH,
        "halted_today": False,
        "trades": [],
        "equity_history": [],
        "last_run": None,
        "last_price": None,
        "note": "PAPER TRADING - fake money",
    }


def save_state(s):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    s["trades"] = s["trades"][-500:]
    s["equity_history"] = s["equity_history"][-MAX_HISTORY:]
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)


def buy(s, price, reason):
    spend = s["cash"]
    if spend < 10:
        return
    qty = spend * (1 - FEE) / price
    s["cash"], s["qty"], s["entry_price"] = 0.0, qty, price
    s["trades"].append({"time": now_iso(), "side": "BUY", "price": round(price, 2),
                        "qty": qty, "reason": reason})


def sell(s, price, reason):
    if s["qty"] <= 0:
        return
    proceeds = s["qty"] * price * (1 - FEE)
    pnl = proceeds - s["qty"] * s["entry_price"]
    s["trades"].append({"time": now_iso(), "side": "SELL", "price": round(price, 2),
                        "qty": s["qty"], "pnl": round(pnl, 2), "reason": reason})
    s["cash"], s["qty"], s["entry_price"] = proceeds, 0.0, None


def run(simulate=False):
    s = load_state()
    closes = fake_closes(seed=int(time.time())) if simulate else fetch_closes()
    if len(closes) < SLOW + 2:
        raise RuntimeError("Not enough candles")
    price = closes[-1]
    equity = s["cash"] + s["qty"] * price

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if s["day"] != today:
        s["day"], s["day_start_equity"], s["halted_today"] = today, equity, False

    if equity < s["day_start_equity"] * (1 - MAX_DAILY_LOSS):
        sell(s, price, "kill switch: daily loss limit")
        s["halted_today"] = True

    if not s["halted_today"]:
        if s["qty"] > 0 and price <= s["entry_price"] * (1 - STOP_LOSS):
            sell(s, price, "stop-loss")
        fast_now, slow_now = sma(closes, FAST), sma(closes, SLOW)
        fast_prev, slow_prev = sma(closes[:-1], FAST), sma(closes[:-1], SLOW)
        if fast_prev <= slow_prev and fast_now > slow_now and s["qty"] == 0:
            buy(s, price, "SMA bullish cross")
        elif fast_prev >= slow_prev and fast_now < slow_now and s["qty"] > 0:
            sell(s, price, "SMA bearish cross")
        s["last_signal"] = "UP" if fast_now > slow_now else "DOWN"

    equity = s["cash"] + s["qty"] * price
    s["last_price"] = round(price, 2)
    s["last_run"] = now_iso()
    s["equity"] = round(equity, 2)
    s["equity_history"].append({"t": s["last_run"], "equity": round(equity, 2), "price": round(price, 2)})
    save_state(s)
    print(f"{s['last_run']} price={price:.2f} equity={equity:.2f} "
          f"pos={'LONG' if s['qty'] > 0 else 'FLAT'} halted={s['halted_today']}")


if __name__ == "__main__":
    try:
        run(simulate="--simulate" in sys.argv)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
