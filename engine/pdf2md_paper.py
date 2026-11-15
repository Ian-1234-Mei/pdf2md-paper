# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict

import pymupdf

from paper import ctx
from paper.inline_pdf import cmex_raw, inline_map, inline_md, katex_flow, scripts
from paper.mineru_run import load_tex, retry_tex
from paper.page import BIB_RE, BULLET_RE, TERM_RE, band_of, process_page, render
from paper.tables import split_at_rule
from paper.text import is_bold, join, key, norm, span_info


def main():
    NOREF = "--ref-wo" in sys.argv
    ctx.NOTAB = "--tab-wo" in sys.argv
    ctx.NOEQ = "--eq-wo" in sys.argv
    sys.argv = [a for a in sys.argv if a not in ("--ref-wo", "--tab-wo", "--eq-wo")]
    ctx.src, md_path, ctx.figdir = sys.argv[1:4]
    ctx.KEEP = sys.argv[4] if len(sys.argv) > 4 else None
    ctx.doc = pymupdf.open(ctx.src)
    ctx.total = len(ctx.doc)
    ctx.saved = Counter()
    ctx.tab_end = {}
    ctx.used_names = set()
    ctx.INLINE = defaultdict(list)
    ctx.TEX = load_tex()
    size_count, font_count, ctx.SYM_FONTS, math_count = Counter(), Counter(), set(), Counter()
    for pg in ctx.doc:
        for b in pg.get_text("dict", sort=False)["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    size_count[round(s["size"], 1)] += len(s["text"].strip())
                    font_count[s["font"]] += len(s["text"].strip())
                    math_count[s["font"]] += sum(unicodedata.category(c) == "Sm" or "\u0370" <= c <= "\u03ff" or "\U0001d400" <= c <= "\U0001d7ff" for c in s["text"] if not c.isspace())
                    if any((ord(c) < 32 and c not in "\t\n\r") or 0xE000 <= ord(c) <= 0xF8FF for c in s["text"]):
                        ctx.SYM_FONTS.add(s["font"])
    TEX_FIX, TEX_RETRY = retry_tex() if ctx.TEX else (0, 0)
    ctx.BODY =size_count.most_common(1)[0][0] if size_count else 12.0
    ctx.CM_BODY = bool(font_count) and font_count.most_common(1)[0][0].upper().startswith("CM")
    ctx.MATH_FONTS = {f for f in font_count if f != font_count.most_common(1)[0][0] and math_count[f] > 0.5 * font_count[f]}

    ctx.pages = []
    for pno, pg in enumerate(ctx.doc):
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
        ctx.pages.append({"W": W, "H": H, "blocks": blocks, "drawings": drawings, "chars": chars})

    ctx.VOCAB = Counter()
    for P in ctx.pages:
        for b in P["blocks"]:
            for l in b["lines"]:
                toks = re.findall(r"[A-Za-z]+", l["text"])
                if l["text"].endswith("-") and toks:
                    toks = toks[:-1]
                ctx.VOCAB.update(t.lower() for t in toks)

    ctx.HS_MIN = max(ctx.BODY + 3, ctx.BODY * 1.3)
    ctx.HSIZES = set()
    for P in ctx.pages:
        for b in P["blocks"]:
            if not b["img"] and not b["rot"] and b["size"] >= ctx.HS_MIN and not BULLET_RE.match(b["lines"][0]["text"]):
                ctx.HSIZES.add(b["size"])
    ctx.HSIZES = sorted(ctx.HSIZES, reverse=True)

    bands = {"header": defaultdict(list), "footer": defaultdict(list)}
    for pno, P in enumerate(ctx.pages):
        for b in P["blocks"]:
            where = None if b["img"] or b["rot"] else band_of(P, b)
            if where:
                bands[where][pno] += [l["text"] for l in b["lines"] if key(l["text"])]
    need = max(3, math.ceil(ctx.total / 2))
    pn = {pno: [(k, int(b["lines"][0]["text"].strip()) - (pno + 1)) for k, b in enumerate(P["blocks"]) if not b["img"] and not b["rot"] and len(b["lines"]) == 1 and re.fullmatch(r"\d{1,4}", b["lines"][0]["text"].strip()) and band_of(P, b)] for pno, P in enumerate(ctx.pages)}
    cnt = Counter(c for v in pn.values() for c in {c for _, c in v})
    PN_C = cnt.most_common(1)[0][0] if cnt and cnt.most_common(1)[0][1] >= need else None
    ctx.PNUM = {pno: {k for k, c in v if c == PN_C} for pno, v in pn.items()}
    ctx.targets, found = [], []
    ctx.band_keys = {"header": set(), "footer": set()}
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
        ctx.band_keys[where] = set(keys)
        if keys:
            ctx.targets.append("".join(keys))
            found.append(f"{label}: {' '.join(shown[k] for k in keys)}")

    page_units, target = [], None
    for pno, pg in enumerate(ctx.doc):
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
    print(f"{md_path}  pages={ctx.total}  body_size={ctx.BODY}pt  crops={ctx.saved['img']}  eq={ctx.saved['eq']}  tex={ctx.saved['tex'] if ctx.TEX is not None else '失敗'}  tex_drop={ctx.saved['tex_drop']}  tex_bad={ctx.saved['tex_bad']}  tex_fix={TEX_FIX}  tex_retry={TEX_RETRY}  ref={ref}  tab_nolink={ctx.saved['tab_nolink']}  eq_nolink={ctx.saved['eq_nolink']}  algo={ctx.saved['algo']}  algo_nolink={ctx.saved['algo_nolink']}  " + "  ".join(found))


if __name__ == "__main__":
    main()
