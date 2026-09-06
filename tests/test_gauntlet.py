"""A missing gate must be fatal, never a silent pass."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest  # noqa: E402

from referee import Gate, NotImplementedGate, Step, run_gauntlet  # noqa: E402
from trials.ledger import Trial, TrialLedger  # noqa: E402


def _ok(sharpe):
    return lambda panel, signal, ctx: Step(
        gate=Gate.RAW, sharpe=sharpe, passed=True, detail="stub"
    )


def test_missing_gate_raises(tmp_path):
    led = TrialLedger(tmp_path / "l.jsonl")
    with pytest.raises(NotImplementedGate, match="pit"):
        run_gauntlet(
            signal_name="x", family="fam",
            trial=Trial(family="fam", signal="x", params={}, universe="u",
                        start="2012-01-01", end="2025-12-31"),
            panel=None, signal=None, gates={}, ledger=led,
        )
