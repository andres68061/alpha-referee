"""Run a signal through the gates in pre-registered order.

Contract for every gate implementation:

    gate(panel, signal, ctx) -> Step

A gate may lower the surviving Sharpe or kill the signal. It may never raise
the Sharpe, and it may never be skipped because it is inconvenient -- an
unimplemented gate raises rather than silently passing, so a scorecard can
never look better than the work behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from referee.verdict import GATE_ORDER, Gate, Step, Verdict
from trials.ledger import Trial, TrialLedger


class GateFn(Protocol):
    def __call__(self, panel: Any, signal: Any, ctx: "Context") -> Step: ...


@dataclass
class Context:
    ledger: TrialLedger
    family: str
    n_trials: int
    trial_sharpe_variance: float
    surviving_sharpe: float | None = None
    extras: dict[str, Any] | None = None


class NotImplementedGate(RuntimeError):
    """Raised when a gate has no implementation.

    Deliberately fatal. A missing gate must not be reported as a pass.
    """


def run_gauntlet(
    *,
    signal_name: str,
    family: str,
    trial: Trial,
    panel: Any,
    signal: Any,
    gates: dict[Gate, GateFn],
    ledger: TrialLedger,
) -> Verdict:
    ledger.verify()
    index = ledger.record(trial)

    ctx = Context(
        ledger=ledger,
        family=family,
        n_trials=ledger.n_trials(family),
        trial_sharpe_variance=_safe_variance(ledger, family),
    )
    verdict = Verdict(signal=signal_name, family=family, n_trials=ctx.n_trials)

    for gate in GATE_ORDER:
        fn = gates.get(gate)
        if fn is None:
            raise NotImplementedGate(
                f"gate {gate.value!r} has no implementation; "
                "a scorecard with a skipped gate is not a scorecard"
            )
        step = fn(panel, signal, ctx)
        if step.sharpe is not None and ctx.surviving_sharpe is not None:
            step = Step(
                gate=step.gate,
                sharpe=step.sharpe,
                passed=step.passed,
                detail=step.detail,
                give_up=step.sharpe - ctx.surviving_sharpe,
            )
        verdict.steps.append(step)
        if not step.passed:
            break
        if step.sharpe is not None:
            ctx.surviving_sharpe = step.sharpe

    ledger.complete(
        index,
        {
            "sharpe": verdict.headline_sharpe,
            "surviving_sharpe": verdict.surviving_sharpe,
            "survives": verdict.survives,
            "died_at": verdict.died_at.value if verdict.died_at else None,
        },
    )
    return verdict


def _safe_variance(ledger: TrialLedger, family: str) -> float:
    try:
        return ledger.trial_sharpe_variance(family)
    except ValueError:
        # First trials in a family: no dispersion estimate yet. The DSR gate
        # must refuse to deflate rather than assume a variance.
        return float("nan")
