"""Text helpers for sourced documents: HTML to text, sentences, term matching, amounts, dates."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section",
         "article", "header", "footer", "ul", "ol", "title"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    """Visible text with block boundaries kept as newlines. Inline XBRL tags are dropped like any tag."""
    p = _Text()
    try:
        p.feed(raw or "")
        p.close()
    except Exception:  # malformed markup: fall back to tag stripping
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw or "")))
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


_ABBR = re.compile(r"\b(Inc|Corp|Co|Ltd|LLC|No|U\.S|Mr|Ms|Dr|St|vs|e\.g|i\.e|etc)\.$", re.I)


def sentences(text: str, max_sentences: int = 6000) -> list[str]:
    """Split into sentences, keeping lines that look like headings as their own sentence."""
    out: list[str] = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        buf = ""
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", line):
            buf = f"{buf} {piece}".strip() if buf else piece
            if _ABBR.search(buf):
                continue
            out.append(buf)
            buf = ""
        if buf:
            out.append(buf)
        if len(out) >= max_sentences:
            break
    return out[:max_sentences]


def term_re(terms: list[str]) -> re.Pattern | None:
    terms = [t.strip() for t in terms or [] if t and t.strip()]
    if not terms:
        return None
    alts = sorted({re.escape(t.lower()) for t in terms}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")(?![a-z0-9])", re.I)


def hits(pattern: re.Pattern | None, text: str) -> list[str]:
    if pattern is None:
        return []
    return sorted({m.group(0).lower() for m in pattern.finditer(text or "")})


_AMOUNT = re.compile(r"(?:US)?\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(billion|million|thousand|bn|mm|m|b|k)?\b", re.I)


def amount(text: str) -> str | None:
    """The largest stated dollar figure, normalized like "$2.5B" or "$40M"."""
    best, best_v = None, 0.0
    for m in _AMOUNT.finditer(text or ""):
        v = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        mult = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mm": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}.get(unit, 1)
        v *= mult
        if v > best_v:
            best_v = v
            if v >= 1e9:
                best = f"${v / 1e9:g}B"
            elif v >= 1e6:
                best = f"${v / 1e6:g}M"
            else:
                best = f"${v:,.0f}"
    return best if best_v >= 1e5 else None  # small figures are prices or fees, not commitments


def iso_date(value) -> str | None:
    """Date part of anything parseable: ISO strings, RFC 822 (RSS), epoch milliseconds."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        v = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(v, tz=timezone.utc).date().isoformat()
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def truncate(s: str, n: int = 400) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 3].rsplit(" ", 1)[0] + "..."
