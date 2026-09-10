"""Text extraction: headers must survive, and invisible content must not."""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corpus.edgar import Filing  # noqa: E402
from corpus.parse import html_to_text  # noqa: E402

HTML = """<html><head><style>.x{color:red}</style></head><body>
<div><b>Item 1A.</b>&nbsp;Risk&nbsp;Factors</div>
<p>The Company&#39;s business is subject to&mdash;risks.</p>
<div><b>Item 7.</b> Management&rsquo;s Discussion</div></body></html>"""

IXBRL = """<html><body>
<ix:header><ix:hidden><ix:nonNumeric name="dei:EntityCentralIndexKey">
http://fasb.org/us-gaap/2025#LongTermDebtNoncurrent</ix:nonNumeric></ix:hidden></ix:header>
<div style="display: none">Draft &mdash; do not circulate</div>
<div><b>Item 7.</b> Management&rsquo;s Discussion</div>
<table><tr><td>Net sales</td><td><ix:nonFraction>391,035</ix:nonFraction></td></tr>
<tr><td>Cost of sales</td><td>210,352</td></tr></table>
</body></html>"""


def test_item_headers_land_at_line_start():
    text = html_to_text(HTML)
    assert re.search(r"(?im)^\s*item\s+1a", text)
    assert re.search(r"(?im)^\s*item\s+7\.", text)


def test_style_and_entities_are_gone():
    text = html_to_text(HTML)
    assert "color:red" not in text
    assert "&nbsp;" not in text and "&#39;" not in text
    assert "Company's" in text


def test_ixbrl_hidden_facts_are_dropped():
    """The pollution that arrives on the iXBRL phase-in schedule, not on news."""
    text = html_to_text(IXBRL)
    assert "fasb.org" not in text
    assert "do not circulate" not in text


def test_displayed_ixbrl_numbers_survive():
    """`ix:nonFraction` wraps figures the reader sees; dropping it guts the filing."""
    text = html_to_text(IXBRL)
    assert "391,035" in text


def test_table_rows_stay_on_their_own_lines():
    lines = [ln for ln in html_to_text(IXBRL).splitlines() if "Net sales" in ln]
    assert lines and "Cost of sales" not in lines[0]


def test_unparseable_document_raises_rather_than_returning_empty():
    """An empty string would sail through as a maximally dissimilar document."""
    with pytest.raises(ValueError):
        html_to_text("   ")


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


def test_xhtml_with_xml_declaration_parses():
    """lxml refuses a str carrying an encoding declaration; filings do carry one."""
    doc = (
        '<?xml version="1.0" encoding="windows-1252"?>'
        "<html><body><p>Item 7. Discussion &mdash; caf&#233;</p></body></html>"
    )
    text = html_to_text(doc)
    assert text.startswith("Item 7.")
    assert "café" in text
    assert "<?xml" not in text
