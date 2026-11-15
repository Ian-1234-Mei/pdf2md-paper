# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

import pymupdf

NOREF = "--ref-wo" in sys.argv
NOTAB = "--tab-wo" in sys.argv
NOEQ = "--eq-wo" in sys.argv
sys.argv = [a for a in sys.argv if a not in ("--ref-wo", "--tab-wo", "--eq-wo")]
src, md_path, figdir = sys.argv[1:4]
KEEP = sys.argv[4] if len(sys.argv) > 4 else None
HERE = os.path.dirname(os.path.abspath(__file__))
TIER = "basic"
RETRY_TIER = "standard"
GPU_PY = os.path.join(HERE, "venv-mineru-gpu", "bin", "python")
doc = pymupdf.open(src)
total = len(doc)
MARGIN = 4
DPI = 300
TEXT_PX, DPI_MIN = 14, 200
HEAD2_RE = re.compile(r"^(?:[IVX]+\.\s+)?[A-Z][A-Z ,\-]*[A-Z]$")
HEAD3_RE = re.compile(r"^[A-Z]\.\s+\S")
NUM_RE = re.compile(r"^(?:\d{1,2}|[A-Z])(?:\.\d{1,2})?$")
HEADN_RE = re.compile(r"^(?:\d{1,2}|[A-Z](?=\.\d))(?:\.\d{1,2}){0,2}\.?\s+[A-Z]")
BOLD_RE = re.compile(r"Bold|bold|Medi|Demi|Black|Heavy|^CMB|^SFB|Bd(?![a-z])")
GAP_UP, GAP_DOWN, GAP_TABLE, GAP_EQ = 5, 20, 15, 2.5
CAP_RE = re.compile(r"^((?:Fig|FIG)\.?\s*(?:[A-Z]\.)?\d+|(?:Figure|FIGURE)\s+(?:[A-Z]\.)?\d+|(?:TABLE|Table)\s+(?:[A-Z]\.\d+|[IVXLC]+|\d+))")
ALGO_RE = re.compile(r"^(algorithm\s*(?:[A-Z]\.)?\d+)", re.I)
LINENO_RE = re.compile(r"^(\d+:)\s*")
ATOM_RE = re.compile(r"(?:((?<![A-Za-z])[A-Za-z]|[\u0370-\u03ff]|[∑∏]|\d+)?(′*)((?:<su[bp]>.*?</su[bp]>)+))+")
TERM_RE = re.compile(r"[.!?:;][\"”’)\]]*$")
REF_RE = re.compile(r"^\[\d+\]")
BIB_RE = re.compile(r"#+ (?:[\dIVX]+\.?\s*)?(?:references?|bibliography|參考文獻|參考資料)\s*", re.I)
BULLET_RE = re.compile(r"^(?:[•●○■▪◦]\s*|-\s+)")
MATH_RE = re.compile(r"^(?:MSAM|MSBM|STIX|KaTeX_|Cambria ?Math|LMMath|XITS)", re.I)
OPS = "=≈≠∈≤≥→←↔∝−∑∏∫⊗⊕⇒≜"
PAGE_NUM_RE = re.compile(r"^[\d\s/.\-:]*\d[\d\s/.\-:]*$")
DASH_RE = re.compile(r"^[-–—]+$")
EQNO_RE = re.compile(r"^\(\d{1,2}\)$")
NUM_TOK = re.compile(r"^[(+\-−±]*\d*[.,]?\d+(?:e[+\-−]?\d+)?%?\)?$")
saved = Counter()
tab_end = {}


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


def union(rs):
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def xov(a, b):
    return a[0] < b[2] and a[2] > b[0]


def cx(r):
    return (r[0] + r[2]) / 2


def cy(r):
    return (r[1] + r[3]) / 2


def near(a, b, gap, gy=None):
    gy = gap if gy is None else gy
    return a[0] <= b[2] + gap and b[0] <= a[2] + gap and a[1] <= b[3] + gy and b[1] <= a[3] + gy


def vov(a, b):
    return min(a[3], b[3]) - max(a[1], b[1])


def join(a, b):
    m = re.match(r"[A-Za-z]+", b)
    if a.endswith("-") and m:
        stem = re.search(r"[A-Za-z]+$", a[:-1])
        if b[:1].islower() and not (stem and VOCAB[stem.group(0).lower()] and VOCAB[m.group(0).lower()]):
            return a[:-1] + b
        return a + b
    if a.endswith("/") or b.startswith("//") or a.endswith(("$", ")", "]", "</sub>", "</sup>")) and b[:1] in ",.;:)":
        return a + b
    return a + " " + b


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def pad(r):
    return (r[0] - MARGIN, r[1] - MARGIN, r[2] + MARGIN, r[3] + MARGIN)


def cluster(items, gap, gy=None):
    groups = []
    for k, r in items:
        members, rect, keep = [k], r, []
        for gm, gr in groups:
            if near(gr, rect, gap, gy):
                members, rect = members + gm, union([rect, gr])
            else:
                keep.append((gm, gr))
        groups = keep + [(members, rect)]
    return groups


def is_math(font):
    return bool(MATH_RE.match(font)) or font.upper().startswith(("CMMI", "CMSY", "CMEX")) or (font.upper().startswith("CM") and not CM_BODY) or font in MATH_FONTS


def is_katex(font):
    return font.startswith("KaTeX_")


def span_info(s):
    text = s["text"]
    math = is_math(s["font"])
    return {"rect": tuple(s["bbox"]), "text": text, "math": math, "blank": not text.strip(), "katex": is_katex(s["font"]),
            "eqno": not math and bool(EQNO_RE.match(text.strip())), "prose": not math and bool(re.search(r"[A-Za-z]{3,}", text)) and s["size"] >= BODY - 1.5}


def inside(r, z):
    return z[0] - 2 <= (r[0] + r[2]) / 2 <= z[2] + 2 and z[1] - 2 <= cy(r) <= z[3] + 2


def same_row(a, b, gap=25):
    ov = vov(a, b)
    return ov >= 0.5 * min(a[3] - a[1], b[3] - b[1]) and max(a[0], b[0]) - min(a[2], b[2]) <= gap


def spaced(rows, top, bottom=None):
    up = [q[3] for q in rows if q[3] <= top[1] + 1 and xov(q, top)]
    down = [q[1] for q in rows if bottom and q[1] >= bottom[3] - 1 and xov(q, bottom)]
    return (not up or top[1] - max(up) >= GAP_UP) and (not down or min(down) - bottom[3] <= GAP_DOWN)


def alone(rows, r):
    return not any(q != r and same_row(q, r) for q in rows)


def follow(free, l, used):
    tail = []
    while l["bold"]:
        nxt = [(m, mi, t) for m, mi, t in free if (m, mi) not in used and t["bold"] and abs(t["size"] - l["size"]) <= 0.3
               and -1 <= t["rect"][1] - l["rect"][3] <= 3 and xov(t["rect"], l["rect"])]
        if not nxt:
            break
        m, mi, l = min(nxt, key=lambda x: x[2]["rect"][1])
        used.add((m, mi))
        tail.append(l["text"])
    return tail


def isolated(blocks, talk, rect):
    tl = [l["rect"] for k, b in enumerate(blocks) for li, l in enumerate(b["lines"]) if (k, li) in talk and xov(l["rect"], rect)]
    if any(vov(r, rect) > 0.5 * min(r[3] - r[1], rect[3] - rect[1]) for r in tl):
        return False
    up = [r[3] for r in tl if r[3] <= rect[1] + 1]
    dn = [r[1] for r in tl if r[1] >= rect[3] - 1]
    return (not up or rect[1] - max(up) >= GAP_EQ) and (not dn or min(dn) - rect[3] >= GAP_EQ)


def equations(blocks, zones, blocked):
    ink = [((k, li, si), s) for k, b in enumerate(blocks) if k not in blocked and not b["img"] and not b["rot"]
           for li, l in enumerate(b["lines"]) for si, s in enumerate(l["spans"])
           if not s["blank"] and not any(inside(s["rect"], z) for z in zones)]
    spans = dict(ink)
    talk = set()
    for k, b in enumerate(blocks):
        for li, l in enumerate(b["lines"]):
            n = sum(len(s["text"].strip()) for s in l["spans"])
            if n and sum(len(s["text"].strip()) for s in l["spans"] if s["prose"]) >= 0.5 * n:
                talk.add((k, li))
    talk_rects = {(k, li): blocks[k]["lines"][li]["rect"] for k, li in talk}
    groups = cluster([(i, s["rect"]) for i, s in ink if s["math"] and i[:2] not in talk], 12, 6)
    prose = [s["rect"] for i, s in ink if s["prose"] and i[:2] in talk]
    merged = []
    for mem, rect in groups:
        for j, (gm, gr) in enumerate(merged):
            if same_row(gr, rect) and not any(inside(p, union([rect, gr])) for p in prose):
                merged[j] = (mem + gm, union([rect, gr]))
                break
        else:
            merged.append((mem, rect))
    out = []
    for mem, rect in merged:
        if len(mem) < 2 or any(s["prose"] and i[:2] in talk and same_row(s["rect"], rect, 8) for i, s in ink):
            continue
        label, tag = None, []
        for _, s in ink:
            if s["eqno"] and rect[1] - 3 <= cy(s["rect"]) <= rect[3] + 3 and 0 <= s["rect"][0] - rect[2] <= 150:
                rect, label, tag = union([rect, s["rect"]]), s["text"].strip(), [s["rect"]]
        if not any(c.isalpha() for i in mem for c in spans[i]["text"]) or (not label and not any(c in OPS for i in mem for c in spans[i]["text"])):
            continue
        if not label and not isolated(blocks, talk, rect):
            continue
        mem_in = [i for i in mem if not any(same_row(blocks[i[0]]["lines"][i[1]]["rect"], t, 8) for q, t in talk_rects.items() if q != i[:2])]
        if mem_in and len(mem_in) < len(mem):
            rect = union([spans[i]["rect"] for i in mem_in] + tag)
        lines = sorted({(k, li) for k, b in enumerate(blocks) if k not in blocked and not b["img"] and not b["rot"]
                        for li, l in enumerate(b["lines"])
                        if (k, li) not in talk and any(not s["blank"] for s in l["spans"]) and all(inside(s["rect"], rect) for s in l["spans"] if not s["blank"])})
        out.append({"rect": rect, "label": label, "lines": lines})
    return out


def merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a < out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def algo_box(blocks, drawings, skip):
    rules = [d for d in drawings if d[3] - d[1] <= 2 and d[2] - d[0] >= 50]
    found = {}
    for k, b in enumerate(blocks):
        if b["img"] or k in skip:
            continue
        m = ALGO_RE.match(b["lines"][0]["text"])
        t = b["lines"][0]["rect"]
        top = [d for d in rules if t[1] - 4 <= cy(d) <= t[1] + 1 and d[0] <= t[0] + 2 and d[2] >= t[2] - 2]
        if not m or not top:
            continue
        td = max(top, key=lambda d: d[1])
        below = sorted([d for d in rules if cy(d) > t[3] - 1 and abs(d[0] - td[0]) <= 2 and abs(d[2] - td[2]) <= 2], key=lambda d: d[1])
        if len(below) < 2 or cy(below[0]) - cy(td) > 40:
            continue
        box = (td[0], td[1], td[2], below[1][3])
        ks = [j for j, o in enumerate(blocks) if j not in skip and inside(o["rect"], box)]
        mid = cy(below[0])
        title = ""
        for l in [l for j in ks for l in blocks[j]["lines"] if cy(l["rect"]) < mid]:
            title = join(title, l["text"]) if title else l["text"]
        body = [l for j in ks if not blocks[j]["img"] for l in blocks[j]["lines"] if cy(l["rect"]) > mid]
        dks = {dk for dk, d in enumerate(drawings) if inside(d, box)}
        found[k] = {"label": m.group(1), "title": title, "box": box, "ks": ks, "dks": dks, "code": algo_code(body)}
    return found


TEX_SYM = {"∑": "\\sum ", "∏": "\\prod ", "−": "-", "′": "'", "∗": "*", "·": "\\cdot ", "∼": "\\sim ", "∈": "\\in ", "←": "\\leftarrow ", "×": "\\times ", "ϵ": "\\epsilon ", "ε": "\\varepsilon ", "ϕ": "\\phi ", "φ": "\\varphi ", "ϑ": "\\vartheta "}
TEX_UP = {"Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega"}


def tex_chr(c):
    if c in TEX_SYM:
        return TEX_SYM[c]
    m = re.fullmatch(r"GREEK (SMALL|CAPITAL) LETTER ([A-Z]+)", unicodedata.name(c, "").replace("LAMDA", "LAMBDA"))
    if m and m.group(1) == "SMALL":
        return "\\" + m.group(2).lower() + " "
    if m and m.group(2).capitalize() in TEX_UP:
        return "\\" + m.group(2).capitalize() + " "
    return c


def algo_tex(s):
    def group(body):
        if " " in body.strip() or re.fullmatch(r"[A-Za-z]{3,}", body):
            return "{\\mathrm{" + body.strip().replace(" ", "\\ ") + "}}"
        return "{" + "".join(tex_chr(c) for c in body).strip() + "}"

    def atom(m):
        out = ""
        for b, pr, tags in re.findall(r"((?<![A-Za-z])[A-Za-z]|[\u0370-\u03ff]|[∑∏]|\d+)?(′*)((?:<su[bp]>.*?</su[bp]>)+)", m.group(0)):
            out += ("{}" if out and not b else "".join(tex_chr(c) for c in b).strip()) + "'" * len(pr)
            seen = set()
            for k, x in re.findall(r"<(su[bp])>(.*?)</\1>", tags):
                out += ("{}" if k in seen else "") + ("_" if k == "sub" else "^") + group(x)
                seen = {k} if k in seen else seen | {k}
        return "$" + out + "$"

    def pad(m):
        a, b = m.start(), m.end()
        return (" " if a and m.string[a - 1].isalnum() and m.group(0)[1] not in "_^" else "") + m.group(0) + (" " if m.string[b:b + 1].isalnum() else "")
    return re.sub(r"\$[^$\n]+\$", pad, ATOM_RE.sub(atom, s).replace("$$", "$ $"))


def algo_code(lines):
    if not lines:
        return ""
    cnt = Counter()
    for l in lines:
        cnt[l["size"]] += len(l["text"])
    main = cnt.most_common(1)[0][0]
    prime = [l for l in lines if l["size"] >= main - 1.5 or LINENO_RE.match(l["text"])]
    rows = []
    for l in sorted(prime, key=lambda l: cy(l["rect"])):
        if rows and cy(l["rect"]) - cy(rows[-1][0]["rect"]) <= 0.5 * main:
            rows[-1].append(l)
        else:
            rows.append([l])
    for l in lines:
        if not any(l is p for p in prime):
            min(rows, key=lambda r: abs(cy(r[0]["rect"]) - cy(l["rect"]))).append(l)
    out = []
    for r in rows:
        r.sort(key=lambda l: l["rect"][0])
        texts = [l["md"] if l["md"] is not None else l["text"] for l in r]
        m = LINENO_RE.match(r[0]["text"])
        x = r[0]["rect"][0]
        if m:
            texts[0] = LINENO_RE.sub("", texts[0], count=1)
            sp = [s for s in r[0]["spans"] if not s["blank"]]
            if sp and LINENO_RE.fullmatch(sp[0]["text"].strip()):
                nxt = sp[1:] or [s for l in r[1:] for s in l["spans"] if not s["blank"]][:1]
                x = nxt[0]["rect"][0] if nxt else None
            elif sp:
                s = sp[0]
                x = s["rect"][0] + (s["rect"][2] - s["rect"][0]) * len(m.group(0)) / max(len(s["text"].lstrip()), 1)
        text = texts[0]
        for p, q, t in zip(r, r[1:], texts[1:]):
            text = text + ("" if q["rect"][0] - p["rect"][2] < 1 else " ") + t
        out.append([m.group(1) if m else None, x, text.strip()])
    numbered = [o for o in out if o[0]]
    if numbered:
        base = min([o[1] for o in numbered if o[1] is not None], default=0)
        merged = []
        for o in out:
            p = merged[-1] if merged else None
            if not o[0] and p and p[1] is not None and (o[1] >= base - 1 if p[0] else o[1] > p[1] + 3):
                p[2] = join(p[2], o[2])
            else:
                merged.append(o)
        out = merged
    xs = sorted(o[1] for o in out if (o[0] or not numbered) and o[1] is not None)
    levels = []
    for x in xs:
        if not levels or x - levels[-1] > 3:
            levels.append(x)
    lines, prev = [], -1
    for num, x, text in out:
        lv = min(sum(1 for v in levels[1:] if x >= v - 3) if (num or not numbered) and x is not None else 0, prev + 1)
        prev = lv
        lines.append(("  " * lv + "- " + (num + " " if num else "") + algo_tex(text)).rstrip())
    return "\n".join(lines)


def table_md(pg, rect, drawings):
    rot = [(tuple(l["bbox"]), norm("".join(s["text"] for s in l["spans"])))
           for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) if tuple(l["dir"]) != (1, 0) and inside(l["bbox"], rect)]
    ws = [(w[0], w[1], w[2], w[3], norm(w[4])) for w in pg.get_text("words") if inside(w[:4], rect) and not any(inside(w[:4], r) for r, _ in rot)]
    ws = sorted((w for w in ws + [r + (t,) for r, t in rot] if w[4]), key=lambda w: (cy(w), w[0]))
    if len(ws) < 2:
        return None
    mk = {}
    rl = [l for b in pg.get_text("rawdict")["blocks"] for l in b.get("lines", []) if tuple(l["dir"]) == (1, 0) and inside(l["bbox"], rect)]
    txt = lambda l: [dict(s, text="".join(c["c"] for c in s["chars"])) for s in l["spans"]]
    for l in rl:
        z = max(s["size"] for s in l["spans"])
        ref = [s for o in rl if o is not l and xov(o["bbox"], l["bbox"]) and vov(o["bbox"], l["bbox"]) > 0
               and max(s["size"] for s in o["spans"]) >= 1.2 * z for s in txt(o)]
        kinds = scripts(txt(l), ref)
        cs = [c for s in l["spans"] for c in s["chars"]]
        if not any(kinds) or len(cs) != len(kinds):
            continue
        for w in ws:
            sel = [(c["c"], k) for c, k in zip(cs, kinds) if not c["c"].isspace() and w[0] - 0.5 <= cx(c["bbox"]) <= w[2] + 0.5 and w[1] - 0.5 <= cy(c["bbox"]) <= w[3] + 0.5]
            if not sel or norm("".join(c for c, _ in sel)) != w[4]:
                continue
            text, i = "", 0
            while i < len(sel):
                j = i
                while j < len(sel) and sel[j][1] == sel[i][1]:
                    j += 1
                seg, k = norm("".join(c for c, _ in sel[i:j])), sel[i][1]
                text += f"<{k}>{seg}</{k}>" if k and any(c.isalnum() for c in seg) else seg
                i = j
            if text != w[4]:
                mk[w[:4]] = text
    h = sorted(w[3] - w[1] for w in ws)[len(ws) // 2]
    hr = []
    for d in sorted((d for d in drawings if d[3] - d[1] <= 2 and xov(d, rect) and rect[1] - 2 <= cy(d) <= rect[3] + 2), key=lambda d: (round(cy(d)), d[0])):
        if hr and abs(cy(hr[-1]) - cy(d)) <= 1 and d[0] <= hr[-1][2] + 2:
            hr[-1] = union([hr[-1], d])
        else:
            hr.append(d)
    hr = [d for d in hr if d[2] - d[0] >= 20]
    vr = [d for d in drawings if d[2] - d[0] <= 2 and d[3] - d[1] >= h and inside(d, rect)]
    xs = merge([(w[0], w[2]) for w in ws] + [(d[0], d[2]) for d in hr])
    cuts = [(a[1] + b[0]) / 2 for a, b in zip(xs, xs[1:])
            if b[0] - a[1] >= 0.5 * h and any(d[2] <= b[0] for d in hr) and any(d[0] >= a[1] for d in hr)]
    if cuts:
        xs = [rect[0]] + cuts + [rect[2]]
        parts = [table_md(pg, (a, rect[1], b, rect[3]), drawings) for a, b in zip(xs, xs[1:])]
        return "\n\n".join(p for p in parts if p) or None

    def mid_y(r):
        core = [cy(v) for v in r if v[3] - v[1] <= 1.3 * h] or [cy(v) for v in r]
        return sum(core) / len(core)

    rows = []
    for w in ws:
        if rows and (abs(cy(w) - mid_y(rows[-1])) <= 0.3 * h or (w[3] - w[1] > 1.3 * h and w[1] <= mid_y(rows[-1]) <= w[3])):
            rows[-1].append(w)
        else:
            rows.append([w])
    if len(rows) < 2:
        return None

    def cells_of(r, split_nums):
        cells = [[r[0][0], r[0][2], r[0][4], r[0][3], [r[0]]]]
        for w in r[1:]:
            c = cells[-1]
            if w[0] - c[1] > 0.5 * h or any(c[1] - 1 <= cx(d) <= w[0] + 1 and d[1] <= cy(w) <= d[3] for d in vr) or (split_nums and NUM_TOK.match(c[2].split()[-1]) and NUM_TOK.match(w[4]) and not w[4].startswith("(")):
                cells.append([w[0], w[2], w[4], w[3], [w]])
            else:
                c[1], c[2], c[3] = max(c[1], w[2]), c[2] + " " + w[4], max(c[3], w[3])
                c[4].append(w)
        return cells

    for r in rows:
        r.sort(key=lambda w: w[0])
    table = [(mid_y(r), cells_of(r, False)) for r in rows]
    if any(sum(bool(NUM_TOK.match(t)) for t in c[2].split()) >= 3 for _, cells in table for c in cells):
        table = [(mid_y(r), cells_of(r, True)) for r in rows]
    full = sorted(cy(d) for d in hr if d[2] - d[0] >= 0.9 * (rect[2] - rect[0]))
    mid = next((y for y in full if y > table[0][0]), None)
    nh = sum(y < mid for y, _ in table) if mid else 1
    if nh >= len(table):
        nh = 1
    most = max(len(c) for _, c in table[nh:])
    if most < 2:
        return None
    cols = merge([(c[0], c[1]) for _, cells in table[nh:] if len(cells) == most for c in cells])
    cols = sorted(cols + merge([(c[0], c[1]) for _, cells in table[nh:] for c in cells if not any(c[0] < b and c[1] > a for a, b in cols)]))

    def base(x0, x1):
        ov = [max(0, min(x1, b) - max(x0, a)) for a, b in cols]
        if not max(ov):
            return min(range(len(cols)), key=lambda i: abs(cols[i][0] + cols[i][1] - x0 - x1))
        covered = [i for i, (a, b) in enumerate(cols) if ov[i] >= 0.6 * (b - a)]
        return covered[0] if len(covered) > 1 else ov.index(max(ov))

    occ = [{base(c[0], c[1]) for c in cells} for _, cells in table[:nh]]
    grid = []
    for n, (y, cells) in enumerate(table):
        row = [""] * len(cols)
        for x0, x1, t, y1, cw in cells:
            hit = [base(x0, x1)]
            k = len(cw)
            if n >= nh and len(cells) > 1 and x0 == cells[0][0]:
                k = next((j for j, w in enumerate(cw) if base(w[0], w[2]) != base(cw[0][0], cw[0][2])), k)
            if k < len(cw):
                for part in (cw[:k], cw[k:]):
                    i = base(part[0][0], part[-1][2])
                    row[i] = (row[i] + " " + " ".join(mk.get(w[:4], w[4]) for w in part).replace("|", "\\|")).strip()
                continue
            if n < nh:
                under = [d for d in hr if d[2] - d[0] < 0.9 * (rect[2] - rect[0]) and y1 - 1 <= cy(d) <= y1 + h and d[0] - 2 <= (x0 + x1) / 2 <= d[2] + 2
                         and sum(d[0] - 2 <= (c[0] + c[1]) / 2 <= d[2] + 2 for c in cells) == 1]
                sides = [cx(d) for d in vr if d[1] <= y1 and d[3] >= y1 - h]
                left = max([x for x in sides if x <= x0], default=None)
                right = min([x for x in sides if x >= x1], default=None)
                span = []
                if under:
                    span = [i for i, (a, b) in enumerate(cols) if under[0][0] - 2 <= (a + b) / 2 <= under[0][2] + 2]
                elif left is not None and right is not None and sum(left < (c[0] + c[1]) / 2 < right for c in cells) == 1:
                    span = [i for i, (a, b) in enumerate(cols) if left < (a + b) / 2 < right]
                if not span and not under:
                    cc = (x0 + x1) / 2
                    nb = [(c[0] + c[1]) / 2 for c in cells if c[0] != x0]
                    ds = ([cc - max((cc + v) / 2 for v in nb if v < cc)] if any(v < cc for v in nb) else []) + ([min((cc + v) / 2 for v in nb if v > cc) - cc] if any(v > cc for v in nb) else [])
                    if ds:
                        taken = {base(c[0], c[1]) for c in cells if c[0] != x0}
                        span = [i for i, (a, b) in enumerate(cols) if abs((a + b) / 2 - cc) <= min(ds) and i not in taken]
                        me = base(x0, x1)
                        if me not in span or not all(i in occ[nh - 1] for i in span if i != me) or abs((cols[span[0]][0] + cols[span[-1]][1]) / 2 - cc) > 0.1 * (cols[span[-1]][1] - cols[span[0]][0]):
                            span = []
                if len(span) > 1 and all(any(i in occ[m] for m in range(nh) if m != n) for i in span):
                    hit = span
            for i in hit:
                row[i] = (row[i] + " " + " ".join(mk.get(w[:4], w[4]) for w in cw).replace("|", "\\|")).strip()
        grid.append((y, row))
    head = [" ".join(r[i] for _, r in grid[:nh] if r[i]) for i in range(len(cols))]
    body = grid[nh:]
    for a, b in zip(full, full[1:]):
        band = [r for y, r in body if a < y < b]
        labels = [r for r in band if r[0]]
        if len(band) > 1 and len(labels) == 1:
            lab = labels[0]
            if not any(lab[1:]):
                body = [(y, r) for y, r in body if r is not lab]
            for r in band:
                r[0] = lab[0]
    lines = ["| " + " | ".join(r) + " |" for r in [head] + [r for _, r in body]]
    lines = [re.sub(r"(</su[bp]>) (?=<su[bp]>)", r"\1", l) for l in lines]
    lines = [re.sub("([ˆ˜¯´`¨˙ˇ])([A-Za-z])", lambda m: m.group(2) + ACCENT[m.group(1)], l) for l in lines]
    return "\n".join(lines[:1] + ["|" + "---|" * len(cols)] + lines[1:])


used_names = set()


def crop_dpi(pg, clip):
    sizes = [s["size"] for b in pg.get_text("dict", clip=clip)["blocks"] for l in b.get("lines", []) for s in l["spans"]
             if s["size"] > 0 and re.search(r"\w", s["text"])]
    if sizes:
        return math.ceil(min(DPI, max(DPI_MIN, TEXT_PX * 72 / min(sizes))))
    native = []
    for im in pg.get_image_info():
        r = pymupdf.Rect(im["bbox"])
        if r.intersects(clip) and r.get_area() > 0:
            native.append(72 * math.sqrt(im["width"] * im["height"] / r.get_area()))
    return math.ceil(min(DPI, max(native))) if native else DPI


def save_crop(pg, rect, name, dpi=DPI, auto=False):
    clip = pymupdf.Rect(rect) & pg.rect
    if clip.is_empty:
        return None
    if name in used_names:
        name = f"{name[:-4]}-p{pg.number + 1:02d}.png"
    used_names.add(name)
    os.makedirs(figdir, exist_ok=True)
    pg.get_pixmap(clip=clip, dpi=crop_dpi(pg, clip) if auto else dpi).save(os.path.join(figdir, name))
    saved["img"] += 1
    return f"{os.path.basename(figdir)}/{name}"


INLINE = defaultdict(list)


def run_mineru(path, out, tier, what, pages):
    runs = [("GPU", GPU_PY, {"MINERU_MODEL_SMALL_BACKEND": "torch", "MINERU_DEVICE_MODE": "cuda"})] if os.path.exists(GPU_PY) else []
    runs.append(("CPU", os.path.join(HERE, "venv-mineru", "bin", "python"), {}))
    for name, py, env in runs:
        print(f"MinerU {what}（{pages} 頁，{name}）…", file=sys.stderr, flush=True)
        try:
            r = subprocess.run([py, "-I", os.path.join(HERE, "mineru_eq.py"), path, out, tier],
                               capture_output=True, text=True, env={**os.environ, **env})
        except OSError as e:
            r = subprocess.CompletedProcess([], 1, "", str(e))
        if not r.returncode:
            return True
        print(f"MinerU（{name}）失敗：" + (r.stderr.strip().splitlines() or ["?"])[-1], file=sys.stderr)
    return False


def load_tex():
    with tempfile.TemporaryDirectory() as tmp:
        out = KEEP or os.path.join(tmp, "eq.json")
        if not os.path.exists(out) and not run_mineru(src, out, TIER, "辨識公式中", total):
            print("MinerU 失敗，公式只輸出 PNG", file=sys.stderr)
            return None
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
    tex = defaultdict(list)
    for e in data["equations"]:
        tex[e["page"]].append(e)
    for e in data.get("inline", []):
        INLINE[e["page"]].append(e)
    return tex


def area(r):
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def overlap(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


IN_PUNCT = set("()[]\"“”'‘’.,;:!?")
IN_STRUCT = re.compile(r"[_^]|\\(?!(?:mathrm|mathbf|mathit|textrm|text|left|right)\b)[A-Za-z]+")
IN_TAIL = re.compile(r"\s*([,.;:]+)\s*$")
IN_ACCENT = re.compile(r"\\(?:overline|underline|widehat|widetilde|overrightarrow|hat|tilde|bar|vec|dot|ddot|breve|check|acute|grave)\b\s*")
ACCENT_GLYPHS = {"dot": "˙̇", "ddot": "¨̈", "hat": "ˆ^̂", "widehat": "ˆ^̂", "tilde": "˜~∼̃", "widetilde": "˜~∼̃", "bar": "¯̄̅", "overline": "¯̄̅", "underline": "", "vec": "→⃗", "overrightarrow": "→⃗", "breve": "˘̆", "check": "ˇ̌", "acute": "´́", "grave": "`̀"}
THIN_ACCENT = {"bar", "overline", "underline", "vec", "overrightarrow"}
IN_OPS = re.compile(r"\\(arg|max|min|log|ln|lg|exp|sin|cos|tan|sinh|cosh|tanh|cot|sec|csc|arcsin|arccos|arctan|lim|liminf|limsup|sup|inf|det|dim|ker|deg|gcd|hom|Pr|mod|bmod|pmod)(?![A-Za-z])")
IN_STACK = re.compile(r"\\(?:frac|dfrac|tfrac|cfrac|over|atop|choose|binom|dbinom|tbinom|overset|underset|stackrel|substack|underbrace|overbrace|limits)(?![A-Za-z])|\\sqrt\s*\[")
PUA = 0xF0000
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
    keep = [(ch, z, bd) for box, ch, font, z, bd in chars if inside(box, tr) and not font.upper().startswith("CMEX") and font not in SYM_FONTS]
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


def retry_tex():
    chars, bad, fixed = {p: page_chars(doc[p]) for p in TEX}, [], 0
    for p, es in TEX.items():
        for e in es:
            tr = tex_rect(e, doc[p])
            if tex_ok(chars[p], tr, e["latex"]):
                continue
            f = tex_fix(chars[p], tr, e["latex"])
            if tex_ok(chars[p], tr, f):
                e["latex"] = f
                fixed += 1
            else:
                bad.append(e)
    pages = sorted({e["page"] for e in bad})
    if not pages:
        return fixed, 0
    with tempfile.TemporaryDirectory() as tmp:
        out = f"{os.path.splitext(KEEP)[0]}-{RETRY_TIER}.json" if KEEP else os.path.join(tmp, "retry.json")
        data = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("pages") != pages:
                data = None
        if data is None:
            sub = pymupdf.open()
            for p in pages:
                sub.insert_pdf(doc, from_page=p, to_page=p)
            sub.save(os.path.join(tmp, "retry.pdf"))
            if not run_mineru(os.path.join(tmp, "retry.pdf"), out, RETRY_TIER, f"{RETRY_TIER} 重新辨識沒通過檢查的公式", len(pages)):
                return fixed, 0
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            data["pages"] = pages
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
    new = defaultdict(list)
    for x in data["equations"]:
        new[pages[x["page"]]].append(x)
    n = 0
    for e in bad:
        pg = doc[e["page"]]
        tr = tex_rect(e, pg)
        x = max(new[e["page"]], key=lambda x: overlap(tex_rect(x, pg), tr), default=None)
        if not x or overlap(tex_rect(x, pg), tr) < 0.5 * min(area(tex_rect(x, pg)), area(tr)):
            continue
        latex, m = outer_bars(x["latex"]), re.search(r"\\tag\s*\{[^}]*\}", e["latex"])
        if m and not re.search(r"\\tag\s*\{", latex):
            latex += m.group()
        for t in (latex, tex_fix(chars[e["page"]], tr, latex)):
            if tex_ok(chars[e["page"]], tr, t):
                e["latex"] = t
                n += 1
                break
    return fixed, n


def in_scripts(latex):
    sub, sup, i = Counter(), Counter(), 0
    while i < len(latex):
        c = latex[i]
        if c == "\\":
            i += len(re.match(r"\\(?:[A-Za-z]+|.?)", latex[i:]).group())
            continue
        i += 1
        if c not in "_^":
            continue
        while latex[i:i + 1] == " ":
            i += 1
        m = re.match(r"\\[A-Za-z]+\s*", latex[i:])
        j = i + (m.end() if m else 0)
        if latex[j:j + 1] == "{":
            j = group_end(latex, j)
        elif not m:
            j += 1
        t = latex[i:j]
        if re.search(r"(?<!\\)[_^]", t):
            return None
        (sub if c == "_" else sup).update(x for x in in_letters(t) if x.isascii() and x.isalnum())
        i = j
    return sub, sup


def in_shift(marks):
    big = max(m[3] for m in marks)
    base = [y for _, _, y, z, y0 in marks if z >= 0.85 * big and y0 is None]
    sub, sup = Counter(), Counter()
    for ch, raw, y, z, y0 in marks:
        if ch.isascii() and ch.isalnum():
            dy = y - (y0 if y0 is not None else min(base or [y], key=lambda v: abs(v - y)))
            kind = unicodedata.decomposition(raw).split(" ")[0]
            if kind == "<super>" or dy < -0.1 * big:
                sup[ch] += 1
            elif kind == "<sub>" or dy > 0.08 * big:
                sub[ch] += 1
    return sub, sup


def scripts(spans, ref=()):
    kinds = [None] * len("".join(s["text"] for s in spans))
    if not any(s["text"].strip() for s in spans):
        return kinds
    zc = Counter()
    for s in list(spans) + list(ref):
        zc[round(s["size"], 1)] += len(s["text"].strip())
    for z0 in (max(k for k, v in zc.items() if v), zc.most_common(1)[0][0]):
        kinds = [None] * len(kinds)
        y0 = Counter()
        for s in list(spans) + list(ref):
            if s["size"] >= 0.85 * z0:
                y0[round(s["origin"][1], 1)] += len(s["text"].strip())
        y0 = y0.most_common(1)[0][0]
        pos, big = 0, False
        for s in spans:
            if s["text"].strip() and (s["size"] <= 0.85 * z0 or is_katex(s["font"])):
                dy = s["origin"][1] - y0
                kind = "sup" if dy < -0.1 * z0 else "sub" if dy > 0.08 * z0 else None
                kinds[pos:pos + len(s["text"])] = [kind] * len(s["text"])
                big = big or (kind is not None and s["size"] >= 0.9 * BODY)
            pos += len(s["text"])
        if not big:
            break
    return kinds


def group_end(s, i):
    d = 0
    for j in range(i, len(s)):
        d += {"{": 1, "}": -1}.get(s[j], 0)
        if not d:
            return j + 1
    return len(s)


def rm_split(body):
    out, run, i = [], "", 0

    def flush():
        nonlocal run
        if run.strip():
            out.append("\\mathrm{" + re.sub(r"\s+", "", run) + "}" if re.search(r"[A-Za-z]", run) else re.sub(r"\s+", "", run))
        run = ""
    while i < len(body):
        c = body[i]
        if c.isalnum() or c in " .'-":
            run += c
            i += 1
        elif c == "{":
            flush()
            j = group_end(body, i)
            inner = rm_split(body[i + 1:j - 1])
            out.append("{" + inner + "}" if out and out[-1] in ("^", "_") else inner)
            i = j
        elif c == "\\":
            flush()
            m = re.match(r"\\[A-Za-z]+\s*|\\.?", body[i:])
            k = i + m.end()
            if re.match(r"\\[A-Za-z]", m.group()) and body[k:k + 1] == "{":
                k = group_end(body, k)
            out.append(body[i:k].strip())
            i = k
        else:
            flush()
            out.append(c)
            i += 1
    flush()
    return "".join(x for x in out if x)


def unroman(s):
    out, pos = "", 0
    for m in re.finditer(r"\\mathrm\s*\{", s):
        if m.start() < pos:
            continue
        j = group_end(s, m.end() - 1)
        body = s[m.end():j - 1]
        out += s[pos:m.start()] + (rm_split(body) if re.search(r"[^A-Za-z0-9\s.'-]", body) else s[m.start():j])
        pos = j
    return out + s[pos:]


def tidy(latex):
    segs, pos = [], 0
    for m in re.finditer(r"\\(?:text[a-z]*|mbox|tag)\s*\{", latex):
        if m.start() < pos:
            continue
        end = group_end(latex, m.end() - 1)
        segs += [latex[pos:m.start()], latex[m.start():end]]
        pos = end
    segs.append(latex[pos:])
    for i in range(0, len(segs), 2):
        s = re.sub(r"(\\(?:operatorname\*?|mathrm|mathbf|mathsf|mathit|mathtt|mathcal|mathbb|mathfrak|boldsymbol))\s*\{([^{}\\]*)\}",
                   lambda m: m.group(1) + "{" + re.sub(r"\s+", "", m.group(2)) + "}", segs[i])
        s = re.sub(r"\\mathrm\{([^{}\\]*[A-Za-z]-(?:[A-Za-z][^{}\\]*)?)\}", r"\\text{\1}", s)
        segs[i] = re.sub(r"[\d.](?: +[\d.])+",
                         lambda m: m.group() if re.search(r"[_^]\s*$", s[:m.start()]) else m.group().replace(" ", ""), s)
    for i in range(1, len(segs), 2):
        segs[i] = re.sub(r"(?<=[A-Za-z]) - (?=[A-Za-z])", "-", segs[i])
    return unroman("".join(segs))


SPACE = r"(?:~|\\[,;: !]|\\q?quad(?![A-Za-z])|\s)"


def text_word(w):
    w = re.sub(SPACE, "", w)
    return w if re.fullmatch(r"[;,]|[a-z]{2,}|(?:[a-z]\.){2},?|[a-z]{2,}\.,?", w) else None


def split_text(latex):
    parts, cur, i, par = [], "", 0, 0

    def flush():
        nonlocal cur
        parts.append(("math", cur))
        cur = ""
    while i < len(latex):
        c = latex[i]
        m = re.match(r"\\(?:mathrm|text|textrm|mbox)\s*\{", latex[i:])
        if m:
            j = group_end(latex, i + m.end() - 1)
            w = text_word(latex[i + m.end():j - 1])
            nxt = latex[j:].lstrip()
            if w and cur.rstrip()[-1:] not in ("^", "_") and nxt[:1] not in ("^", "_", "(", "[", "{") and not nxt.startswith("\\left"):
                flush()
                parts.append(("text", w))
            else:
                cur += latex[i:j]
            i = j
            continue
        m = re.match(r"(?:e\s*\.\s*g|i\s*\.\s*e)\s*\.(?:\s*,)?", latex[i:])
        if m and not re.search(r"[A-Za-z\\]$", cur):
            flush()
            parts.append(("text", re.sub(r"\s", "", m.group())))
            i += m.end()
            continue
        if c == ";" and par == 0:
            flush()
            parts.append(("text", ";"))
            i += 1
            continue
        if c == "{":
            j = group_end(latex, i)
            cur += latex[i:j]
            i = j
            continue
        if c == "\\":
            m = re.match(r"\\[A-Za-z]+|\\.?", latex[i:])
            cur += m.group()
            i += m.end()
            continue
        par += (c in "([") - (c in ")]")
        cur += c
        i += 1
    flush()
    return parts


def unmatched(s):
    st, bad, i = [], set(), 0
    while i < len(s):
        if s[i] == "\\":
            i += re.match(r"\\(?:left|right|[bB]igg?[lr]?)(?![A-Za-z])\s*(?:\\?.)?|\\[A-Za-z]+|\\.?", s[i:]).end()
            continue
        c = s[i]
        if c in "([":
            st.append(i)
        elif c in ")]":
            if st and s[st[-1]] == "(["[")]".index(c)]:
                st.pop()
            else:
                bad.add(i)
        i += 1
    return bad | set(st)


def glue(parts):
    out = ""
    for p in parts:
        if out and not out.endswith(("(", "[")) and not p.startswith((")", "]", ",", ";", ":", ".")):
            out += " "
        out += p
    return out


def cut_lead(latex, lead):
    need = [c for c in lead if c.isascii() and c.isalnum()]
    punct = re.sub(r"[A-Za-z\d.]", "", lead)
    i, k, d = 0, 0, 0
    while i < len(latex) and k < len(need):
        m = re.match(r"\\[A-Za-z]+", latex[i:])
        if m:
            i += m.end()
            continue
        c = latex[i]
        d += {"{": 1, "}": -1}.get(c, 0)
        if c.isascii() and c.isalnum():
            if c != need[k]:
                return None
            k += 1
        i += 1
    while i < len(latex) and latex[i] in " }":
        d -= latex[i] == "}"
        i += 1
    m = re.match(r"\s*" + r"\s*".join(map(re.escape, punct)), latex[i:])
    if k < len(need) or d or not m:
        return None
    return latex[i + m.end():]


ARG2 = {"frac", "dfrac", "tfrac", "cfrac", "binom", "dbinom", "tbinom", "overset", "underset", "stackrel", "begin"}
SCOPED = re.compile(r"\\(?:over|atop|choose|bf|it|rm|sf|tt|cal)(?![A-Za-z])")


def free_groups(s):
    out, i, need, hit = [], 0, 0, False
    while i < len(s):
        c = s[i]
        if c == "{":
            j = group_end(s, i)
            inner = s[i + 1:j - 1]
            if need == 0 and re.search(r"[A-Za-z0-9\\]", inner) and not SCOPED.search(inner) and not re.match(r"\s*[_^']", s[j:]):
                out.append(" " + inner.strip() + " ")
                hit = True
            else:
                out.append(s[i:j])
                need = max(0, need - 1)
            i = j
        elif c == "\\":
            m = re.match(r"\\[A-Za-z]+\*?|\\.?", s[i:])
            out.append(m.group())
            i += m.end()
            if m.group()[1:] in ARG2:
                need = 2
            elif m.group()[1:2].isalpha():
                need = 1
        elif c in "^_":
            out.append(c)
            i += 1
            need = 1
        else:
            out.append(c)
            i += 1
            if not c.isspace():
                need = 0
    return free_groups(re.sub(r"\s+", " ", "".join(out)).strip()) if hit else s


def inline_fmt(latex, lead=None):
    latex = free_groups(latex)
    rest = cut_lead(latex, lead) if lead else None
    if rest and rest.strip():
        return glue([lead, inline_fmt(rest)])
    parts = split_text(latex)
    split = len(parts) > 1
    res = []
    for kind, s in parts:
        if kind == "text":
            res.append(s)
            continue
        s = re.sub(rf"^{SPACE}+|{SPACE}+$", "", tidy(s))
        pre = close = cite = post = ""
        if split:
            m = re.match(r"[,;:.]+", s)
            pre = m.group() if m else ""
            s = re.sub(rf"^{SPACE}+", "", s[len(pre):])
            m = re.search(r"[,;:.]+$", s)
            post = m.group() if m else ""
            s = re.sub(rf"{SPACE}+$", "", s[:len(s) - len(post)])
        bad = unmatched(s)
        if bad and all(s[b] in ")]" for b in bad):
            last = max(bad)
            if not re.search(r"[A-Za-z^_]", re.sub(SPACE, "", s[last + 1:])) and re.search(r"\d", s[last + 1:]):
                cite = re.sub(r"[\s{}]", "", s[last + 1:])
                s = s[:last + 1].rstrip()
                bad = unmatched(s)
        if bad and len({s[b] in "([" for b in bad}) == 1:
            i0, i1 = 0, len(s)
            while i0 < i1 and (i0 in bad or s[i0] == " "):
                i0 += 1
            while i1 > i0 and (i1 - 1 in bad or s[i1 - 1] == " "):
                i1 -= 1
            if all(b < i0 or b >= i1 for b in bad):
                pre += s[:i0].replace(" ", "")
                close = s[i1:].replace(" ", "")
                s = s[i0:i1]
        if pre:
            res.append(pre)
        if s:
            res.append(f"${s}$" if re.search(r"[A-Za-z\\^_]", s) else re.sub(r"\s+", "", s))
        res += [x for x in (close, cite, post) if x]
    return glue(res)


IN_ARRAY = re.compile(r"\\begin\{array\}\s*\{\s*[a-z|]+\s*\}\s*(.*?)\s*\\end\{array\}")


def in_unwrap(latex):
    def one(m):
        body = re.sub(r"\\\\\s*$", "", m.group(1)).strip()
        if "&" in body or "\\\\" in body or "\\begin" in body:
            return m.group(0)
        if body.startswith("{") and group_end(body, 0) == len(body):
            body = body[1:-1].strip()
        return body
    return IN_ARRAY.sub(one, latex)


def inline_latex(latex, gap, odd, text, marks, lead=None):
    if "$" in latex:
        return None
    flat = re.sub(r"\\left\\\{\s*\\begin\{matrix\}(.*?)\\end\{matrix\}\s*\\right\.", lambda m: "\\begin{cases}" + m.group(1) + "\\end{cases}", in_unwrap(latex), flags=re.S)
    latex, unwrapped = re.sub(r"\s+", " ", flat).strip(), flat != latex
    if unwrapped and latex and latex[0] in "([" and gap[:1] != latex[0]:
        latex = latex[1:].lstrip()
    latex = IN_TAIL.sub("", latex)
    if not odd or not latex or not IN_STRUCT.search(latex) or "\\begin" in latex.replace("\\begin{cases}", "") or "\\end" in latex.replace("\\end{cases}", ""):
        return None
    if any(greek(c) and not re.search(r"\\(?:var)?" + greek(c) + r"\b", latex.lower()) for c in gap):
        return None
    bare = re.sub(r"\\[A-Za-z]+", "", re.sub(r"\\(?:l?dots|ldotp)\b", "...", latex))
    if set(c for c in IN_TAIL.sub("", gap) if c in IN_PUNCT) - set(c for c in bare if c in IN_PUNCT):
        return None
    if set(c for c in bare if c in "()[]") - set(c for c in gap if c in "()[]"):
        return None
    if re.search(r"\\[lr]angle(?![A-Za-z])", latex) and not any(c in "⟨⟩〈〉<>" for c in gap):
        return None
    alnum = lambda t: "".join(c for c in t if c.isascii() and c.isalnum()).lower()
    if SequenceMatcher(None, alnum(bare), alnum(gap)).ratio() < 0.5:
        return None
    letters = lambda t: Counter(c for c in t if c.isascii() and c.isalpha())
    if letters(in_letters(latex.replace("\\begin{cases}", "").replace("\\end{cases}", ""))) != letters(text):
        return None
    sc = None if IN_STACK.search(latex) else in_scripts(latex)
    if sc and sc != in_shift(marks):
        return None
    return inline_fmt(latex, lead)


def in_word(c):
    return c.isalnum() or c in "-‐"


ACCENT = {"ˆ": "̂", "˜": "̃", "^": "̂", "~": "̃", "`": "̀", "´": "́", "¨": "̈", "¯": "̄", "˙": "̇", "ˇ": "̌", "˘": "̆"}


def katex_flow(pg, raw):
    d = pg.get_text("rawdict" if raw else "dict", sort=False)["blocks"]
    if not any(is_katex(s["font"]) for b in d for l in b.get("lines", []) for s in l["spans"]):
        return d
    r = d if raw else pg.get_text("rawdict", sort=False)["blocks"]
    if [len(b.get("lines", [])) for b in r] != [len(b.get("lines", [])) for b in d]:
        return d
    dx = lambda a, b: max(0, a[0] - b[2], b[0] - a[2])
    host, kat = [], []
    for bi, b in enumerate(r):
        for li, l in enumerate(b.get("lines", [])):
            ss = [s for s in l["spans"] if "".join(c["c"] for c in s["chars"]).replace("\u200b", "").strip()]
            if tuple(l["dir"]) == (1, 0) and ss:
                (kat if all(is_katex(s["font"]) for s in ss) else host).append((bi, li, tuple(l["bbox"])))
    groups = []
    for k in sorted(kat, key=lambda k: k[2][0]):
        hit = [g for g in groups if any(vov(k[2], o[2]) >= 0.5 * min(k[2][3] - k[2][1], o[2][3] - o[2][1]) and k[2][0] - o[2][2] <= 12 for o in g)]
        groups = [g for g in groups if g not in hit] + [sum(hit, []) + [k]]
    rows = defaultdict(list)
    for g in groups:
        gb = union([k[2] for k in g])
        cand = [h for h in host if vov(gb, h[2]) >= 0.5 * (h[2][3] - h[2][1])]
        best = None
        for h in cand:
            row = [o for o in host if o[0] == h[0] and vov(h[2], o[2]) >= 0.5 * (h[2][3] - h[2][1])]
            span = union([o[2] for o in host if o[0] == h[0]])
            dist = min(dx(gb, o[2]) for o in row)
            if (dist <= 6 or span[0] - 2 <= gb[0] and gb[2] <= span[2] + 6) and (best is None or dist < best[0]):
                best = (dist, h[0], tuple(sorted(o[1] for o in row)))
        if best:
            rows[best[1:]] += g
    if not rows:
        return d
    drop, put = set(), {}
    for (bi, lis), g in rows.items():
        hl = sorted(lis, key=lambda li: r[bi]["lines"][li]["bbox"][0])
        seq = [((bi, li, si), c) for li in hl for si, s in enumerate(r[bi]["lines"][li]["spans"]) for c in s["chars"]]
        ks = []
        for kb, kl, _ in sorted(g, key=lambda k: (k[0], k[1])):
            for si, s in enumerate(r[kb]["lines"][kl]["spans"]):
                ch = [c for c in s["chars"] if c["c"] != "\u200b"]
                if ch:
                    ks.append(((kb, kl, si), ch))
            drop.add((kb, kl))
        ks.sort(key=lambda k: k[1][0]["bbox"][0])
        pieces, hi = [], 0
        def add(src, ch):
            if pieces and pieces[-1][0] == src:
                pieces[-1][1].extend(ch)
            else:
                pieces.append((src, list(ch)))
        for src, ch in ks:
            while hi < len(seq) and seq[hi][1]["bbox"][0] < ch[0]["bbox"][0] - 0.3:
                add(seq[hi][0], [seq[hi][1]])
                hi += 1
            add(src, ch)
        for src, c in seq[hi:]:
            add(src, [c])
        prev = None
        for _, ch in pieces:
            for k, c in enumerate(ch):
                if prev and c["c"] in ACCENT and prev["c"].isalpha() and abs(c["origin"][0] - prev["origin"][0]) < 0.3:
                    ch[k] = c = dict(c, c=ACCENT[c["c"]])
                prev = c
        spans = []
        for (sb, sl, si), ch in pieces:
            rs, ds = r[sb]["lines"][sl]["spans"][si], d[sb]["lines"][sl]["spans"][si]
            runs = [[ch[0]]]
            for c in ch[1:]:
                if abs(c["origin"][1] - runs[-1][0]["origin"][1]) > 0.5:
                    runs.append([c])
                else:
                    runs[-1].append(c)
            for ch in runs:
                if len(ch) == len(rs["chars"]) and all(a is b for a, b in zip(ch, rs["chars"])):
                    spans.append(ds)
                elif raw:
                    spans.append(dict(ds, chars=ch, bbox=union([c["bbox"] for c in ch]), origin=ch[0]["origin"]))
                else:
                    spans.append(dict(ds, text="".join(c["c"] for c in ch), bbox=union([c["bbox"] for c in ch]), origin=ch[0]["origin"]))
        hb = union([r[bi]["lines"][li]["bbox"] for li in hl])
        xb = union([s["bbox"] for s in spans])
        put[(bi, hl[0])] = dict(d[bi]["lines"][hl[0]], spans=spans, bbox=(xb[0], hb[1], xb[2], hb[3]))
        drop.update((bi, li) for li in hl[1:])
    out = []
    for bi, b in enumerate(d):
        if b["type"] != 0 or not any((bi, li) in drop or (bi, li) in put for li in range(len(b["lines"]))):
            out.append(b)
            continue
        ls = [put.get((bi, li), l) for li, l in enumerate(b["lines"]) if (bi, li) not in drop]
        if ls:
            out.append(dict(b, lines=ls, bbox=union([l["bbox"] for l in ls])))
    return out


def gap_spot(sel, pos, lt, rt, ink):
    def hit(x0, x1, ly):
        return [r for r in ink if x0 <= (r[0] + r[2]) / 2 <= x1 and ly[1] <= (r[1] + r[3]) / 2 <= ly[3]]
    L = pos[lt] if lt >= 0 else None
    R = pos[rt] if rt < len(pos) else None
    if L and R and L[0] == R[0]:
        ch = sel[R[0]][1]
        h = hit(ch[L[1]]["bbox"][2], ch[R[1]]["bbox"][0], sel[R[0]][0]) if L[1] < R[1] else []
        if not h:
            return None
        mid = (min(r[0] for r in h) + max(r[2] for r in h)) / 2
        return R[0], next(i for i in range(L[1] + 1, R[1] + 1) if i == R[1] or ch[i]["bbox"][0] >= mid)
    if R and hit(sel[R[0]][1][R[1]]["bbox"][0] - 40, sel[R[0]][1][R[1]]["bbox"][0], sel[R[0]][0]):
        return R
    if L and hit(sel[L[0]][1][L[1]]["bbox"][2], sel[L[0]][1][L[1]]["bbox"][2] + 40, sel[L[0]][0]):
        return L[0], L[1] + 1
    return None


def inline_map(pg, pno):
    items = INLINE.get(pno)
    if not items:
        return {}
    lines, imgs = [], []
    for b in katex_flow(pg, True):
        if b["type"] != 0:
            imgs.append(tuple(b["bbox"]))
            continue
        for l in b["lines"]:
            chars = [dict(c, font=s["font"], size=s["size"], flags=s["flags"]) for s in l["spans"] for c in s["chars"]]
            ink = [c for c in chars if not c["c"].isspace()]
            if tuple(l["dir"]) != (1, 0) or not ink:
                continue
            f0 = Counter(c["font"] for c in ink).most_common(1)[0][0]
            z0 = Counter(round(c["size"], 1) for c in ink).most_common(1)[0][0]
            y0 = Counter(round(c["origin"][1]) for c in ink).most_common(1)[0][0]
            for c in chars:
                c["odd"] = c["font"] != f0 or abs(c["size"] - z0) > 0.6 or abs(c["origin"][1] - y0) > 1.2
                c["y0"] = y0 if is_katex(c["font"]) else None
            lines.append((tuple(l["bbox"]), chars))
    out, rules, ink = defaultdict(list), None, None
    for it in items:
        tr = tex_rect(it, pg)
        sel = [(lb, ch) for lb, ch in lines if inside(lb, tr)]
        S, T, pos, odd = [], [], [], []
        for li, (lb, ch) in enumerate(sel):
            for ci, c in enumerate(ch):
                for x in unicodedata.normalize("NFKC", c["c"]).replace("−", "-").replace("‐", "-"):
                    if not x.isspace():
                        S.append(x.lower())
                        T.append(x)
                        pos.append((li, ci))
                        odd.append(c["odd"] or ord(x) > 0x24F)
        S = "".join(S)
        M, bounds, forms = [], [], []
        for kind, t in it["parts"]:
            if kind == "e":
                bounds.append(sum(len(x) for x in M))
                forms.append(t.strip())
            else:
                M.append("".join(x.lower() for x in unicodedata.normalize("NFKC", t).replace("−", "-") if not x.isspace()))
        M = "".join(M)
        m2s = {m.b + k: m.a + k for m in SequenceMatcher(None, S, M, autojunk=False).get_matching_blocks() if m.size >= 3 or not any(odd[m.a:m.a + m.size]) for k in range(m.size)}
        if bounds and 0 < len(M) - bounds[-1] < 3 and S.endswith(M[bounds[-1]:]):
            m2s.update((j, len(S) - len(M) + j) for j in range(bounds[-1], len(M)))
        if bounds and 0 < bounds[0] < 3 and S.startswith(M[:bounds[0]]):
            m2s.update((j, j) for j in range(bounds[0]))
        groups = []
        for bd, f in zip(bounds, forms):
            if groups and groups[-1][0] == bd:
                groups[-1][1].append(f)
            else:
                groups.append([bd, [f]])
        for bd, fs in groups:
            lt = m2s.get(bd - 1) if bd > 0 else -1
            rt = m2s.get(bd) if bd < len(M) else len(S)
            if lt is not None and rt is not None and rt - lt == 1:
                if ink is None:
                    ink = [r for r in imgs if r[2] - r[0] < 80 and r[3] - r[1] < 40] + \
                          [tuple(d["rect"]) for d in pg.get_drawings() if 2 <= d["rect"].width < 60 and 2 <= d["rect"].height < 40]
                spot = gap_spot(sel, pos, lt, rt, ink)
                latex = IN_TAIL.sub("", re.sub(r"\s+", " ", " ".join(fs)).strip())
                if spot and IN_STRUCT.search(latex) and "\\begin" not in latex and (re.search(r"[A-Za-z\d]", in_letters(latex)) or TEX_GREEK.search(latex)):
                    li, ci = spot
                    ch = sel[li][1]
                    o = sum(len(c["c"]) for c in ch[:ci])
                    md = (" " if ci > 0 and not ch[ci - 1]["c"].isspace() else "") + inline_fmt(latex) + (" " if ci < len(ch) and not ch[ci]["c"].isspace() else "")
                    out[sel[li][0]].append((o, o, md))
                continue
            if lt is None or rt is None or rt - lt <= 1:
                continue
            core = IN_TAIL.sub("", re.sub(r"\s+", " ", in_unwrap(" ".join(fs))).strip())
            a, b = lt + 1, rt
            while b > a and (not odd[b - 1] and S[b - 1] in IN_PUNCT or S[b - 1] in ".,;:") and S[b - 1] != core[-1:]:
                b -= 1
            while a < b and not odd[a] and S[a] in IN_PUNCT and S[a] != core[:1]:
                a += 1
            if b <= a:
                continue
            fo = lambda k: sel[pos[k][0]][1][pos[k][1]]["font"]
            fl = lambda k: sel[pos[k][0]][1][pos[k][1]]["flags"]
            tail, k = "", b
            while k < len(S) and odd[k] and S[k].isascii() and S[k].isalpha() and pos[k][0] == pos[b - 1][0] and fo(k) == fo(b - 1) and not re.search(r"(?i)italic|oblique|MI\d|Math", fo(k)) and not fl(k) & 2 \
                    and bd + k - b < len(M) and M[bd + k - b] == S[k]:
                k += 1
            if k > b:
                tail, b = "".join(T[b:k]), k
            (l0, c0), (l1, c1) = pos[a], pos[b - 1]
            ch0, ch1 = sel[l0][1], sel[l1][1]
            if b < len(S) and S[b] in ".,;:" and pos[b][0] == l1 and all(ch1[k]["c"].isspace() for k in range(c1 + 1, pos[b][1])):
                c1 = pos[b][1] - 1
            if c0 > 0 and in_word(ch0[c0 - 1]["c"]) or c1 + 1 < len(ch1) and in_word(ch1[c1 + 1]["c"]):
                continue
            latex = " ".join(fs) + (" \\mathrm{" + tail + "}" if tail else "")
            gc = [sel[li][1][ci] for li, ci in pos[a:b]]
            if IN_ACCENT.search(latex):
                box = (min(c["bbox"][0] for c in gc), min(c["bbox"][1] for c in gc) - 6, max(c["bbox"][2] for c in gc), max(c["bbox"][3] for c in gc) + 3)
                if rules is None:
                    rules = [tuple(d["rect"]) for d in pg.get_drawings() if d["rect"].height <= 1.5 and d["rect"].width >= 2]
                thin = any(r[0] < box[2] and box[0] < r[2] and box[1] <= r[1] <= box[3] for r in rules)
                seen = {c["c"] for _, ch in lines for c in ch if inside(c["bbox"], box)}
                latex = IN_ACCENT.sub(lambda m: m.group() if (thin and m.group().strip()[1:] in THIN_ACCENT) or any(g in seen for g in ACCENT_GLYPHS[m.group().strip()[1:]]) else "", latex)
            lead = re.match(r"[A-Za-z][A-Za-z\d.]*[,;:]", "".join(T[a:b]))
            lead = lead.group() if lead and a + lead.end() < b and not any(odd[a:a + lead.end()]) and odd[a + lead.end()] else None
            md = inline_latex(latex, cgap(S, a, b, fo), any(odd[a:b]), "".join(t for t, k in zip(T[a:b], range(a, b)) if not fo(k).upper().startswith("CMEX")), [(t, c["c"], c["origin"][1], c["size"], c["y0"]) for t, c, k in zip(T[a:b], gc, range(a, b)) if not fo(k).upper().startswith("CMEX")], lead)
            if not md and len(fs) > 1 and not tail:
                n = sum(c.isascii() and c.isalnum() for c in in_letters(fs[-1]))
                idx = [i for i in range(a, b) if S[i].isascii() and S[i].isalnum()]
                if n and len(idx) > n and re.match(r"[A-Za-z0-9]", fs[-1].strip()):
                    a, latex = idx[-n], fs[-1]
                    (l0, c0), (l1, c1) = pos[a], pos[b - 1]
                    gc = [sel[li][1][ci] for li, ci in pos[a:b]]
                    md = inline_latex(latex, S[a:b], any(odd[a:b]), "".join(T[a:b]), [(t, c["c"], c["origin"][1], c["size"], c["y0"]) for t, c in zip(T[a:b], gc)], None)
            if not md:
                continue
            rest = "".join(c["c"] for c in sel[l1][1][c1 + 1:]).strip() if l1 != l0 else ""
            lone = bool(rest) and set(rest) <= set(".,;:")
            ptxt = "".join(c["c"] for c in sel[pos[b][0]][1]).strip() if b < len(S) and S[b] in ".,;:" and pos[b][0] != l1 else ""
            trail = pos[b][0] if ptxt and set(ptxt) <= set(".,;:") else None
            for li in range(l0, l1 + 1):
                ch = sel[li][1]
                off = [0]
                for c in ch:
                    off.append(off[-1] + len(c["c"]))
                out[sel[li][0]].append((off[c0] if li == l0 else 0, off[-1] if lone and li == l1 else off[c1 + 1] if li == l1 else off[-1], ((md + rest if lone else md) + (T[b] if trail is not None else "")) if li == l0 else ""))
            if trail is not None:
                out[sel[trail][0]].append((0, sum(len(c["c"]) for c in sel[trail][1]), ""))
    return out


CMEX_UNI = {"P": "∑", "X": "∑", "Y": "∏", "\x00": "(", "\x01": ")", "\x02": "[", "\x03": "]", "\x10": "(", "\x11": ")", "!": ")", '"': "[", "#": "]", "h": "[", "i": "]"}
def cmex_raw(spans):
    return "".join("".join(CMEX_UNI.get(c, c) for c in s["text"]) if s["font"].upper().startswith("CMEX") else s["text"] for s in spans)


def cgap(S, a, b, fo):
    return re.sub(r"\d+:", "", "".join("{" if x == "(" and fo(k).upper().startswith("CMEX") else x for x, k in zip(S[a:b], range(a, b))))


def inline_md(raw, segs, kinds):
    def plain(a, b):
        out, i = "", a
        while i < b:
            j = i
            while j < b and kinds[j] == kinds[i]:
                j += 1
            seg, k = raw[i:j], kinds[i]
            body = seg.strip()
            if k and any(c.isalnum() for c in body):
                out += seg[:len(seg) - len(seg.lstrip())] + f"<{k}>{body}</{k}>" + seg[len(seg.rstrip()):]
            else:
                out += seg
            i = j
        return out
    text, last, subs = "", 0, []
    for a, b, md in sorted(segs):
        text += plain(last, a) + (chr(PUA + len(subs)) if md else "")
        subs.append(md)
        last = b
    text = norm(text + plain(last, len(raw)))
    for i, md in enumerate(subs):
        text = text.replace(chr(PUA + i), md)
    return text


TEX = load_tex()
size_count, font_count, SYM_FONTS, math_count = Counter(), Counter(), set(), Counter()
for pg in doc:
    for b in pg.get_text("dict", sort=False)["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                size_count[round(s["size"], 1)] += len(s["text"].strip())
                font_count[s["font"]] += len(s["text"].strip())
                math_count[s["font"]] += sum(unicodedata.category(c) == "Sm" or "\u0370" <= c <= "\u03ff" or "\U0001d400" <= c <= "\U0001d7ff" for c in s["text"] if not c.isspace())
                if any((ord(c) < 32 and c not in "\t\n\r") or 0xE000 <= ord(c) <= 0xF8FF for c in s["text"]):
                    SYM_FONTS.add(s["font"])
TEX_FIX, TEX_RETRY = retry_tex() if TEX else (0, 0)
BODY =size_count.most_common(1)[0][0] if size_count else 12.0
CM_BODY = bool(font_count) and font_count.most_common(1)[0][0].upper().startswith("CM")
MATH_FONTS = {f for f in font_count if f != font_count.most_common(1)[0][0] and math_count[f] > 0.5 * font_count[f]}

def split_at_rule(b, drawings):
    ls, rect = b["lines"], tuple(b["bbox"])
    lab = caption_label(norm("".join(s["text"] for s in ls[0]["spans"]))) if ls else None
    if not lab or not lab.upper().startswith("TAB"):
        return [(rect, ls)]
    for ry in sorted(cy(d) for d in drawings if d[3] - d[1] <= 2 and d[2] - d[0] >= 0.3 * (rect[2] - rect[0]) and xov(d, rect) and rect[1] < cy(d) < rect[3]):
        up = [l for l in ls if l["bbox"][3] <= ry + 1]
        dn = [l for l in ls if l["bbox"][3] > ry + 1]
        if up and dn and all(l["bbox"][1] >= ry - 1 for l in dn):
            return [(union([l["bbox"] for l in up]), up), (union([l["bbox"] for l in dn]), dn)]
    return [(rect, ls)]


pages = []
for pno, pg in enumerate(doc):
    W, H = pg.rect.width, pg.rect.height
    im = inline_map(pg, pno)
    drawings = []
    for d in pg.get_drawings():
        r = tuple(d["rect"])
        if r[2] - r[0] > 0.95 * W or r[3] - r[1] > 0.95 * H:
            continue
        if r[3] - r[1] < 1:
            r = (r[0], r[1] - 0.5, r[2], r[3] + 0.5)
        if r[2] - r[0] < 1:
            r = (r[0] - 0.5, r[1], r[2] + 0.5, r[3])
        drawings.append(r)
    blocks, chars = [], 0
    for b in katex_flow(pg, False):
        if b["type"] != 0:
            blocks.append({"img": True, "rect": tuple(b["bbox"]), "rot": False, "size": 0, "chars": 0, "lines": []})
            continue
        for rect, part in split_at_rule(b, drawings):
            lines, cnt = [], Counter()
            for l in part:
                for s in l["spans"]:
                    cnt[round(s["size"], 1)] += len(s["text"].strip())
                raw = "".join(s["text"] for s in l["spans"])
                text = norm(raw)
                if text:
                    lines.append({"md": inline_md(cmex_raw(l["spans"]), im.get(tuple(l["bbox"]), []), scripts(l["spans"])), "text": text, "size": max(round(s["size"], 1) for s in l["spans"]), "rot": tuple(l["dir"]) != (1, 0), "rect": tuple(l["bbox"]), "bold": is_bold(l["spans"]), "spans": [span_info(s) for s in l["spans"]]})
            if lines:
                n_chars = sum(len(l["text"]) for l in lines)
                chars += n_chars
                blocks.append({"img": False, "rect": rect, "rot": any(l["rot"] for l in lines), "size": cnt.most_common(1)[0][0], "chars": n_chars, "lines": lines})
    pages.append({"W": W, "H": H, "blocks": blocks, "drawings": drawings, "chars": chars})


VOCAB = Counter()
for P in pages:
    for b in P["blocks"]:
        for l in b["lines"]:
            toks = re.findall(r"[A-Za-z]+", l["text"])
            if l["text"].endswith("-") and toks:
                toks = toks[:-1]
            VOCAB.update(t.lower() for t in toks)


HS_MIN = max(BODY + 3, BODY * 1.3)
HSIZES = set()
for P in pages:
    for b in P["blocks"]:
        if not b["img"] and not b["rot"] and b["size"] >= HS_MIN and not BULLET_RE.match(b["lines"][0]["text"]):
            HSIZES.add(b["size"])
HSIZES = sorted(HSIZES, reverse=True)


def band_of(P, b):
    c = cy(b["rect"])
    return "header" if c < 0.1 * P["H"] else "footer" if c > 0.9 * P["H"] else None


bands = {"header": defaultdict(list), "footer": defaultdict(list)}
for pno, P in enumerate(pages):
    for b in P["blocks"]:
        where = None if b["img"] or b["rot"] else band_of(P, b)
        if where:
            bands[where][pno] += [l["text"] for l in b["lines"] if key(l["text"])]
need = max(3, math.ceil(total / 2))
pn = {pno: [(k, int(b["lines"][0]["text"].strip()) - (pno + 1)) for k, b in enumerate(P["blocks"]) if not b["img"] and not b["rot"] and len(b["lines"]) == 1 and re.fullmatch(r"\d{1,4}", b["lines"][0]["text"].strip()) and band_of(P, b)] for pno, P in enumerate(pages)}
cnt = Counter(c for v in pn.values() for c in {c for _, c in v})
PN_C = cnt.most_common(1)[0][0] if cnt and cnt.most_common(1)[0][1] >= need else None
PNUM = {pno: {k for k, c in v if c == PN_C} for pno, v in pn.items()}
targets, found = [], []
band_keys = {"header": set(), "footer": set()}
for where, label in (("header", "頁首"), ("footer", "頁尾")):
    per_page = bands[where]
    seen = Counter()
    for ts in per_page.values():
        seen.update({key(t) for t in ts})
    keys, shown = [], {}
    for pno in sorted(per_page):
        for t in per_page[pno]:
            k = key(t)
            if seen[k] >= need and k not in keys:
                keys.append(k)
                shown[k] = re.sub(r"\d+", "N", t.strip())
    band_keys[where] = set(keys)
    if keys:
        targets.append("".join(keys))
        found.append(f"{label}: {' '.join(shown[k] for k in keys)}")


def strip_targets(line):
    for t in targets:
        k = key(line)
        if k == t:
            return ""
        if k.endswith(t):
            i = next((i for i in range(len(line) - 1, -1, -1) if key(line[i:]) == t), None)
            line = line[:i].rstrip()
        elif k.startswith(t):
            i = next((i for i in range(1, len(line) + 1) if key(line[:i]) == t), None)
            line = line[i:].lstrip()
    return line


def band(blocks, drawings, skip, cr, lo, hi):
    ks = [k for k, b in enumerate(blocks) if k not in skip and lo - 1 <= cy(b["rect"]) <= hi and xov(b["rect"], cr)]
    ds = [dk for dk, d in enumerate(drawings) if lo - 1 <= cy(d) <= hi and xov(d, cr) and not (d[1] < lo - 1 and d[3] > hi + 1)]
    return ks, ds


def prose(b, width):
    if b["size"] < BODY - 0.5 or b["chars"] < 30 or b["rect"][2] - b["rect"][0] < 0.6 * width:
        return False
    if not stacked(b):
        return False
    if sum(l["rect"][0] - b["rect"][0] <= 15 for l in b["lines"]) < 0.5 * len(b["lines"]):
        return False
    text = "".join(l["text"] for l in b["lines"]).replace(" ", "")
    if sum(c.isalpha() for c in text) < 0.6 * len(text):
        return False
    for l in b["lines"]:
        rs = sorted(s["rect"] for s in l["spans"] if not s["blank"])
        if any(q[0] - p[2] > 1.5 * l["size"] for p, q in zip(rs, rs[1:])):
            return False
    return True


def stacked(b):
    rs = [l["rect"] for l in b["lines"]]
    return not any(vov(p, q) > 0.5 * min(p[3] - p[1], q[3] - q[1]) for i, p in enumerate(rs) for q in rs[i + 1:])


def anchor(b, width=None):
    if b["img"] or caption_label(b["lines"][0]["text"]):
        return True
    return b["size"] >= BODY - 1 and b["chars"] >= 30 if width is None else prose(b, width)


def process_page(pno, pg):
    P = pages[pno]
    n = pno + 1
    W, H, blocks, drawings = P["W"], P["H"], P["blocks"], P["drawings"]
    if P["chars"] < 20 and any(b["img"] for b in blocks):
        link = save_crop(pg, tuple(pg.rect), f"page-{n:02d}.png", 150)
        return [("img", f"![第 {n} 頁]({link})")] if link else []
    skip = {k for k, b in enumerate(blocks) if not b["img"] and b["rot"] and (b["rect"][2] < 0.1 * W or b["rect"][0] > 0.9 * W)}
    skip |= PNUM.get(pno, set())
    algos = algo_box(blocks, drawings, skip)
    for a in algos.values():
        skip.update(a["ks"])

    caps, cap_idx = [], set()
    for i, b in enumerate(blocks):
        if b["img"] or i in skip:
            continue
        lab = caption_label(b["lines"][0]["text"])
        if not lab:
            continue
        is_table = lab.upper().startswith("TAB")
        idx, rect = [i], b["rect"]
        if is_table:
            j = i + 1
            while (j < len(blocks) and not blocks[j]["img"] and j not in skip and blocks[j]["size"] < BODY - 1
                   and xov(blocks[j]["rect"], rect) and is_upper(" ".join(l["text"] for l in blocks[j]["lines"]))
                   and not caption_label(blocks[j]["lines"][0]["text"])):
                idx.append(j)
                rect = union([rect, blocks[j]["rect"]])
                j += 1
        for j, o in enumerate(blocks):
            if (j not in idx and j not in skip and j not in cap_idx and not o["img"] and xov(o["rect"], rect)
                    and rect[1] <= o["rect"][1] < rect[3] - 1 and not caption_label(o["lines"][0]["text"]) and not PAGE_NUM_RE.match(o["lines"][0]["text"])):
                idx.append(j)
                rect = union([rect, o["rect"]])
        caps.append({"kind": "table" if is_table else "fig", "label": lab, "idx": idx, "rect": rect})
        cap_idx.update(idx)

    consumed, dused, tables, figs = set(), set().union(*(a["dks"] for a in algos.values())), [], []
    for g in caps:
        if g["kind"] != "table":
            continue
        cr = g["rect"]
        top = max(blocks[k]["rect"][3] for k in g["idx"])
        bottom = H - 36
        below = sorted([(b["rect"], k) for k, b in enumerate(blocks) if k not in skip and k not in g["idx"] and b["rect"][1] >= top - 1 and xov(b["rect"], cr)]
                       + [(d, None) for d in drawings if d[1] >= top - 1 and xov(d, cr)], key=lambda x: x[0][1])
        cur = top
        for r, k in below:
            if r[1] - cur > GAP_TABLE or (k is not None and (k in cap_idx or anchor(blocks[k], cr[2] - cr[0]))):
                bottom = min(bottom, r[1])
                break
            cur = max(cur, r[3])
        rules = [d[3] for d in drawings if top - 1 <= cy(d) <= bottom and xov(d, cr) and d[3] - d[1] <= 2 and d[2] - d[0] >= 20]
        after = [r[1] for r, k in below if rules and k is not None and r[1] >= max(rules) - 1 and r[1] < bottom]
        if after and min(after) - max(rules) >= 8:
            bottom = max(rules) + 1
        ks, ds = band(blocks, drawings, skip | cap_idx, cr, top, bottom)
        above = False
        if not ds and all(blocks[k]["size"] >= BODY - 1 and not blocks[k]["img"] for k in ks):
            head = min(blocks[k]["rect"][1] for k in g["idx"])
            upper = max([b["rect"][3] for k, b in enumerate(blocks) if k not in skip and k not in cap_idx
                         and b["rect"][3] <= head + 1 and xov(b["rect"], cr) and anchor(b, cr[2] - cr[0])], default=0)
            ka, da = band(blocks, drawings, skip | cap_idx, cr, upper, head)
            if da or any(blocks[k]["size"] < BODY - 1 or blocks[k]["img"] for k in ka):
                ks, ds, above = ka, da, True
        rects = [blocks[k]["rect"] for k in ks] + [drawings[dk] for dk in ds]
        consumed.update(ks)
        dused.update(ds)
        tables.append({"g": g, "crop": union(rects) if rects else None, "bottom": top if above or not rects else max(r[3] for r in rects)})

    for g in caps:
        if g["kind"] != "fig":
            continue
        cr = g["rect"]
        band_bottom = cr[1]
        band_top = 0.0
        for t in tables:
            if t["bottom"] <= band_bottom + 1 and xov(t["g"]["rect"], cr):
                band_top = max(band_top, t["bottom"])
        for k, b in enumerate(blocks):
            if k not in skip and k not in consumed and not b["img"] and anchor(b) and stacked(b) and b["rect"][3] <= band_bottom + 1 and xov(b["rect"], cr):
                band_top = max(band_top, b["rect"][3])
        objs, used, dd = [], [], []
        for k, b in enumerate(blocks):
            if k in skip or k in consumed or k in cap_idx:
                continue
            if (b["img"] or b["size"] < BODY - 1) and xov(b["rect"], cr) and band_top - 1 <= cy(b["rect"]) <= band_bottom + 1:
                objs.append(b["rect"])
                used.append(k)
        for dk, d in enumerate(drawings):
            if dk not in dused and xov(d, cr) and band_top - 1 <= cy(d) <= band_bottom + 1:
                objs.append(d)
                dd.append(dk)
        if objs:
            box = union(objs)
            used += [k for k, b in enumerate(blocks) if k not in skip and k not in consumed and k not in cap_idx and k not in used
                     and inside(b["rect"], box) and band_top - 1 <= cy(b["rect"]) <= band_bottom + 1 and (b["img"] or not anchor(b) or not stacked(b))]
            consumed.update(used)
            dused.update(dd)
        figs.append({"g": g, "crop": union(objs) if objs else None})

    conts = {}
    prev = tab_end.get(pno - 1)
    if prev and prev[0] >= 0.8 * H:
        rules = [d for dk, d in enumerate(drawings) if dk not in dused and d[3] - d[1] <= 2 and d[2] - d[0] >= 0.3 * W and 0.1 * H < cy(d) < 0.9 * H]
        if rules:
            rw = max(d[2] for d in rules) - min(d[0] for d in rules)
            first = min((b["rect"][1] for k, b in enumerate(blocks) if k not in skip and k not in consumed and k not in cap_idx
                         and not b["img"] and not band_of(P, b) and prose(b, rw)), default=H)
            rules = [d for d in rules if cy(d) < first]
        if len(rules) >= 2:
            zone = union(rules)
            ks = [k for k, b in enumerate(blocks) if k not in skip and k not in consumed and k not in cap_idx and not b["img"]
                  and zone[1] - 1 <= cy(b["rect"]) <= zone[3] + 1 and xov(b["rect"], zone)]
            if ks and not ALGO_RE.match(blocks[min(ks)]["lines"][0]["text"]):
                conts[min(ks)] = (prev[1], union([zone] + [blocks[k]["rect"] for k in ks]))
                consumed.update(ks)
    ends = [(t["crop"][3], t["g"]["label"]) for t in tables if t["crop"]] + [(c[3], lab) for lab, c in conts.values()]
    if ends:
        tab_end[pno] = max(ends)

    rest = [(k, b["rect"]) for k, b in enumerate(blocks) if b["img"] and k not in consumed and k not in skip]
    fb = {min(m): r for m, r in cluster(rest, 12)}

    heads = {g["idx"][0]: g for g in caps}
    figs_by = {f["g"]["idx"][0]: f for f in figs}
    tabs_by = {t["g"]["idx"][0]: t for t in tables}
    zones = [t["crop"] for t in tables if t["crop"]] + [f["crop"] for f in figs if f["crop"]] + [c for _, c in conts.values()] + [a["box"] for a in algos.values()]
    eqs = equations(blocks, zones, consumed | skip | cap_idx)
    pchars = page_chars(pg) if (TEX or {}).get(pno) else []
    for e in (TEX or {}).get(pno, []):
        tr = tex_rect(e, pg)
        if any(inside(tr, z) for z in zones):
            saved["tex_drop"] += 1
            continue
        taken = {x for g in eqs for x in g["lines"]}
        lines = [(k, li) for k, b in enumerate(blocks) if k not in consumed | skip | cap_idx and not b["img"] and not b["rot"]
                 for li, l in enumerate(b["lines"]) if (k, li) not in taken
                 and any(not s["blank"] for s in l["spans"]) and all(inside(s["rect"], tr) for s in l["spans"] if not s["blank"])]
        g = max(eqs, key=lambda g: overlap(g["rect"], tr), default=None)
        m = re.search(r"\\tag\{([^}]*)\}", e["latex"])
        if not g or overlap(g["rect"], tr) < 0.5 * min(area(g["rect"]), area(tr)):
            if not lines or any(same_row(l["rect"], tr, 8) for b in blocks if not b["img"] for l in b["lines"]
                                if any(not s["blank"] and not inside(s["rect"], tr) for s in l["spans"])):
                saved["tex_drop"] += 1
                continue
            g = {"rect": None, "label": f"({m.group(1)})" if m else None, "lines": [], "tex": []}
            eqs.append(g)
        elif m and not g["label"]:
            g["label"] = f"({m.group(1)})"
        for o in [o for o in eqs if o is not g and o["label"] == g["label"] and not o.get("tex") and overlap(o["rect"], tr) >= 0.5 * area(o["rect"])]:
            g["rect"] = union([r for r in [g["rect"], o["rect"]] if r])
            g["lines"] = sorted(set(g["lines"]) | set(o["lines"]))
            eqs.remove(o)
        if lines:
            g["rect"] = union([r for r in [g["rect"]] if r] + [s["rect"] for k, li in lines for s in blocks[k]["lines"][li]["spans"] if not s["blank"]])
            g["lines"] = sorted(g["lines"] + lines)
        if tex_ok(pchars, tr, e["latex"]):
            g.setdefault("tex", []).append((tr[1], e["latex"]))
        else:
            saved["tex_bad"] += 1
            g["bad"] = True
    eq_head = {min(g["lines"]): (i, g) for i, g in enumerate(eqs, 1) if g["lines"]}
    eq_skip = {x for g in eqs for x in g["lines"]}
    rows = [l["rect"] for b in blocks if not b["img"] and not b["rot"] for l in b["lines"] if 0.1 * H <= cy(l["rect"]) <= 0.9 * H]
    free = [(k, li, l) for k, b in enumerate(blocks) if not b["img"] and not b["rot"] and k not in skip and k not in consumed and k not in cap_idx
            for li, l in enumerate(b["lines"]) if (k, li) not in eq_skip]
    num_head, num_skip = {}, set()
    for k, li, l in free:
        if not NUM_RE.match(l["text"]) or l["size"] < BODY or any(s["math"] for s in l["spans"] if not s["blank"]):
            continue
        right = [(m, mi, t) for m, mi, t in free if t["rect"][0] >= l["rect"][2] - 1 and same_row(l["rect"], t["rect"]) and (m, mi) not in num_head]
        if not right:
            continue
        m, mi, t = min(right, key=lambda x: x[2]["rect"][0])
        if (re.search(r"[A-Za-z]{3,}", t["text"]) and t["text"][:1].isupper() and not t["text"].endswith(",")
                and max(l["size"], t["size"]) < HS_MIN and spaced(rows, l["rect"], t["rect"])):
            num_head[(m, mi)] = ("h3" if "." in l["text"] else "h2", l["text"])
            num_skip.add((k, li))
    cont = set()
    out = []
    for k, b in enumerate(blocks):
        if k in algos:
            a = algos[k]
            out.append(("caption", a["title"]))
            link = save_crop(pg, pad(a["box"]), slug(a["label"]) + ".png", auto=True)
            saved["algo"] += 1
            if link and a["code"] and NOEQ:
                saved["algo_nolink"] += 1
            elif link:
                out.append(("img", f"![{a['label']}]({link})"))
            if a["code"]:
                out.append(("algo", a["code"]))
            continue
        if k in fb:
            link = save_crop(pg, pad(fb[k]), f"p{n:02d}-img{k}.png", auto=True)
            if link:
                out.append(("img", f"![第 {n} 頁]({link})"))
            continue
        if k in conts:
            label, crop = conts[k]
            name = f"{label} (continued)"
            out.append(("caption", name))
            link = save_crop(pg, pad(crop), slug(label) + "-cont.png", auto=True)
            md = table_md(pg, crop, drawings)
            if link and md and NOTAB:
                saved["tab_nolink"] += 1
            elif link:
                out.append(("img", f"![{name}]({link})"))
            if md:
                out.append(("table", md))
            continue
        if k in skip or k in consumed:
            continue
        if k in heads:
            g = heads[k]
            text = ""
            for m in g["idx"]:
                for l in blocks[m]["lines"]:
                    text = join(text, l["text"]) if text else l["text"]
            crop = figs_by[k]["crop"] if g["kind"] == "fig" else tabs_by[k]["crop"]
            r = pad(crop) if crop else None
            if r and g["kind"] == "table":
                cr = g["rect"]
                if crop[1] >= cr[3] - 1:
                    r = (r[0], max(r[1], cr[3]), r[2], r[3])
                elif crop[3] <= cr[1] + 1:
                    r = (r[0], r[1], r[2], min(r[3], cr[1]))
                elif cy(crop) > cy(cr):
                    r = (r[0], crop[1], r[2], r[3])
                else:
                    r = (r[0], r[1], r[2], crop[3])
            link = save_crop(pg, r, slug(g["label"]) + ".png", auto=True) if r else None
            md = table_md(pg, crop, drawings) if crop and g["kind"] == "table" else None
            if link and md and NOTAB:
                saved["tab_nolink"] += 1
                link = None
            seq = [("caption", text)]
            if link:
                img = ("img", f"![{g['label']}]({link})")
                seq = [img] + seq if g["kind"] == "fig" else seq + [img]
            if md:
                seq.append(("table", md))
            out += seq
            continue
        if b["img"] or k in cap_idx:
            continue
        where = band_of(P, b)
        last = not where and len(b["lines"]) == 1 and cy(b["rect"]) > 0.88 * H and not any(o is not b and not o["img"] and o["rect"][1] >= b["rect"][3] - 1 for o in blocks)
        for li, l in enumerate(b["lines"]):
            if (k, li) in eq_head:
                i, g = eq_head[(k, li)]
                alt = f"Eq. {g['label']}" if g["label"] else "Equation"
                er, r = g["rect"], pad(g["rect"])
                others = [o["rect"] for m, bb in enumerate(blocks) if not bb["img"] for mi, o in enumerate(bb["lines"]) if (m, mi) not in g["lines"] and xov(o["rect"], r)]
                r = (r[0], max([r[1]] + [min(o[3], er[1]) for o in others if cy(o) < er[1]]), r[2], min([r[3]] + [max(o[1], er[3]) for o in others if cy(o) > er[3]]))
                link = save_crop(pg, r, f"eq-p{n:02d}-{i}.png")
                tex = [] if g.get("bad") else sorted(g.get("tex", []))
                if link:
                    saved["eq"] += 1
                    if tex and NOEQ:
                        saved["eq_nolink"] += 1
                    else:
                        out.append(("img", f"![{alt}]({link})"))
                for _, t in tex:
                    saved["tex"] += 1
                    out.append(("tex", f"$$\n{tidy(t)}\n$$"))
            if (k, li) in eq_skip or (k, li) in num_skip or (k, li) in cont or (where and (key(l["text"]) in band_keys[where] or PAGE_NUM_RE.match(l["text"]) or DASH_RE.match(l["text"]))) or (last and l["text"].replace(" ", "") == str(n)):
                continue
            text = strip_targets(l["text"])
            if not text:
                continue
            mdt = l["md"] if l["md"] is not None and text == l["text"] else text
            if not mdt:
                continue
            head = None
            if (k, li) in num_head:
                kind, num = num_head[(k, li)]
                head = (kind, num + " " + text)
            elif BULLET_RE.match(text):
                out.append(("bullet", BULLET_RE.sub("", mdt, count=1)))
            elif b["size"] >= HS_MIN:
                out.append(("title", min(HSIZES.index(b["size"]), 2) + 1 if b["size"] in HSIZES else 3, text))
            elif (HEAD2_RE.match(text) and len(text) <= 60 and BODY <= l["size"] < HS_MIN
                  and (len(text.split()) > 1 or sum(c.isalpha() for c in text) >= 5) and spaced(rows, l["rect"], l["rect"]) and alone(rows, l["rect"])):
                head = ("h2", text)
            elif HEADN_RE.match(text) and l["bold"] and BODY - 0.5 <= l["size"] < HS_MIN and len(text) <= 100 and spaced(rows, l["rect"]):
                head = ("h3" if "." in text.split()[0].rstrip(".") else "h2", text)
            elif HEAD3_RE.match(text) and l["size"] >= BODY - 0.5 and len(text) <= 90 and not text.endswith(",") and spaced(rows, l["rect"]):
                head = ("h3", text)
            elif ((l["bold"] or BIB_RE.fullmatch("# " + text)) and BODY + 1.5 <= l["size"] < HS_MIN and len(b["lines"]) == 1 and len(text.split()) <= 5
                  and text[:1].isupper() and re.search(r"[A-Za-z]{3,}", text) and not text.endswith((".", ",")) and spaced(rows, l["rect"], l["rect"]) and alone(rows, l["rect"])):
                head = ("h2", text)
            else:
                foot = b["size"] < BODY - 1 and cy(b["rect"]) > 0.9 * H
                small = b["size"] < BODY - 1
                lead = next((sp for sp in l["spans"] if not sp["blank"]), None)
                out.append(("body", mdt, li == 0 or (small and REF_RE.match(text) is not None), small, foot, text, lead is not None and lead["katex"]))
            if head:
                for t in follow(free, l, cont):
                    head = (head[0], join(head[1], t))
                out.append(head)
    return out


def render(entries):
    out, cur, held, title, tail = [], None, [], None, None

    def flush():
        nonlocal cur, held, tail
        if cur is not None:
            tail = (len(out), len(held))
            out.append(cur)
        out.extend(held)
        cur, held = None, []

    def flush_title():
        nonlocal title
        if title:
            out.append("#" * title[0] + " " + " ".join(title[1]))
            title = None

    for e in entries:
        if e[0] == "title":
            if title and title[0] != e[1]:
                flush_title()
            if title is None:
                title = [e[1], []]
            title[1].append(e[2])
            continue
        flush_title()
        if e[0] == "body":
            text, new, small, foot, flat, kat = e[1], e[2], e[3], e[4], e[5], e[6]
            if foot and cur is not None and not TERM_RE.search(cur):
                if not new and held:
                    held[-1] = join(held[-1], text)
                else:
                    held.append(text)
                continue
            if cur is not None and (not new or (not TERM_RE.search(cur) and (flat[:1].islower() or kat or (small and len(flat) <= 12)))):
                cur = join(cur, text)
            else:
                flush()
                cur = text
            continue
        flush()
        if e[0] == "bullet":
            cur = "- " + e[1]
        elif e[0] == "h2":
            out.append("## " + e[1])
        elif e[0] == "h3":
            out.append("### " + e[1])
        else:
            out.append(e[1])
    flush_title()
    flush()
    first = entries[0][1:7] if entries and entries[0][0] == "body" else None
    return out, tail[0] if tail and len(out) == tail[0] + 1 + tail[1] else None, first


page_units, target = [], None
for pno, pg in enumerate(doc):
    units, tail_idx, first = render(process_page(pno, pg))
    page_units.append(units)
    if target and first and not TERM_RE.search(page_units[target[0]][target[1]]) and not re.search(r"https?://\S*$", page_units[target[0]][target[1]]) \
            and (first[4][:1].islower() or first[5] or (first[2] and len(first[4]) <= 12)):
        pi, ti = target
        page_units[pi][ti] = join(page_units[pi][ti], units[0])
        del units[0]
        target = target if tail_idx == 0 else (pno, tail_idx - 1) if tail_idx else None
    else:
        target = (pno, tail_idx) if tail_idx is not None else None
ref, cut = "保留", False
if NOREF:
    ref = "未找到"
    for units in page_units:
        kept = []
        for u in units:
            if re.match(r"#+ ", u):
                cut = bool(BIB_RE.fullmatch(u))
                kept.append(u)
                if cut:
                    kept.append("（參考文獻已省略）")
                    ref = "省略"
            elif not cut:
                kept.append(u)
        units[:] = kept
page_texts = ["\n\n".join([f"**第 {pno + 1} 頁**"] + units) for pno, units in enumerate(page_units)]
with open(md_path, "w", encoding="utf-8") as fh:
    fh.write("\n\n---\n\n".join(page_texts) + "\n")
print(f"{md_path}  pages={total}  body_size={BODY}pt  crops={saved['img']}  eq={saved['eq']}  tex={saved['tex'] if TEX is not None else '失敗'}  tex_drop={saved['tex_drop']}  tex_bad={saved['tex_bad']}  tex_fix={TEX_FIX}  tex_retry={TEX_RETRY}  ref={ref}  tab_nolink={saved['tab_nolink']}  eq_nolink={saved['eq_nolink']}  algo={saved['algo']}  algo_nolink={saved['algo_nolink']}  " + "  ".join(found))
