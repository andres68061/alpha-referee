"""HTML -> text for EDGAR filings, using a real parser.

Two things distinguish this from a regex strip, and both matter for a document
similarity signal:

1. **Non-rendered content is dropped.** Modern filings are inline XBRL. An
   iXBRL document carries an `ix:header` and often an `ix:hidden` block holding
   machine-readable facts and taxonomy URIs that no reader ever sees. A regex
   that deletes tags but keeps everything between them ingests all of it.

   This is not cosmetic. iXBRL arrived on a phase-in schedule — measured on our
   own corpus, 0% of filings carried taxonomy-URI pollution through 2020, 8.7%
   in 2021, and 96% by 2025. A year-over-year similarity signal fed that text
   sees every firm's language change at the same moment, and reads a filing
   format mandate as a market-wide event.

2. **Block structure survives.** Item headers must remain at the start of a
   line for section extraction to find them, and table cells must not run
   together into a single unbroken line of digits.

`lxml` is required. The fallback is deliberately absent: silently degrading to
a worse parser would put two incomparable text representations in the same
corpus, which is the kind of quiet inconsistency this repo exists to catch.
"""

from __future__ import annotations

import re

from lxml import etree, html as lxml_html

#: Bump when the extraction changes in a way that alters the text. The text
#: cache is keyed on this, so old text is never silently mixed with new.
PARSER_VERSION = 2

#: Elements whose text is never displayed, matched on the bare tag name.
_DROP_BARE = {"script", "style", "head", "meta", "link", "title", "xbrl"}

#: Inline-XBRL machinery, matched on the *prefixed* name. The prefix is load
#: bearing: `ix:hidden` and `ix:header` hold facts the reader never sees, while
#: `ix:nonFraction` and `ix:nonNumeric` wrap numbers that are displayed. Match
#: these on the bare name and every reported figure in the filing disappears.
_DROP_PREFIXED = {
    "ix:header", "ix:hidden", "ix:references", "ix:resources",
    "xbrli:xbrl", "link:schemaref",
}

#: Tags that end a line. Table cells get a space, not a newline, so a row stays
#: one line; rows themselves break.
_BLOCK = {
    "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "thead", "tbody", "section", "article", "hr", "ul", "ol",
}
_CELL = {"td", "th"}

_WS = re.compile(r"[ \t\r\f\v   ]+")
_BLANKS = re.compile(r"\n{3,}")
_SPACED_NL = re.compile(r"[ \t]*\n[ \t]*")


#: Some filings are served as XHTML and open with an XML declaration. lxml
#: refuses a `str` carrying one ("Unicode strings with encoding declaration are
#: not supported"), so it is stripped and the document is handed over as UTF-8
#: bytes with an explicit parser encoding — otherwise lxml would honour a stale
#: in-document charset and mojibake the text.
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)


def _names(tag: object) -> tuple[str, str]:
    """Return ``(prefixed, bare)`` lowercased tag names, or ``("", "")``.

    Comments and processing instructions carry a callable ``.tag``; they are
    reported as empty and dropped.
    """
    if not isinstance(tag, str):
        return "", ""
    prefixed = tag.rsplit("}", 1)[-1].lower()
    return prefixed, prefixed.rsplit(":", 1)[-1]


def _is_hidden(el: object) -> bool:
    """True for elements the browser would not paint."""
    style = (el.get("style") or "").replace(" ", "").lower()  # type: ignore[attr-defined]
    if "display:none" in style or "visibility:hidden" in style:
        return True
    return el.get("hidden") is not None  # type: ignore[attr-defined]


def html_to_text(html: str) -> str:
    """Return the visible text of an EDGAR filing document.

    Raises:
        ValueError: if the document cannot be parsed at all. A filing we cannot
            read is dropped loudly, never turned into an empty string that
            would sail through as a maximally dissimilar document.
    """
    if not html or not html.strip():
        raise ValueError("empty document")

    body = _XML_DECL.sub("", html, count=1)
    parser = lxml_html.HTMLParser(encoding="utf-8", recover=True)
    try:
        root = lxml_html.document_fromstring(
            body.encode("utf-8", "replace"), parser=parser
        )
    except (etree.ParserError, etree.XMLSyntaxError, ValueError) as exc:
        raise ValueError(f"unparseable document: {exc}") from exc

    for el in list(root.iter()):
        prefixed, bare = _names(el.tag)
        if (
            not prefixed
            or prefixed in _DROP_PREFIXED
            or bare in _DROP_BARE
            or _is_hidden(el)
        ):
            parent = el.getparent()
            if parent is not None:
                # Keep the tail: text *after* a hidden element is visible.
                tail = el.tail
                parent.remove(el)
                if tail:
                    prev = parent[-1] if len(parent) else None
                    if prev is not None:
                        prev.tail = (prev.tail or "") + tail
                    else:
                        parent.text = (parent.text or "") + tail

    parts: list[str] = []

    def walk(el) -> None:  # noqa: ANN001
        _, name = _names(el.tag)
        if name in _BLOCK:
            parts.append("\n")
        if el.text:
            parts.append(el.text)
        for child in el:
            walk(child)
            if child.tail:
                parts.append(child.tail)
        if name in _BLOCK:
            parts.append("\n")
        elif name in _CELL:
            parts.append(" ")

    walk(root)

    text = "".join(parts)
    text = _WS.sub(" ", text)
    text = _SPACED_NL.sub("\n", text)
    return _BLANKS.sub("\n\n", text).strip()
