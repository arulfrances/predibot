"""Fail-closed checks for Pocket Option Telegram signal evidence.

The result is an evidence gate, not a predicted win probability. Connectors for
Telegram, Pocket Option quotes, market trends, and news are intentionally
separate from this deterministic evaluator.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Direction(str, Enum):
    CALL = "call"
    PUT = "put"


class VerificationStatus(str, Enum):
    HOLD = "hold"
    REJECT = "reject"
    READY_FOR_USER_REVIEW = "ready_for_user_review"


@dataclass(frozen=True)
class TelegramSignal:
    source_username: str
    source_chat_id: int | None
    source_verified: bool
    asset: str
    direction: str
    received_at: datetime
    expiry_seconds: int
    payout: float
    is_otc: bool = False


@dataclass(frozen=True)
class MarketEvidence:
    quote_asset: str | None = None
    quote_price: float | None = None
    quote_source: str | None = None
    quote_observed_at: datetime | None = None
    quote_is_platform_authoritative: bool = False
    trend_by_horizon: dict[str, str] = field(default_factory=dict)
    trend_asset_by_horizon: dict[str, str] = field(default_factory=dict)
    trend_source_by_horizon: dict[str, str] = field(default_factory=dict)
    trend_observed_at_by_horizon: dict[str, datetime] = field(default_factory=dict)
    news_risk: str = "unknown"  # clear, elevated, high, unknown
    news_relevant_to_asset: bool | None = None
    news_source: str | None = None
    news_observed_at: datetime | None = None
    minutes_to_relevant_event: float | None = None


@dataclass(frozen=True)
class VerificationPolicy:
    expected_username: str = "pocketsignalbot"
    expected_chat_id: int | None = None
    minimum_payout: float = 0.85
    maximum_signal_age_seconds: int = 15
    maximum_evidence_age_seconds: int = 30
    maximum_news_age_seconds: int = 120
    news_blackout_minutes: int = 5
    required_trend_horizons: tuple[str, ...] = ("1m", "5m")


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    asset: str
    direction: str | None
    received_at: datetime
    expiry_seconds: int
    payout: float
    checks: tuple[tuple[str, str], ...]
    summary: str


def _aware(dt: datetime | None) -> bool:
    return dt is not None and dt.tzinfo is not None and dt.utcoffset() is not None


def _age_seconds(now: datetime, then: datetime | None) -> float | None:
    if not _aware(then):
        return None
    return (now - then).total_seconds()


def _normalize_direction(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized in {"call", "up", "buy", "bullish"}:
        return Direction.CALL.value
    if normalized in {"put", "down", "sell", "bearish"}:
        return Direction.PUT.value
    return None


def verify_signal(
    signal: TelegramSignal,
    evidence: MarketEvidence,
    *,
    policy: VerificationPolicy = VerificationPolicy(),
    now: datetime | None = None,
) -> VerificationResult:
    """Check identity, completeness, freshness, payout, trend, and news.

    HOLD means required data is missing or unsupported. REJECT means known
    evidence conflicts with a configured rule. READY_FOR_USER_REVIEW never
    submits an order; the user must still review the details separately.
    """
    now = now or datetime.now(timezone.utc)
    if not _aware(now):
        raise ValueError("now must include a timezone")

    checks: list[tuple[str, str]] = []
    blockers: list[str] = []
    known_failures: list[str] = []
    asset_key = signal.asset.strip().casefold()
    is_otc = signal.is_otc or asset_key.endswith(("_otc", "-otc", " otc"))

    source_ok = (
        signal.source_verified
        and policy.expected_chat_id is not None
        and signal.source_chat_id == policy.expected_chat_id
        and signal.source_username.strip().lstrip("@").casefold() == policy.expected_username.casefold()
    )
    checks.append(("telegram_source", "pass" if source_ok else "missing or not verified"))
    if not source_ok:
        blockers.append("Telegram chat identity has not been verified")

    signal_direction = _normalize_direction(signal.direction)
    complete = bool(signal.asset.strip()) and signal_direction is not None and signal.expiry_seconds > 0
    complete = complete and 0 < signal.payout <= 1 and _aware(signal.received_at)
    checks.append(("signal_fields", "pass" if complete else "missing or invalid fields"))
    if not complete:
        known_failures.append("Signal fields are incomplete or invalid")

    age = _age_seconds(now, signal.received_at)
    fresh = (
        age is not None
        and age >= 0
        and age <= policy.maximum_signal_age_seconds
        and age < signal.expiry_seconds
    )
    checks.append(("signal_freshness", "pass" if fresh else "stale or timestamp unavailable"))
    if not fresh:
        known_failures.append("Signal is stale, expired, future-dated, or has no timezone")

    payout_ok = 0 < signal.payout <= 1 and signal.payout >= policy.minimum_payout
    checks.append(("payout_floor", "pass" if payout_ok else f"below {policy.minimum_payout:.0%} minimum"))
    if not payout_ok:
        known_failures.append("Payout is below the configured high-payout threshold")

    quote_age = _age_seconds(now, evidence.quote_observed_at)
    quote_ok = (
        bool(evidence.quote_asset)
        and evidence.quote_asset.strip().casefold() == signal.asset.strip().casefold()
        and evidence.quote_price is not None
        and evidence.quote_price > 0
        and bool(evidence.quote_source)
        and evidence.quote_is_platform_authoritative
        and quote_age is not None
        and 0 <= quote_age <= policy.maximum_evidence_age_seconds
    )
    if not evidence.quote_is_platform_authoritative:
        quote_ok = False
        quote_state = "fresh authoritative Pocket Option quote unavailable"
    else:
        quote_state = "pass" if quote_ok else "fresh quote unavailable"
    checks.append(("current_quote", "pass" if quote_ok else quote_state))
    if not quote_ok:
        blockers.append("A fresh authoritative quote is unavailable")

    trend_complete = True
    trend_conflict = False
    observed_sources: set[str] = set()
    for horizon in policy.required_trend_horizons:
        direction = _normalize_direction(evidence.trend_by_horizon.get(horizon))
        source = evidence.trend_source_by_horizon.get(horizon, "").strip()
        trend_asset = evidence.trend_asset_by_horizon.get(horizon, "").strip()
        trend_age = _age_seconds(now, evidence.trend_observed_at_by_horizon.get(horizon))
        trend_is_current = trend_age is not None and 0 <= trend_age <= policy.maximum_evidence_age_seconds
        if (
            direction is None
            or not source
            or trend_asset.casefold() != signal.asset.strip().casefold()
            or not trend_is_current
        ):
            trend_complete = False
            continue
        observed_sources.add(source.casefold())
        if direction != signal_direction:
            trend_conflict = True
    bot_name = policy.expected_username.casefold().lstrip("@")
    if not observed_sources or any(bot_name in source for source in observed_sources):
        trend_complete = False
    if is_otc:
        trend_complete = False
        trend_state = "external trend cannot validate synthetic OTC pricing"
    elif trend_conflict:
        trend_state = "trend conflicts with signal"
    else:
        trend_state = "pass" if trend_complete else "independent multi-horizon trend evidence unavailable"
    checks.append(("trend_alignment", trend_state))
    if trend_conflict:
        known_failures.append("Independent trend evidence conflicts with the signal")
    elif not trend_complete:
        blockers.append("Independent trend confirmation is incomplete")

    news_age = _age_seconds(now, evidence.news_observed_at)
    news_fresh = (
        news_age is not None
        and 0 <= news_age <= policy.maximum_news_age_seconds
        and bool(evidence.news_source)
    )
    news_risk = evidence.news_risk.strip().casefold()
    if not news_fresh or news_risk == "unknown" or evidence.news_relevant_to_asset is not True:
        news_state = "current news check unavailable"
        blockers.append("Current relevant news/event check is unavailable")
    elif news_risk in {"elevated", "high"}:
        news_state = f"{news_risk} news/event risk"
        known_failures.append("Relevant news/event risk exceeds the configured limit")
    elif (
        evidence.minutes_to_relevant_event is not None
        and 0 <= evidence.minutes_to_relevant_event <= policy.news_blackout_minutes
    ):
        news_state = "relevant event inside blackout window"
        known_failures.append("A scheduled relevant event is too close to the signal expiry")
    elif news_risk == "clear":
        news_state = "pass"
    else:
        news_state = "unrecognized news risk value"
        blockers.append("News risk result is not recognized")
    checks.append(("news_risk", news_state))

    if known_failures:
        status = VerificationStatus.REJECT
        summary = "; ".join(known_failures)
    elif blockers:
        status = VerificationStatus.HOLD
        summary = "; ".join(blockers)
    else:
        status = VerificationStatus.READY_FOR_USER_REVIEW
        summary = "Evidence checks passed; inspect the signal and confirm manually"

    return VerificationResult(
        status=status,
        asset=signal.asset,
        direction=signal_direction,
        received_at=signal.received_at,
        expiry_seconds=signal.expiry_seconds,
        payout=signal.payout,
        checks=tuple(checks),
        summary=summary,
    )
