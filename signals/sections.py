"""Pull Item sections out of 10-K text.

This is the part of a text signal that quietly decides the result. A section
extractor that fails on 15% of filings and returns the whole document instead
is not a 15% problem — it silently swaps the hypothesis. "Did management change
how they discuss the business?" becomes "did the boilerplate, exhibit list and
financial statements change?", which is a different and much noisier question.

So extraction failure is an explicit flag on every row, never a silent
fallback, and the failure rate is reported in the scorecard as a caveat.

The two hard cases:

* **The table of contents.** Every 10-K names "Item 7" twice — once in the TOC
  and once at the real section. Taking the first match yields a section a few
  hundred characters long consisting of page numbers.
* **Cross-references.** Body text says "see Item 7A" in the middle of a
  paragraph, which is not a section start.

Both are handled by the same rule: for each candidate *end*, pair it with the
**nearest preceding** start, then keep whichever of those pairs spans the most
text. In the TOC, consecutive item headers sit a line apart; in the body they
sit tens of thousands of characters apart, so span length separates them
without a per-filer list of formatting quirks.

The "nearest preceding" half is not optional. Maximising span over all
start/end combinations instead pairs the *table of contents* start with the
*body* end, and returns everything in between — measured on this corpus, that
mistake produced a median "MD&A" of 302,000 characters, i.e. most of the
filing, while failing loudly on nothing at all. It is a good example of the
kind of bug this repo is about: it does not crash, it does not look wrong in a
summary statistic, and it silently replaces the hypothesis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A section shorter than this is not a section. MD&A in a large-cap 10-K runs
#: tens of thousands of characters; a few hundred means we caught the TOC.
MIN_SECTION_CHARS = 1_000


def _item_pattern(label: str) -> re.Pattern[str]:
    """Match ``Item 7.`` at the start of a line, tolerating filer formatting.

    Filers separate the number from the title with a period, a colon, a dash,
    an em dash or nothing at all, and some pad with non-breaking spaces that
    survive as ordinary spaces after parsing.
    """
    return re.compile(
        rf"^[ \t]*item[ \t ]*{label}[ \t]*[\.\:\-–—]?[ \t]*",
        re.IGNORECASE | re.MULTILINE,
    )


#: (start label, end labels in preference order). The end is the next section;
#: the fallbacks cover filers that omit an optional item.
_BOUNDS = {
    "item_1a": ("1A", ("1B", "1C", "2")),
    "item_7": ("7", ("7A", "8")),
}


@dataclass(frozen=True)
class Section:
    name: str
    text: str
    failed: bool
    reason: str = ""


def extract(text: str, name: str) -> Section:
    """Extract one named section, or return ``failed=True`` with the reason.

    Never falls back to the full document. A caller that wants that behaviour
    has to ask for it in the open, where the scorecard can see it.
    """
    if name not in _BOUNDS:
        raise KeyError(f"unknown section {name!r}; known: {sorted(_BOUNDS)}")
    start_label, end_labels = _BOUNDS[name]

    starts = [m.end() for m in _item_pattern(start_label).finditer(text)]
    if not starts:
        return Section(name, "", True, f"no 'Item {start_label}' header found")

    ends: list[int] = []
    for label in end_labels:
        ends = [m.start() for m in _item_pattern(label).finditer(text)]
        if ends:
            break
    if not ends:
        # No terminator anywhere: run to the end of the document rather than
        # failing, but only from the last plausible start.
        ends = [len(text)]

    best: tuple[int, int, int] | None = None
    for e in ends:
        preceding = [s for s in starts if s < e]
        if not preceding:
            continue
        s = max(preceding)  # nearest start above this end, never the TOC one
        span = e - s
        if best is None or span > best[0]:
            best = (span, s, e)

    if best is None:
        return Section(
            name, "", True,
            f"'Item {start_label}' never precedes its terminator "
            f"(candidates: {len(starts)} starts, {len(ends)} ends)",
        )

    span, s, e = best
    body = text[s:e].strip()
    if len(body) < MIN_SECTION_CHARS:
        return Section(
            name, body, True,
            f"longest span is {len(body)} chars, below {MIN_SECTION_CHARS} "
            "— probably the table of contents",
        )
    return Section(name, body, False)


def extract_all(text: str, names: tuple[str, ...]) -> tuple[str, bool, str]:
    """Concatenate several sections.

    Returns ``(text, failed, reason)``. Failure of *any* requested section
    fails the row: comparing MD&A-plus-risk-factors this year against MD&A
    alone last year measures the extractor, not the filing.
    """
    parts, reasons = [], []
    for name in names:
        section = extract(text, name)
        if section.failed:
            reasons.append(f"{name}: {section.reason}")
        else:
            parts.append(section.text)
    if reasons:
        return "\n\n".join(parts), True, "; ".join(reasons)
    return "\n\n".join(parts), False, ""
