"""Browser-based Predibot signal desk. Run locally with ``python webapp.py``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re
import secrets

from flask import Flask, flash, redirect, render_template, request, session, url_for

from risk import FIXED_STAKE_USD, RiskConfig


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_urlsafe(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("APP_ENV") == "production",
    MAX_CONTENT_LENGTH=16 * 1024,
)

RISK = RiskConfig()
CRYPTO_BASES = "BTC ETH SOL XRP ADA DOGE BNB AVAX LINK LTC DOT TRX BCH TON"
PAIR_RE = re.compile(rf"\b({CRYPTO_BASES.replace(' ', '|')})(?:\s*[/_-]?\s*(USDT|USD|USDC))?\b")
EXPIRY_RE = re.compile(r"\b(\d{1,3})\s*(?:M|MIN|MINS|MINUTE|MINUTES)\b")
DIRECTION_MAP = {
    "CALL": "UP", "BUY": "UP", "UP": "UP",
    "PUT": "DOWN", "SELL": "DOWN", "DOWN": "DOWN",
}


def parse_crypto_signal(message: str) -> tuple[str, str, int] | None:
    text = message.upper()
    if re.search(r"\b(?:OTC|EUR|GBP|JPY|AUD|CAD|CHF|NZD)\b", text):
        return None
    pair = PAIR_RE.search(text)
    direction = re.search(r"\b(CALL|PUT|BUY|SELL|UP|DOWN)\b", text)
    expiry = EXPIRY_RE.search(text)
    if not (pair and direction and expiry):
        return None
    minutes = int(expiry.group(1))
    if not 1 <= minutes <= 1440:
        return None
    return f"{pair.group(1)}/{pair.group(2) or 'USD'}", DIRECTION_MAP[direction.group(1)], minutes


@app.template_filter("localtime")
def localtime(value: str) -> str:
    """Format UTC timestamps in the browser's local time with client JS."""
    return value


@app.route("/")
def overview():
    return render_template("overview.html", signals=session.get("signals", []), risk=RISK, stake=FIXED_STAKE_USD)


@app.route("/signals", methods=["GET", "POST"])
def signals():
    if request.method == "POST":
        if not _valid_csrf():
            flash("Form expired. Please try again.", "error")
            return redirect(url_for("signals"))
        raw = request.form.get("signal", "").strip()[:2000]
        parsed = parse_crypto_signal(raw)
        if not parsed:
            flash("Could not parse that crypto signal. Try: BTC/USD CALL 1m or ETHUSDT PUT 5m.", "error")
            return redirect(url_for("signals"))
        pair, direction, minutes = parsed
        now = datetime.now(timezone.utc)
        rows = session.get("signals", [])
        rows.insert(0, {
            "pair": pair,
            "direction": direction,
            "entry_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=minutes)).isoformat(),
            "expiry_minutes": minutes,
            "status": "UNVERIFIED · no live feeds",
        })
        session["signals"] = rows[:20]
        flash("Signal added. Its timing is derived from the time you submitted it; market validation is unavailable.", "success")
        return redirect(url_for("signals"))
    token = session.setdefault("csrf_token", secrets.token_urlsafe(24))
    return render_template("signals.html", signals=session.get("signals", []), csrf_token=token)


@app.post("/signals/clear")
def clear_signals():
    if not _valid_csrf():
        flash("Form expired. Please try again.", "error")
    else:
        session.pop("signals", None)
        flash("This browser session's signal list was cleared.", "success")
    return redirect(url_for("signals"))


def _valid_csrf() -> bool:
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(submitted and expected and secrets.compare_digest(submitted, expected))


@app.route("/risk")
def risk():
    return render_template("risk.html", risk=RISK, stake=FIXED_STAKE_USD)


@app.route("/connections")
def connections():
    return render_template("connections.html")


@app.errorhandler(413)
def request_too_large(_error):
    return "Request too large. Signal text is limited to 16 KB.", 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
