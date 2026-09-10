"""Append-only record of what was run, when, on which commit, and what it said.

The trial ledger in ``trials/ledger.py`` records *what was tested* — the
pre-registered hypothesis. This is the other half: what was actually
*executed*. They answer different questions. The ledger answers "how many
strategies did you try before this one?", which is what the deflated Sharpe
needs. The run log answers "what produced this parquet, on what code, and did
it finish?", which is what anyone reproducing the result needs.

Both are append-only. Neither is ever edited to make a story tidier.

Usage::

    with runlog.run("corpus.fetch", top_n=200, start="2012-01-01") as rec:
        ...
        rec.note("2474 unique accessions cached")

Everything printed inside the block is teed to ``logs/<stamp>-<name>/stdout.log``
so a long console run is not lost when the terminal scrollback rolls over —
which is exactly how the first corpus download was nearly lost.
"""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

LOGS = Path(__file__).resolve().parents[1] / "logs"
INDEX = LOGS / "INDEX.md"

_INDEX_HEADER = """# Run log

Append-only. One line per execution, newest last. Written by
`referee/runlog.py`; do not hand-edit. Narrative decisions live in
`docs/DECISIONS.md` instead.

| started (UTC) | run | commit | status | seconds | params |
|---|---|---|---|---|---|
"""


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _commit() -> str:
    sha = _git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = bool(_git("status", "--porcelain"))
    return f"{sha}{'+dirty' if dirty else ''}"


class _Tee:
    """Write to the real stdout and to the run's log file at once."""

    def __init__(self, *streams: Any) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for s in self._streams:
            s.write(data)
            s.flush()
        return len(data)

    def flush(self) -> None:
        for s in self._streams:
            s.flush()

    def isatty(self) -> bool:
        return False


class Record:
    """Handle passed to the caller inside a ``run`` block."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.notes: list[str] = []
        self.outputs: list[str] = []

    def note(self, message: str) -> None:
        """Record a finding worth keeping in the run's metadata, not just stdout."""
        self.notes.append(message)

    def output(self, path: str | Path) -> None:
        """Record an artifact this run wrote."""
        self.outputs.append(str(path))


@contextmanager
def run(name: str, **params: Any) -> Iterator[Record]:
    """Log one execution: metadata, teed stdout, and an index line.

    A failing run is logged too, with its traceback and ``status: failed``.
    A run that vanishes because it crashed is a run that gets silently
    repeated with different parameters and remembered as the first attempt.
    """
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    directory = LOGS / f"{stamp}-{name.replace('.', '_')}"
    directory.mkdir(parents=True, exist_ok=True)

    record = Record(directory)
    meta: dict[str, Any] = {
        "run": name,
        "started_utc": started.isoformat(),
        "commit": _commit(),
        "argv": sys.argv,
        "python": sys.version.split()[0],
        "params": {k: str(v) for k, v in params.items()},
    }

    status = "ok"
    log_path = directory / "stdout.log"
    real_stdout = sys.stdout
    with log_path.open("w") as fh:
        sys.stdout = _Tee(real_stdout, fh)
        try:
            yield record
        except BaseException as exc:  # noqa: BLE001
            status = "failed"
            meta["error"] = f"{type(exc).__name__}: {exc}"
            fh.write("\n" + traceback.format_exc())
            raise
        finally:
            sys.stdout = real_stdout
            ended = datetime.now(timezone.utc)
            meta.update(
                ended_utc=ended.isoformat(),
                seconds=round((ended - started).total_seconds(), 1),
                status=status,
                notes=record.notes,
                outputs=record.outputs,
            )
            (directory / "meta.json").write_text(json.dumps(meta, indent=2))

            if not INDEX.exists():
                INDEX.write_text(_INDEX_HEADER)
            params_cell = ", ".join(f"{k}={v}" for k, v in meta["params"].items()) or "—"
            with INDEX.open("a") as idx:
                idx.write(
                    f"| {started:%Y-%m-%d %H:%M} | [{name}]({directory.name}/) "
                    f"| `{meta['commit']}` | {status} | {meta['seconds']} "
                    f"| {params_cell} |\n"
                )
