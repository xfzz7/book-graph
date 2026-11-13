"""文本归一化、分词、数字抽取。所有"机器可验证"的检查都建立在这里。"""
from __future__ import annotations

import re
import unicodedata

CJK = r"㐀-䶿一-鿿豈-﫿぀-ヿ가-힯"
_CJK_RE = re.compile(f"[{CJK}]")
_TOKEN_RE = re.compile(f"[{CJK}]|[^\\W_]+", re.UNICODE)


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def norm(s: str) -> str:
    """去掉空白和标点、转小写,只留字母数字和文字。用于"原文片段是否真的出现在段落里"。"""
    return "".join(_TOKEN_RE.findall(nfkc(s).lower()))


def tokens(s: str) -> list[str]:
    """一个汉字 = 一个单位,一个拉丁单词/数字串 = 一个单位。"""
    return _TOKEN_RE.findall(nfkc(s).lower())


def cjk_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _CJK_RE.match(c)) / len(letters)


def est_tokens(s: str) -> int:
    """粗估 LLM token 数:汉字约 1.2/字,其余约 0.28/字符。只用于切分阅读批次。"""
    cjk = len(_CJK_RE.findall(s))
    return int(cjk * 1.2 + (len(s) - cjk) * 0.28)


def units(s: str) -> int:
    """长度单位数(汉字数 + 拉丁单词数),用于长度上限。"""
    return len(tokens(s))


def ngram_set(toks: list[str], n: int) -> set[int]:
    return {hash(tuple(toks[i:i + n])) for i in range(len(toks) - n + 1)}


def longest_shared_run(text: str, src_toks_set: set[int], n: int) -> tuple[int, str]:
    """text 与原文共享的最长连续片段(以单位计)。返回 (长度, 片段)。长度 < n 时返回 (0, '')。"""
    toks = tokens(text)
    best, best_at, i = 0, 0, 0
    while i <= len(toks) - n:
        if hash(tuple(toks[i:i + n])) in src_toks_set:
            j = i + 1
            while j <= len(toks) - n and hash(tuple(toks[j:j + n])) in src_toks_set:
                j += 1
            run = (j - 1 - i) + n
            if run > best:
                best, best_at = run, i
            i = j
        else:
            i += 1
    if not best:
        return 0, ""
    seg = toks[best_at:best_at + best]
    joined = "".join(seg) if _CJK_RE.match(seg[0]) else " ".join(seg)
    return best, joined


# ---------- 数字 ----------
_CN_D = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
         "六": 6, "七": 7, "八": 8, "九": 9}
_CN_U = {"十": 10, "百": 100, "千": 1000}
_CN_NUM = "零〇一二两三四五六七八九十百千万亿"
_CN_RE = re.compile(f"百分之([{_CN_NUM}点]+)|([{_CN_NUM}]+点[{_CN_NUM}]+|[{_CN_NUM}]{{2,}})")
_AR_RE = re.compile(r"(?<![\d.A-Za-z])(?<!\d,)(\d[\d,]*(?:\.\d+)?)(\s*[%％‰])?")


def cn_to_number(s: str) -> str | None:
    """中文数字 → 阿拉伯数字串。解析失败返回 None。"""
    if "点" in s:
        a, b = s.split("点", 1)
        ia = cn_to_number(a) if a else "0"
        if ia is None or not all(c in _CN_D for c in b):
            return None
        return ia + "." + "".join(str(_CN_D[c]) for c in b)
    if all(c in _CN_D for c in s):          # 二〇一九 → 2019
        return "".join(str(_CN_D[c]) for c in s)
    total = section = number = 0
    for c in s:
        if c in _CN_D:
            number = _CN_D[c]
        elif c in _CN_U:
            section += (number or 1) * _CN_U[c]
            number = 0
        elif c == "万":
            total += (section + number) * 10000
            section = number = 0
        elif c == "亿":
            total = (total + section + number) * 100000000
            section = number = 0
        else:
            return None
    return str(total + section + number)


def _canon(num: str) -> str:
    num = num.replace(",", "")
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return num.lstrip("0") or "0"


def numbers(s: str) -> set[str]:
    """抽取文本里"有信息量"的数字(阿拉伯数字 + 中文数字),统一成规范形式。
    百分数带 %。小于 10 的裸整数太常见(如"3 个步骤"),不计。"""
    s = nfkc(s)
    out: set[str] = set()
    for m in _AR_RE.finditer(s):
        n = _canon(m.group(1))
        pct = bool(m.group(2))
        if pct:
            out.add(n + "%")
        elif "." in n or len(n) >= 2:
            out.add(n)
    for m in _CN_RE.finditer(s):
        if m.group(1):
            n = cn_to_number(m.group(1))
            if n is not None:
                out.add(_canon(n) + "%")
        else:
            raw = m.group(2)
            n = cn_to_number(raw)
            if n is not None:
                n = _canon(n)
                if "." in n or len(n) >= 2:
                    out.add(n)
    return out


def number_forms(s: str) -> set[str]:
    """原文一侧的宽松集合:37% 同时算作出现了 37。"""
    ns = numbers(s)
    s = nfkc(s)
    for ch, v in (("十", "10"), ("百", "100"), ("千", "1000"), ("万", "10000")):
        if ch in s:                      # 单个"十/百/千/万":原文一侧从宽
            ns.add(v)
    return ns | {n[:-1] for n in ns if n.endswith("%")}
