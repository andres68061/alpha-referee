"""Append-only, hash-chained trial ledger.

Why this file exists
--------------------
The Deflated Sharpe Ratio corrects a reported Sharpe for the fact that you
tried ``N`` configurations and are showing the best one. It is the standard
guard against backtest overfitting, and it is almost always applied
dishonestly -- not through bad faith, but because ``N`` is supplied by the
same person who chose which result to publish, *after* the search is over.
Nobody counts the variants they abandoned in the first hour.

This ledger makes ``N`` a measurement rather than a claim:

  * a ``Trial`` is written **before** the run, not after, so an abandoned
    variant is already on the record;
  * entries are hash-chained, so removing or editing one breaks ``verify()``
    at a named index;
  * ``n_trials(family)`` is what the referee passes to the DSR. The
    researcher never types the number.

The design is lifted from the evidence ledger in ``equity-research/vesp/state.py``
and applied to a different failure mode: there it proves a thesis preceded the
evidence; here it proves a trial count preceded the result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class Trial:
    """One configuration of one signal, recorded before it is run.

    ``family`` is the multiple-testing unit. Every variant that shares a family
    counts against that family's ``N``. Choosing the family boundary is the one
    judgement call left to the researcher, so it is stated in the
    pre-registration and never changed afterwards.
    """

    family: str
    signal: str
    params: dict[str, Any]
    universe: str
    start: str
    end: str
    note: str = ""
    recorded_at: str = field(default_factory=_utcnow)

    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical(asdict(self)).encode()).hexdigest()


@dataclass(frozen=True)
class Entry:
    index: int
    prev_hash: str
    trial: Trial
    outcome: dict[str, Any] | None = None
    #: Index of the entry this one amends, or ``None`` if this is the original
    #: record of a trial. Only originals count toward ``N``; an amendment is the
    #: same trial coming back with its result, not a second experiment.
    amends: int | None = None

    def entry_hash(self) -> str:
        body = {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "trial": asdict(self.trial),
            "outcome": self.outcome,
            "amends": self.amends,
        }
        return hashlib.sha256(_canonical(body).encode()).hexdigest()


class TrialLedger:
    """JSONL-backed chain. One file per project, never rewritten in place."""

    def __init__(self, path: str | Path = "trials/ledger.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[Entry] = list(self._load())

    # -- reading -------------------------------------------------------

    def _load(self) -> Iterator[Entry]:
        if not self.path.exists():
            return
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            yield Entry(
                index=raw["index"],
                prev_hash=raw["prev_hash"],
                trial=Trial(**raw["trial"]),
                outcome=raw.get("outcome"),
                amends=raw.get("amends"),
            )

    def __len__(self) -> int:
        return len(self._entries)

    def n_trials(self, family: str) -> int:
        """The honest ``N`` for a multiple-testing family.

        This is the only number the referee will accept for a DSR. It counts
        every recorded variant in the family, including the ones that were
        started and abandoned -- which is precisely the population the
        deflation is supposed to correct for.
        """
        return sum(
            1
            for e in self._entries
            if e.trial.family == family and e.amends is None
        )

    def trial_sharpe_variance(self, family: str) -> float:
        """Cross-trial variance of the observed Sharpes in a family.

        The DSR needs the dispersion of trial Sharpes, not just their count.
        Reading it from the ledger rather than assuming a value is the second
        half of making the correction honest.
        """
        vals = [
            e.outcome["sharpe"]
            for e in self._entries
            if e.trial.family == family
            and e.outcome
            and e.outcome.get("sharpe") is not None
        ]
        if len(vals) < 2:
            raise ValueError(
                f"family {family!r} has {len(vals)} completed trial(s); "
                "a deflated Sharpe needs at least 2 to estimate trial variance"
            )
        mean = sum(vals) / len(vals)
        return sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)

    # -- writing -------------------------------------------------------

    def record(self, trial: Trial) -> int:
        """Append a trial *before* it is run. Returns its index."""
        prev = self._entries[-1].entry_hash() if self._entries else GENESIS
        entry = Entry(index=len(self._entries), prev_hash=prev, trial=trial)
        self._append(entry)
        return entry.index

    def complete(self, index: int, outcome: dict[str, Any]) -> None:
        """Attach the result to a recorded trial by appending an amendment.

        The original entry is never edited -- an amendment is a new link in the
        chain that carries the same trial with its outcome filled in. History is
        therefore additive, and a result cannot be quietly detached from the
        trial that produced it.
        """
        original = self._entries[index]
        prev = self._entries[-1].entry_hash()
        amended = Entry(
            index=len(self._entries),
            prev_hash=prev,
            trial=original.trial,
            outcome=outcome,
            amends=index,
        )
        self._append(amended)

    def _append(self, entry: Entry) -> None:
        self._entries.append(entry)
        with self.path.open("a") as fh:
            fh.write(
                json.dumps(
                    {
                        "index": entry.index,
                        "prev_hash": entry.prev_hash,
                        "trial": asdict(entry.trial),
                        "outcome": entry.outcome,
                        "amends": entry.amends,
                        "entry_hash": entry.entry_hash(),
                    },
                    default=str,
                )
                + "\n"
            )

    # -- integrity -----------------------------------------------------

    def verify(self) -> None:
        """Raise naming the first broken link, rather than failing vaguely."""
        prev = GENESIS
        for entry in self._entries:
            if entry.prev_hash != prev:
                raise ValueError(
                    f"trial ledger broken at index {entry.index}: "
                    f"expected prev_hash {prev[:12]}..., found {entry.prev_hash[:12]}..."
                )
            prev = entry.entry_hash()
