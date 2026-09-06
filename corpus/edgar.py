"""EDGAR client: filing index and full text, with the timestamp that matters.

The one field this whole project depends on is ``acceptanceDateTime`` — the
moment EDGAR accepted the document, which is the earliest instant any trader
could have read it. It is not ``filingDate`` (a date, no time, occasionally a
day later) and it is emphatically not the fiscal period end, which is what a
careless replication aligns on and which sits two to three months in the past.

Everything here is cached by accession number. A filing is downloaded once.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

import requests

#: SEC fair-access policy requires a descriptive UA with a contact address and
#: caps traffic at 10 requests/second. We run below the cap deliberately.
USER_AGENT = "alpha-referee research andraeo@outlook.com"
MAX_RPS = 8.0

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SUBMISSIONS_PART = "https://data.sec.gov/submissions/{name}"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"

CACHE = Path(__file__).resolve().parent / "cache"


@dataclass(frozen=True)
class Filing:
    cik: str
    ticker: str
    form: str
    accession: str
    #: Fiscal period end. Present for reference only — never align a signal on it.
    period_end: str
    filing_date: str
    #: The field the point-in-time gate audits against.
    acceptance_datetime: str
    primary_document: str

    @property
    def url(self) -> str:
        return _ARCHIVE.format(
            cik_int=int(self.cik),
            acc_nodash=self.accession.replace("-", ""),
            doc=self.primary_document,
        )


class _RateLimiter:
    def __init__(self, rps: float) -> None:
        self._min_gap = 1.0 / rps
        self._last = 0.0

    def wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self._min_gap:
            time.sleep(self._min_gap - gap)
        self._last = time.monotonic()


class EdgarClient:
    def __init__(self, user_agent: str = USER_AGENT, cache_dir: Path = CACHE) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        )
        self.cache = cache_dir
        (self.cache / "json").mkdir(parents=True, exist_ok=True)
        (self.cache / "text").mkdir(parents=True, exist_ok=True)
        self._limiter = _RateLimiter(MAX_RPS)

    # -- http ----------------------------------------------------------

    def _get(self, url: str, *, retries: int = 4) -> requests.Response:
        for attempt in range(retries):
            self._limiter.wait()
            resp = self.session.get(url, timeout=45)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429, 500, 502, 503):
                # SEC throttles by returning 403 as well as 429. Back off hard;
                # hammering gets the whole IP blocked for the day.
                time.sleep(2.0 * (2**attempt))
                continue
            resp.raise_for_status()
        raise RuntimeError(f"giving up on {url} after {retries} attempts")

    # -- ticker -> cik -------------------------------------------------

    def ticker_to_cik(self) -> dict[str, str]:
        path = self.cache / "json" / "company_tickers.json"
        if not path.exists():
            path.write_text(self._get(_TICKERS_URL).text)
        payload = json.loads(path.read_text())
        return {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in payload.values()
        }

    # -- filing index --------------------------------------------------

    def filings(self, ticker: str, cik: str, forms=("10-K",)) -> list[Filing]:
        """Every filing of the requested forms, across the full history.

        ``filings.recent`` in the submissions JSON holds only the most recent
        ~1,000 filings. Older ones live in separate files listed under
        ``filings.files``. Reading only ``recent`` is a silent truncation that
        would quietly shorten the sample for long-lived firms — exactly the
        kind of bias that shows up as a suspiciously clean backtest.
        """
        path = self.cache / "json" / f"CIK{cik}.json"
        if not path.exists():
            path.write_text(self._get(_SUBMISSIONS_URL.format(cik=cik)).text)
        payload = json.loads(path.read_text())

        blocks = [payload["filings"]["recent"]]
        for extra in payload["filings"].get("files", []):
            part = self.cache / "json" / extra["name"]
            if not part.exists():
                part.write_text(
                    self._get(_SUBMISSIONS_PART.format(name=extra["name"])).text
                )
            blocks.append(json.loads(part.read_text()))

        out: list[Filing] = []
        for block in blocks:
            for i, form in enumerate(block.get("form", [])):
                if form not in forms:
                    continue
                doc = block["primaryDocument"][i]
                if not doc:
                    continue
                out.append(
                    Filing(
                        cik=cik,
                        ticker=ticker,
                        form=form,
                        accession=block["accessionNumber"][i],
                        period_end=block["reportDate"][i],
                        filing_date=block["filingDate"][i],
                        acceptance_datetime=block["acceptanceDateTime"][i],
                        primary_document=doc,
                    )
                )
        return sorted(out, key=lambda f: f.acceptance_datetime)

    # -- document text -------------------------------------------------

    def text(self, filing: Filing) -> str:
        """Plain text of the primary document, cached by accession."""
        path = self.cache / "text" / f"{filing.accession}.txt"
        if path.exists():
            return path.read_text(errors="ignore")
        body = html_to_text(self._get(filing.url).text)
        path.write_text(body)
        return body


# ---------------------------------------------------------------- html


_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_ENTITY = {
    "&nbsp;": " ", "&#160;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&rsquo;": "'", "&lsquo;": "'",
    "&ldquo;": '"', "&rdquo;": '"', "&mdash;": "—", "&ndash;": "–",
}
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    """Dependency-free HTML strip, tuned for EDGAR filings.

    Block-level tags become newlines so that Item headers survive as line
    starts — section extraction downstream depends on that. Modern filings are
    inline XBRL, which is still HTML for our purposes.
    """
    text = _SCRIPT_STYLE.sub(" ", html)
    text = re.sub(r"<(br|/p|/div|/tr|/h[1-6]|/li)[^>]*>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    for k, v in _ENTITY.items():
        text = text.replace(k, v)
    text = re.sub(r"&#\d+;", " ", text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def iter_universe_filings(
    client: EdgarClient, tickers: list[str], forms=("10-K",)
) -> Iterator[tuple[str, list[Filing]]]:
    mapping = client.ticker_to_cik()
    for ticker in tickers:
        cik = mapping.get(ticker.upper())
        if cik is None:
            yield ticker, []
            continue
        yield ticker, client.filings(ticker, cik, forms=forms)


def filings_to_frame(filings: list[Filing]):
    import pandas as pd

    return pd.DataFrame([asdict(f) for f in filings])
