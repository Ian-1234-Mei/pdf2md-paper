# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata

from . import ctx

BOLD_RE = re.compile(r"Bold|bold|Medi|Demi|Black|Heavy|^CMB|^SFB|Bd(?![a-z])")
CAP_RE = re.compile(r"^((?:Fig|FIG)\.?\s*(?:[A-Z]\.)?\d+|(?:Figure|FIGURE)\s+(?:[A-Z]\.)?\d+|(?:TABLE|Table)\s+(?:[A-Z]\.\d+|[IVXLC]+|\d+))")
MATH_RE = re.compile(r"^(?:MSAM|MSBM|STIX|KaTeX_|Cambria ?Math|LMMath|XITS)", re.I)
EQNO_RE = re.compile(r"^\(\d{1,2}\)$")


def norm(s):
    s = "".join(c for c in s if unicodedata.category(c) not in ("Cc", "Cf"))
    s = "".join(unicodedata.normalize("NFKC", c) if unicodedata.decomposition(c).startswith("<font>") or "\ufb00" <= c <= "\ufb06" else c for c in s)
    return re.sub(r"\s+", " ", s).strip()


def key(s):
    return re.sub(r"[\W\d_]+", "", s).lower()


def caption_label(text):
    m = CAP_RE.match(text)
    if not m:
        return None
    rest = text[m.end():]
    if rest[:1] in ("", ".", ":", "|") or (rest[:1].isspace() and not rest.lstrip()[:1].islower()):
        return m.group(1)
    return None


def is_upper(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def is_bold(spans):
    ink = [(len(s["text"].strip()), bool(BOLD_RE.search(s["font"]) or s["flags"] & 16)) for s in spans if s["text"].strip()]
    total = sum(n for n, _ in ink)
    return total > 0 and ink[0][1] and sum(n for n, b in ink if b) >= 0.8 * total


def join(a, b):
    m = re.match(r"[A-Za-z]+", b)
    if a.endswith("-") and m:
        stem = re.search(r"[A-Za-z]+$", a[:-1])
        if b[:1].islower() and not (stem and ctx.VOCAB[stem.group(0).lower()] and ctx.VOCAB[m.group(0).lower()]):
            return a[:-1] + b
        return a + b
    if a.endswith("/") or b.startswith("//") or a.endswith(("$", ")", "]", "</sub>", "</sup>")) and b[:1] in ",.;:)":
        return a + b
    return a + " " + b


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def is_math(font):
    return bool(MATH_RE.match(font)) or font.upper().startswith(("CMMI", "CMSY", "CMEX")) or (font.upper().startswith("CM") and not ctx.CM_BODY) or font in ctx.MATH_FONTS


def is_katex(font):
    return font.startswith("KaTeX_")


def span_info(s):
    text = s["text"]
    math = is_math(s["font"])
    return {"rect": tuple(s["bbox"]), "text": text, "math": math, "blank": not text.strip(), "katex": is_katex(s["font"]),
            "eqno": not math and bool(EQNO_RE.match(text.strip())), "prose": not math and bool(re.search(r"[A-Za-z]{3,}", text)) and s["size"] >= ctx.BODY - 1.5}
