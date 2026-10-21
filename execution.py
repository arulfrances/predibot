"""Safe execution boundary: paper records and manual-review queue only.

There is intentionally no Pocket Option browser/session automation here. A live
adapter must use an interface Pocket Option has explicitly authorized.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from risk import DayState, RiskConfig, TradeProposal, validate
from verification import VerificationResult, VerificationStatus


class ExecutionMode(str, Enum):
    PAPER = "paper"
    MANUAL_REVIEW = "manual_review"


class OrderAdapter(Protocol):
    """Interface for a permitted trade application adapter."""

    def submit(self, proposal: TradeProposal) -> str:
        """Submit one approved proposal and return the app's order reference."""


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    proposal: TradeProposal
    detail: str


class ExecutionBlocked(RuntimeError):
    """Execution stopped by mode or approval requirements."""


class ExecutionController:
    """Risk-gated routing; defaults to local paper mode and has no live adapter."""

    def __init__(
        self,
        config: RiskConfig,
        mode: ExecutionMode = ExecutionMode.PAPER,
        adapter: OrderAdapter | None = None,
    ) -> None:
        self.config = config
        self.mode = mode
        self.adapter = adapter
        self.pending: list[TradeProposal] = []

    def route(
        self,
        proposal: TradeProposal,
        state: DayState,
        *,
        approved: bool = False,
        verification: VerificationResult | None = None,
    ) -> ExecutionResult:
        """Validate risk first, then record paper intent or queue for review.

        This starter ships no live adapter. A reviewed item is only forwarded
        if a separately supplied, explicitly authorized adapter is injected.
        """
        if verification is None:
            raise ExecutionBlocked("Signal verification is required before execution")
        if verification.status is not VerificationStatus.READY_FOR_USER_REVIEW:
            raise ExecutionBlocked(f"Signal is not eligible: {verification.summary}")
        if (
            verification.asset.strip().casefold() != proposal.symbol.strip().casefold()
            or verification.direction != proposal.direction.strip().casefold()
            or verification.expiry_seconds != proposal.expiry_seconds
            or abs(verification.payout - proposal.payout) > 1e-9
            or verification.received_at.date() != proposal.signal_time
        ):
            raise ExecutionBlocked("Proposal does not match the signal that passed verification")

        validate(proposal, state, self.config)

        if self.mode is ExecutionMode.PAPER:
            return ExecutionResult("paper", proposal, "Recorded locally; no order was sent")

        if self.mode is ExecutionMode.MANUAL_REVIEW:
            if not approved:
                self.pending.append(proposal)
                return ExecutionResult(
                    "pending_review", proposal, "Queued for explicit human review; no order was sent"
                )
            if self.adapter is None:
                raise ExecutionBlocked(
                    "No authorized trade-app adapter is configured; proposal was not sent"
                )
            reference = self.adapter.submit(proposal)
            return ExecutionResult("submitted", proposal, f"Adapter reference: {reference}")

        raise ExecutionBlocked(f"Unsupported execution mode: {self.mode}")
