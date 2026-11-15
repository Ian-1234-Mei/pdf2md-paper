# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from . import ctx
from .geom import inside, union, vov
from .inline_tex import IN_PUNCT, IN_STRUCT, IN_TAIL, in_unwrap, inline_fmt, inline_latex
from .texcheck import TEX_GREEK, in_letters, tex_rect
from .text import is_katex, norm

IN_ACCENT = re.compile(r"\\(?:overline|underline|widehat|widetilde|overrightarrow|hat|tilde|bar|vec|dot|ddot|breve|check|acute|grave)\b\s*")
ACCENT_GLYPHS = {"dot": "˙̇", "ddot": "¨̈", "hat": "ˆ^̂", "widehat": "ˆ^̂", "tilde": "˜~∼̃", "widetilde": "˜~∼̃", "bar": "¯̄̅", "overline": "¯̄̅", "underline": "", "vec": "→⃗", "overrightarrow": "→⃗", "breve": "˘̆", "check": "ˇ̌", "acute": "´́", "grave": "`̀"}
THIN_ACCENT = {"bar", "overline", "underline", "vec", "overrightarrow"}
PUA = 0xF0000


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
                big = big or (kind is not None and s["size"] >= 0.9 * ctx.BODY)
            pos += len(s["text"])
        if not big:
            break
    return kinds


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
    items = ctx.INLINE.get(pno)
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
