"""Section headers must survive HTML stripping, or extraction silently fails."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corpus.edgar import Filing, html_to_text  # noqa: E402

HTML = """<html><head><style>.x{color:red}</style></head><body>
<div><b>Item 1A.</b>&nbsp;Risk&nbsp;Factors</div>
<p>The Company&#39;s business is subject to&mdash;risks.</p>
<div><b>Item 7.</b> Management&rsquo;s Discussion</div></body></html>"""


def test_item_headers_land_at_line_start():
    text = html_to_text(HTML)
    assert re.search(r"(?im)^\s*item\s+1a", text)
    assert re.search(r"(?im)^\s*item\s+7\.", text)


def test_style_and_entities_are_gone():
    text = html_to_text(HTML)
    assert "color:red" not in text
    assert "&nbsp;" not in text and "&#39;" not in text
    assert "Company's" in text


def test_archive_url_strips_leading_zeros_and_dashes():
    f = Filing(
        cik="0000320193", ticker="AAPL", form="10-K",
        accession="0000320193-23-000106", period_end="2023-09-30",
        filing_date="2023-11-03", acceptance_datetime="2023-11-02T18:08:27.000Z",
        primary_document="aapl-20230930.htm",
    )
    assert f.url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019323000106/aapl-20230930.htm"
    )
