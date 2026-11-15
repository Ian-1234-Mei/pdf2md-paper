# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata
from collections import Counter

from .geom import cy, inside
from .text import join

ALGO_RE = re.compile(r"^(algorithm\s*(?:[A-Z]\.)?\d+)", re.I)
LINENO_RE = re.compile(r"^(\d+:)\s*")
ATOM_RE = re.compile(r"(?:((?<![A-Za-z])[A-Za-z]|[\u0370-\u03ff]|[∑∏]|\d+)?(′*)((?:<su[bp]>.*?</su[bp]>)+))+")


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
