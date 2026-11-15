# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata
from collections import Counter

from . import ctx
from .geom import inside

IN_OPS = re.compile(r"\\(arg|max|min|log|ln|lg|exp|sin|cos|tan|sinh|cosh|tanh|cot|sec|csc|arcsin|arccos|arctan|lim|liminf|limsup|sup|inf|det|dim|ker|deg|gcd|hom|Pr|mod|bmod|pmod)(?![A-Za-z])")
GREEK_NAMES = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega".split()
TEX_GREEK = re.compile(r"\\(?:var)?(" + "|".join(GREEK_NAMES) + r")(?![A-Za-z])", re.I)


def greek(ch):
    for x in unicodedata.normalize("NFKC", ch):
        n = "GREEK DELTA" if x == "∆" else unicodedata.name(x, "")
        if n.startswith("GREEK"):
            for w in n.lower().replace("lamda", "lambda").split()[1:]:
                if w in GREEK_NAMES:
                    return w


def in_letters(t):
    t = IN_OPS.sub(r" \1 ", re.sub(r"\\ell(?![A-Za-z])", "l", t))
    return re.sub(r"\\(?:[A-Za-z]+|.?)", "", t)


TEX_ACC = re.compile(r"\\(tilde|hat|bar|dot|ddot|check|breve|acute|grave|widetilde|widehat|overline)(?![A-Za-z])")
PDF_ACC = {"˜": "tilde", "~": "tilde", "\u0303": "tilde", "ˆ": "hat", "^": "hat", "\u0302": "hat", "¯": "bar", "ˉ": "bar", "\u0304": "bar",
           "˙": "dot", "\u0307": "dot", "¨": "ddot", "\u0308": "ddot", "ˇ": "check", "˘": "breve", "´": "acute", "`": "grave"}
WIDE_ACC = {"widetilde": "tilde", "widehat": "hat", "overline": "bar"}
TEX_BOLD = re.compile(r"\\(mathbf|boldsymbol|bm|pmb|textbf|mathbfit|bf)(?![A-Za-z])\s*")
SYM_RE = {"minus": r"-", "eq": r"=", "plus": r"\+", "cdot": r"\\(?:cdot|cdotp|centerdot)(?![A-Za-z])"}
PDF_SYM = {"minus": "-−‐–", "eq": "=", "plus": "+", "cdot": "·⋅"}
LOOSE_SYM = {"neq": ("eq", 1), "ne": ("eq", 1), "coloneqq": ("eq", 1), "eqqcolon": ("eq", 1), "triangleq": ("eq", 1), "doteq": ("eq", 1), "models": ("eq", 1),
             "Longrightarrow": ("eq", 1), "Longleftarrow": ("eq", 1), "Longleftrightarrow": ("eq", 1), "iff": ("eq", 1), "Relbar": ("eq", 1),
             "longrightarrow": ("minus", 1), "longleftarrow": ("minus", 1), "longleftrightarrow": ("minus", 1), "longmapsto": ("minus", 1), "relbar": ("minus", 1),
             "xrightarrow": ("minus", 9), "xleftarrow": ("minus", 9), "overrightarrow": ("minus", 9), "overleftarrow": ("minus", 9), "cdots": ("cdot", 3), "dots": ("cdot", 3)}
TEX_SKIP = re.compile(r"\\(?:[hv]space\*?\s*\{[^}]*\}|m?kern\s*-?[\d.]+\s*[a-z]{2}|mskip\s*-?[\d.]+\s*mu)|\\\\\s*\[[^\]]*\]")
SCRIPT_ARG = set("mathbf mathrm mathit mathcal mathbb mathsf mathtt mathfrak mathscr boldsymbol bm pmb tilde hat bar vec dot ddot check breve acute grave widetilde widehat "
                 "overline underline text textrm textbf textit textsf texttt mbox operatorname sqrt overrightarrow overleftarrow underbrace overbrace".split())
SCRIPT_FRAC = set("frac dfrac tfrac cfrac binom dbinom tbinom".split())
SCRIPT_STACK = set("overset underset stackrel".split())
SCRIPT_DELIM = set("left right middle big Big bigg Bigg bigl bigr Bigl Bigr biggl biggr Biggl Biggr".split())


def tex_depth(latex):
    toks, out = re.findall(r"\\[A-Za-z]+|\\.|\S", latex), Counter()

    def item(k, d):
        return atom(k + 1, min(d + 1, 2)) if toks[k] in ("_", "^") else atom(k, d)

    def atom(k, d):
        if k >= len(toks):
            return k
        t = toks[k]
        k += 1
        if t == "{":
            while k < len(toks) and toks[k] != "}":
                k = item(k, d)
            return k + 1
        if t[:1] == "\\" and t[1:].isalpha():
            n = t[1:]
            if toks[k:k + 1] == ["*"]:
                k += 1
            if n in SCRIPT_FRAC:
                return atom(atom(k, d and 2), d and 2)
            if n in SCRIPT_STACK:
                return atom(atom(k, min(d + 1, 2)), d)
            if n in SCRIPT_ARG:
                if n == "sqrt" and toks[k:k + 1] == ["["]:
                    k = toks.index("]", k) + 1 if "]" in toks[k:] else len(toks)
                return atom(k, d)
            if n in SCRIPT_DELIM:
                return k + 1 if k < len(toks) and toks[k] not in ("\\left", "\\right") else k
            g = TEX_GREEK.fullmatch(t)
            if g:
                out[(g.group(1).lower(), d)] += 1
            elif IN_OPS.fullmatch(t):
                out.update((c, d) for c in n)
            elif n == "ell":
                out[("l", d)] += 1
            return k
        x = greek(t) or (t if t.isascii() and t.isalpha() else None)
        if x:
            out[(x, d)] += 1
        return k

    k = 0
    while k < len(toks):
        k = item(k, 0)
    return out


def bold_spans(latex):
    out = []
    for m in TEX_BOLD.finditer(latex):
        j = e = m.end()
        if m.group(1) == "bf":
            d, e = 0, len(latex)
            for k in range(j, len(latex)):
                d += {"{": 1, "}": -1}.get(latex[k], 0)
                if d < 0:
                    e = k
                    break
        elif latex[j:j + 1] == "{":
            e = group_end(latex, j)
        else:
            e = j + re.match(r"\\[A-Za-z]+|\S?", latex[j:]).end()
        out.append((m.start(), j, e))
    return out


def bold_letters(latex):
    c, end = Counter(), 0
    for s, j, e in bold_spans(latex):
        if j >= end:
            c.update(x for x in in_letters(latex[j:e]) if x.isascii() and x.isalpha())
            end = e
    return c


def tex_eval(chars, tr, latex):
    keep = [(ch, z, bd) for box, ch, font, z, bd in chars if inside(box, tr) and not font.upper().startswith("CMEX") and font not in ctx.SYM_FONTS]
    ascii_letters = lambda t: Counter(x for ch in t for x in unicodedata.normalize("NFKC", ch) if x.isascii() and x.isalpha())
    have = ascii_letters(ch for ch, _, _ in keep)
    if not have:
        return None
    tag = Counter(c for t in re.findall(r"\\tag\s*\{([^}]*)\}", latex) for c in t if c.isascii() and c.isalpha())
    body = re.sub(r"\\(?:tag|begin|end)\s*\{[^}]*\}", "", re.sub(r"\\begin\s*\{array\}\s*\{[^}]*\}", "", latex))
    want = ascii_letters(in_letters(body))
    want = min((want, want + tag), key=lambda w: sum(((w - have) + (have - w)).values()))
    r = {"letters": (want, have),
         "greek": (Counter([m.lower() for m in TEX_GREEK.findall(body)] + [g for ch in in_letters(body) if (g := greek(ch))]), Counter(g for ch, _, _ in keep if (g := greek(ch))))}
    found = TEX_ACC.findall(body)
    aw, wide = Counter(a for a in found if a not in WIDE_ACC), Counter(WIDE_ACC[a] for a in found if a in WIDE_ACC)
    ah = Counter(PDF_ACC[ch] for ch, _, _ in keep if ch in PDF_ACC)
    r["accent"] = all(aw[a] <= ah[a] <= aw[a] + wide[a] for a in set(aw) | set(ah) | set(wide))
    lets = [(x, z) for ch, z, _ in keep for x in ([greek(ch)] if greek(ch) else [y for y in unicodedata.normalize("NFKC", ch) if y.isascii() and y.isalpha()])]
    big = max((z for _, z in lets), default=0)
    small = Counter(x for x, z in lets if z <= 0.6 * big)
    r["depth"] = not small or small == Counter({x: c for (x, d), c in tex_depth(body).items() if d == 2})
    r["bold"] = (bold_letters(body), Counter(y for ch, _, bd in keep for y in unicodedata.normalize("NFKC", ch) if y.isascii() and y.isalpha()
                                              and (bd or unicodedata.name(ch, "").startswith(("MATHEMATICAL BOLD", "MATHEMATICAL SANS-SERIF BOLD")))))
    flat = TEX_SKIP.sub("", body)
    sw, loose = Counter({k: len(re.findall(v, flat)) for k, v in SYM_RE.items()}), Counter()
    for n in re.findall(r"\\([A-Za-z]+)", flat):
        if n in LOOSE_SYM:
            loose[LOOSE_SYM[n][0]] += LOOSE_SYM[n][1]
    sh = Counter({k: sum(ch in v for ch, _, _ in keep) for k, v in PDF_SYM.items()})
    r["sym"] = all(sw[k] <= sh[k] <= sw[k] + loose[k] for k in PDF_SYM)
    return r


def tex_ok(chars, tr, latex):
    r = tex_eval(chars, tr, latex)
    return r is None or all(v[0] == v[1] if isinstance(v, tuple) else v for v in r.values())


def outer_bars(latex):
    m = re.match(r"\s*\\left\s*(\||\\\|)(.*)\\right\s*\1\s*((?:\\tag\s*\{[^}]*\}\s*)?)$", latex, re.S)
    if not m:
        return latex
    top = m.group(2)
    while re.search(r"\{[^{}]*\}|\([^()]*\)|\[[^\[\]]*\]", top):
        top = re.sub(r"\{[^{}]*\}|\([^()]*\)|\[[^\[\]]*\]", "", top)
    return m.group(2).strip() + m.group(3) if "=" in top else latex


CONFUSABLE = (("nu", "v"), ("I", "l"), ("l", "I"), ("kappa", "k"), ("k", "kappa"), ("rho", "p"), ("p", "rho"),
              ("chi", "x"), ("x", "chi"), ("upsilon", "u"), ("u", "upsilon"))


def tex_fix(chars, tr, latex):
    latex = outer_bars(latex)
    if tex_eval(chars, tr, latex) is None:
        return latex
    for a, b in CONFUSABLE:
        r = tex_eval(chars, tr, latex)
        (lw, lh), (gw, gh) = r["letters"], r["greek"]
        src = "\\" + a if len(a) > 1 else a
        n = sum(t == src for t in re.findall(r"\\[A-Za-z]+|[A-Za-z]", latex))
        extra = (gw - gh)[a] if len(a) > 1 else (lw - lh)[a]
        lack = (gh - gw)[b] if len(b) > 1 else (lh - lw)[b]
        if n and extra == lack == n:
            dst = "\\" + b + " " if len(b) > 1 else b
            latex = re.sub(r"\\[A-Za-z]+|[A-Za-z]", lambda m: dst if m.group() == src else m.group(), latex)
    bw, bh = tex_eval(chars, tr, latex)["bold"]
    extra = bw - bh
    if extra and not bh - bw:
        for s, j, e in reversed(bold_spans(latex)):
            got = Counter(x for x in in_letters(latex[j:e]) if x.isascii() and x.isalpha())
            if got and not got - extra:
                extra -= got
                latex = latex[:s] + latex[j:]
    return latex


def page_chars(pg):
    return [(c["bbox"], c["c"], s["font"], s["size"], bool(s["flags"] & 16)) for b in pg.get_text("rawdict")["blocks"] if b["type"] == 0
            for l in b["lines"] for s in l["spans"] for c in s["chars"]]


def tex_rect(e, pg):
    return (e["bbox"][0] * pg.rect.width, e["bbox"][1] * pg.rect.height, e["bbox"][2] * pg.rect.width, e["bbox"][3] * pg.rect.height)


def group_end(s, i):
    d = 0
    for j in range(i, len(s)):
        d += {"{": 1, "}": -1}.get(s[j], 0)
        if not d:
            return j + 1
    return len(s)
