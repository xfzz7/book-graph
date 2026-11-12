"""文本工具:归一化、语种判断、重叠度、疑似照抄检测。只用标准库。"""
from __future__ import annotations

import re
import unicodedata

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_KEEP = re.compile(r"[^\w]", re.UNICODE)  # 去掉标点和空白,保留字母数字/汉字/下划线
_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def norm(s: str) -> str:
    """归一化用于匹配:NFKC、小写、去掉一切标点和空白。"""
    s = unicodedata.normalize("NFKC", s).lower()
    return _KEEP.sub("", s).replace("_", "")


def cjk_ratio(s: str) -> float:
    letters = [c for c in s if c.isalnum()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _CJK.match(c)) / len(letters)


def detect_lang(s: str) -> str:
    """粗分:zh(汉字为主)/ en(其他,按拉丁文字处理)。"""
    return "zh" if cjk_ratio(s[:20000]) > 0.3 else "en"


def weight(s: str) -> int:
    """估算 token 量:汉字≈1.1,其他字符≈0.28。用于分块预算,不求精确。"""
    cjk = len(_CJK.findall(s))
    return int(cjk * 1.1 + (len(s) - cjk) * 0.28)


def ngrams(s: str, n: int = 2) -> set[str]:
    s = norm(s)
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def words_stems(s: str) -> set[str]:
    """拉丁文字用:小写词的前 5 个字母(粗略词干),长度≥3。"""
    s = unicodedata.normalize("NFKC", s).lower()
    return {w[:5] for w in re.findall(r"[a-z]{3,}", s)}


def overlap(claim: str, source: str) -> float:
    """claim 的内容被 source 覆盖的比例(0~1)。汉字用 2-gram,拉丁文字用词干。
    只在 claim 与 source 同语种时有意义。"""
    if cjk_ratio(claim) > 0.3:
        a = ngrams(claim, 2)
        b = ngrams(source, 2)
    else:
        a, b = words_stems(claim), words_stems(source)
    if not a:
        return 1.0
    return len(a & b) / len(a)


def numbers(s: str) -> set[str]:
    """提取阿拉伯数字串(去掉千分位逗号)。用于核对“数字是否真的出现在引用段落里”。"""
    s = unicodedata.normalize("NFKC", s)
    return {m.replace(",", "") for m in _NUM.findall(s)}


# ---- 疑似照抄 -------------------------------------------------------------

def copy_threshold(text: str) -> int:
    """归一化后连续相同多少字符算疑似照抄:汉字 16,拉丁文字 45(约 8 个词)。"""
    return 16 if cjk_ratio(text) > 0.3 else 45


class CopyIndex:
    """给一段原文(通常是一章)建 k-gram 集合,快速查询某段文字里是否有长公共片段。"""

    def __init__(self, source: str, k: int):
        self.k = k
        self.src = norm(source)
        self.grams = {self.src[i:i + k] for i in range(len(self.src) - k + 1)} if len(self.src) >= k else set()

    def longest_shared(self, s: str) -> int:
        """返回 s 与原文最长公共子串长度(仅当 ≥k 时精确,否则返回 0)。"""
        t = norm(s)
        k = self.k
        best = 0
        i = 0
        while i <= len(t) - k:
            if t[i:i + k] in self.grams:
                # 向右尽量延伸
                j = i + k
                while j < len(t) and (t[i:j + 1] in self.src):
                    j += 1
                best = max(best, j - i)
                i = j - k + 1 if j - k + 1 > i else i + 1
            else:
                i += 1
        return best


def clip(s: str, n: int = 60) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"
