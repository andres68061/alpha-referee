"""The ledger is the repo's central claim. It gets the most tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest  # noqa: E402

from trials.ledger import Trial, TrialLedger  # noqa: E402


def _trial(name="v1", family="fam"):
    return Trial(
        family=family, signal=name, params={"w": 1},
        universe="top200", start="2012-01-01", end="2025-12-31",
    )


def test_n_counts_originals_not_amendments(tmp_path):
    led = TrialLedger(tmp_path / "l.jsonl")
    for i in range(3):
        led.complete(led.record(_trial(f"v{i}")), {"sharpe": 0.1 * i})
    assert led.n_trials("fam") == 3, "amendments must not inflate N"
    assert len(led) == 6


def test_abandoned_trial_still_counts(tmp_path):
    """The whole point: a variant you started and gave up on still deflates."""
    led = TrialLedger(tmp_path / "l.jsonl")
    led.record(_trial("abandoned"))
    led.complete(led.record(_trial("kept")), {"sharpe": 1.4})
    assert led.n_trials("fam") == 2


def test_tampering_breaks_the_chain_at_a_named_index(tmp_path):
    p = tmp_path / "l.jsonl"
    led = TrialLedger(p)
    for i in range(3):
        led.complete(led.record(_trial(f"v{i}")), {"sharpe": 0.1 * i})
    led.verify()
    lines = p.read_text().splitlines()
    lines[3] = lines[3].replace('"sharpe": 0.1', '"sharpe": 9.9')
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="broken at index 4"):
        TrialLedger(p).verify()


def test_variance_refuses_on_one_trial(tmp_path):
    """A DSR with an assumed trial variance is an unfalsifiable pass."""
    led = TrialLedger(tmp_path / "l.jsonl")
    led.complete(led.record(_trial()), {"sharpe": 2.0})
    with pytest.raises(ValueError, match="at least 2"):
        led.trial_sharpe_variance("fam")


def test_families_are_separate(tmp_path):
    led = TrialLedger(tmp_path / "l.jsonl")
    led.record(_trial(family="lazy_prices"))
    led.record(_trial(family="lm_sentiment"))
    assert led.n_trials("lazy_prices") == 1
    assert led.n_trials("lm_sentiment") == 1
