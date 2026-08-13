from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class MarketType(StrEnum):
    BINARY = "binary"
    MULTI_OUTCOME = "multi_outcome"


class MarketStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"
    INVALID = "invalid"


class ResolutionOutcome(StrEnum):
    YES = "yes"
    NO = "no"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class Market:
    """A provider-neutral description of a prediction market."""

    provider: str
    external_id: str
    question: str
    market_type: MarketType
    status: MarketStatus
    yes_outcome_id: str | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    topics: tuple[str, ...] = ()
    raw_payload: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.external_id}"


@dataclass(frozen=True, slots=True)
class ForecastSnapshot:
    """A time-stamped forecast that can later be scored against a resolution."""

    market_id: str
    observed_at: datetime
    probability_yes: Decimal
    volume: Decimal | None = None
    open_interest: Decimal | None = None
    liquidity: Decimal | None = None

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.probability_yes <= Decimal("1"):
            raise ValueError("probability_yes must be between zero and one")


@dataclass(frozen=True, slots=True)
class Resolution:
    market_id: str
    outcome: ResolutionOutcome
    resolved_at: datetime
    source: str
    is_verified: bool = False
