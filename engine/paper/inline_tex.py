# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from .texcheck import greek, group_end, in_letters

IN_PUNCT = set("()[]\"“”'‘’.,;:!?")
IN_STRUCT = re.compile(r"[_^]|\\(?!(?:mathrm|mathbf|mathit|textrm|text|left|right)\b)[A-Za-z]+")
IN_TAIL = re.compile(r"\s*([,.;:]+)\s*$")
IN_STACK = re.compile(r"\\(?:frac|dfrac|tfrac|cfrac|over|atop|choose|binom|dbinom|tbinom|overset|underset|stackrel|substack|underbrace|overbrace|limits)(?![A-Za-z])|\\sqrt\s*\[")


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
