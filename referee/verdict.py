"""The scorecard: an ordered decay record, not a pass/fail flag.

A signal is interesting for what it survives *and* for where it dies. A
verdict therefore carries the full waterfall, so `KILLED_BY_PIT` and
`KILLED_BY_COSTS` are legibly different outcomes -- the first says the paper
was never real, the second says the paper was real and uninvestable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Gate(StrEnum):
    PIT = "pit"
    INTEGRITY = "integrity"
    RAW = "raw"
    ORTHOGONALIZE = "orthogonalize"
    COSTS = "costs"
    DSR = "dsr"
    PBO = "pbo"


#: The order is pre-registered. It is deliberately not reorderable at runtime:
#: choosing the order after seeing results is itself a form of overfitting.
GATE_ORDER: tuple[Gate, ...] = (
    Gate.PIT,
    Gate.INTEGRITY,
    Gate.RAW,
    Gate.ORTHOGONALIZE,
    Gate.COSTS,
    Gate.DSR,
    Gate.PBO,
)


@dataclass(frozen=True)
class Step:
    gate: Gate
    sharpe: float | None
    passed: bool
    detail: str
    #: Sharpe destroyed by this gate relative to the previous surviving step.
    give_up: float | None = None


@dataclass
class Verdict:
    signal: str
    family: str
    n_trials: int
    steps: list[Step] = field(default_factory=list)

    @property
    def survives(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    @property
    def died_at(self) -> Gate | None:
        for step in self.steps:
            if not step.passed:
                return step.gate
        return None

    @property
    def headline_sharpe(self) -> float | None:
        for step in self.steps:
            if step.gate is Gate.RAW:
                return step.sharpe
        return None

    @property
    def surviving_sharpe(self) -> float | None:
        live = [s.sharpe for s in self.steps if s.passed and s.sharpe is not None]
        return live[-1] if live else None

    def waterfall(self) -> str:
        """One-screen summary. This is the artefact a reviewer actually reads."""
        head = (
            f"{self.signal}   family={self.family}   "
            f"N={self.n_trials} (from ledger)\n" + "-" * 68
        )
        rows = []
        for s in self.steps:
            mark = "ok  " if s.passed else "DIED"
            sharpe = "   --" if s.sharpe is None else f"{s.sharpe:6.2f}"
            drop = "" if s.give_up is None else f"  ({s.give_up:+.2f})"
            rows.append(f"  {mark}  {s.gate.value:<14} SR {sharpe}{drop:<10}  {s.detail}")
        tail = (
            f"\n  VERDICT: survives"
            if self.survives
            else f"\n  VERDICT: killed at {self.died_at.value if self.died_at else '?'}"
        )
        return "\n".join([head, *rows, tail])
