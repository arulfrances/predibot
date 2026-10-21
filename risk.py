"""Offline risk checks for a fixed-expiry, paper-only options research bot."""

from dataclasses import dataclass
from datetime import date

FIXED_STAKE_USD = 1.0


@dataclass(frozen=True)
class RiskConfig:
    starting_balance: float = 1000.0
    max_stake_fraction: float = 0.01
    max_daily_loss_fraction: float = 0.03
    max_trades_per_day: int = 10
    max_consecutive_losses: int = 3
    minimum_payout: float = 0.85


@dataclass(frozen=True)
class TradeProposal:
    symbol: str
    direction: str
    stake: float
    payout: float
    expiry_seconds: int
    signal_time: date


@dataclass(frozen=True)
class DayState:
    day: date
    realized_pnl: float = 0.0
    trades: int = 0
    consecutive_losses: int = 0


class RiskRejected(ValueError):
    """Proposal rejected by a configured risk guardrail."""


def validate(proposal: TradeProposal, state: DayState, config: RiskConfig) -> None:
    """Raise RiskRejected unless a proposed paper trade passes every guard."""
    if proposal.signal_time != state.day:
        raise RiskRejected("Signal date does not match the active trading day")
    if not proposal.symbol.strip():
        raise RiskRejected("Symbol is required")
    if proposal.direction.strip().lower() not in {"call", "put"}:
        raise RiskRejected("Direction must be Call or Put")
    if proposal.expiry_seconds <= 0:
        raise RiskRejected("Expiry must be positive")
    if proposal.stake != FIXED_STAKE_USD:
        raise RiskRejected("Stake must be exactly $1.00")
    if proposal.stake > config.starting_balance * config.max_stake_fraction:
        raise RiskRejected("Stake exceeds the configured fraction of starting balance")
    if not 0 <= proposal.payout <= 1:
        raise RiskRejected("Payout must be expressed as a fraction between 0 and 1")
    if proposal.payout < config.minimum_payout:
        raise RiskRejected("Payout is below the configured minimum")
    if state.trades >= config.max_trades_per_day:
        raise RiskRejected("Daily trade limit reached")
    if state.consecutive_losses >= config.max_consecutive_losses:
        raise RiskRejected("Consecutive-loss limit reached")
    if state.realized_pnl <= -(config.starting_balance * config.max_daily_loss_fraction):
        raise RiskRejected("Daily loss limit reached")
    if state.realized_pnl - proposal.stake <= -(config.starting_balance * config.max_daily_loss_fraction):
        raise RiskRejected("This stake could breach the daily loss limit")
