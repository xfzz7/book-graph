#!/usr/bin/env python3
"""EPUB → 按章纯文本。只依赖标准库。

用法:
    python scripts/extract_epub.py book.epub -o work/text

输出:
    work/text/000_序.txt ...           每章一个 txt
    work/text/chapters.json            章键、标题、文件名、字数

为什么需要它:
    EPUB 里章节不一定有 <h1>,很多书把整本压成几个大 HTML 块,
    章标题只是正文里单独一行。本脚本先按标题行切,切不出来再退回「一文件一章」。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"o": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

PATTERNS = [
    ("chapter", re.compile(r"^第\s*([零〇一二三四五六七八九十百两\d]+)\s*([章节回卷])\s*[、,，.。:：]?\s*(.*)$")),
    ("preface", re.compile(r"^(自序|序言|序章|前言|引言|楔子)\s*[、,，.。:：]?\s*(.*)$")),
    ("afterword", re.compile(r"^(后记|结语|尾声|终章)\s*[、,，.。:：]?\s*(.*)$")),
    ("appendix", re.compile(r"^(附录)\s*([A-Za-z0-9一二三四五六七八九十]?)\s*[、,，.。:：]?\s*(.*)$")),
]


def cn_to_int(s: str) -> int:
    if s.isdigit():
        return int(s)
    total = 0
    number = 0
    for ch in s:
        if ch in CN_DIGIT:
            number = CN_DIGIT[ch]
        elif ch == "十":
            total += (number or 1) * 10
            number = 0
        elif ch == "百":
            total += (number or 1) * 100
            number = 0
    return total + number


def match_heading(line: str):
    """返回 (kind, key, title, has_rest) 或 None。只认足够短的行,避免把正文句子当标题。"""
    s = line.strip()
    if not s or len(s) > 50:
        return None
    for kind, pat in PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        if kind == "chapter":
            return kind, str(cn_to_int(m.group(1))), s, bool((m.group(3) or "").strip())
        if kind == "preface":
            return kind, "序", s, bool((m.group(2) or "").strip())
        if kind == "afterword":
            return kind, "后", s, bool((m.group(2) or "").strip())
        if kind == "appendix":
            return kind, ("附录" + m.group(2)).strip(), s, bool((m.group(3) or "").strip())
    return None


def html_to_text(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<br\s*/?>|</p>|</div>|</h[1-6]>|</li>|</tr>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    # NFKC:把「⼀」这类康熙部首/兼容字符归一成正常汉字,否则「第一章」匹配不到
    raw = unicodedata.normalize("NFKC", raw)
    raw = raw.replace("\u00a0", " ").replace("\u3000", " ")
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def open_epub(path: str):
    z = zipfile.ZipFile(path)
    container = ET.fromstring(z.read("META-INF/container.xml"))
    rootfile = container.find(".//c:rootfile", CONTAINER_NS).get("full-path")
    opf = ET.fromstring(z.read(rootfile))
    base = os.path.dirname(rootfile)

    def meta(tag):
        node = opf.find(f".//dc:{tag}", OPF_NS)
        return (node.text or "").strip() if node is not None and node.text else ""

    manifest = {}
    for item in opf.findall(".//o:manifest/o:item", OPF_NS):
        manifest[item.get("id")] = item
    spine = []
    for ref in opf.findall(".//o:spine/o:itemref", OPF_NS):
        item = manifest.get(ref.get("idref"))
        if item is None or item.get("media-type") not in (None, "application/xhtml+xml", "text/html"):
            continue
        href = item.get("href")
        full = os.path.normpath(os.path.join(base, href)).replace("\\", "/")
        spine.append((item, full))
    return z, opf, base, manifest, spine, {"title": meta("title"), "author": meta("creator")}


def toc_titles(z, opf, base, manifest):
    """尽力从 EPUB3 nav 或 EPUB2 NCX 拿目录标题。返回 [(href, title)]。"""
    entries = []
    nav_item = None
    for item in manifest.values():
        if "nav" in (item.get("properties") or ""):
            nav_item = item
            break
    if nav_item:
        href = nav_item.get("href")
        full = os.path.normpath(os.path.join(base, href)).replace("\\", "/")
        try:
            raw = z.read(full).decode("utf-8", "ignore")
            for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", raw, flags=re.S | re.I):
                text = re.sub(r"<[^>]+>", "", m.group(2))
                text = html.unescape(text).strip()
                if text:
                    entries.append((m.group(1), text))
        except KeyError:
            pass
    if entries:
        return entries
    ncx = next((i for i in manifest.values()
                if i.get("media-type") == "application/x-dtbncx+xml"), None)
    if ncx:
        full = os.path.normpath(os.path.join(base, ncx.get("href"))).replace("\\", "/")
        try:
            root = ET.fromstring(z.read(full))
            for point in root.findall(".//n:navPoint", NCX_NS):
                label = point.find("n:navLabel/n:text", NCX_NS)
                content = point.find("n:content", NCX_NS)
                if label is not None and content is not None:
                    entries.append((content.get("src"), (label.text or "").strip()))
        except (KeyError, ET.ParseError):
            pass
    return entries


def looks_like_toc(text: str) -> bool:
    lines = text.splitlines()
    heads = sum(1 for line in lines if match_heading(line))
    return heads >= 3 and len(text) < 2500


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()[:40] or "part"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="EPUB → 按章纯文本")
    ap.add_argument("epub")
    ap.add_argument("-o", "--out", default="work/text")
    ap.add_argument("--min-chars", type=int, default=50, help="短于此长度的章会并入下一章")
    a = ap.parse_args(argv)

    z, opf, base, manifest, spine, meta = open_epub(a.epub)
    os.makedirs(a.out, exist_ok=True)

    docs = []
    for item, full in spine:
        raw = z.read(full).decode("utf-8", "ignore")
        text = html_to_text(raw)
        if not text or looks_like_toc(text):
            continue
        docs.append(text)

    # 方案 A:按标题行切
    chapters = []
    for text in docs:
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            hit = match_heading(lines[i])
            if not hit:
                if chapters:
                    chapters[-1]["lines"].append(lines[i])
                elif lines[i]:
                    chapters.append({"key": "front", "title": "扉页 / 版权", "lines": [lines[i]]})
                i += 1
                continue
            kind, key, title, has_rest = hit
            # 标题行只有「第三章」时,把下一行短标题并进来
            if not has_rest:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and len(lines[j]) <= 30 and not match_heading(lines[j]):
                    title = (title + " " + lines[j]).strip()
                    i = j
            if chapters and chapters[-1]["key"] == key and chapters[-1]["title"] == title:
                i += 1
                continue
            chapters.append({"key": key, "title": title, "lines": []})
            i += 1

    # 方案 B:切不出来,一文件一章(标题尽量取目录)
    if len([c for c in chapters if c["key"] != "front"]) < 2:
        chapters = []
        names = {}
        for href, title in toc_titles(z, opf, base, manifest):
            names[os.path.basename(href.split("#")[0])] = title
        for idx, (item, full) in enumerate(spine):
            raw = z.read(full).decode("utf-8", "ignore")
            text = html_to_text(raw)
            if not text or looks_like_toc(text):
                continue
            title = names.get(os.path.basename(full)) or (text.splitlines()[0][:40] if text else f"part{idx}")
            chapters.append({"key": str(len(chapters) + 1), "title": title, "lines": text.splitlines()})

    # 合并过短的章
    merged = []
    for c in chapters:
        body = "\n".join(c["lines"]).strip()
        if len(body) < a.min_chars and merged and c["key"] != "front":
            merged[-1]["lines"].extend(c["lines"])
            merged[-1]["title"] += " / " + c["title"]
            continue
        merged.append({"key": c["key"], "title": c["title"], "lines": c["lines"]})
    chapters = merged

    manifest_out = {"book": meta["title"], "author": meta["author"], "source": os.path.basename(a.epub), "chapters": []}
    print(f"{meta['title']} / {meta['author']}")
    print(f"{'key':<6}{'chars':>8}  file  title")
    for idx, c in enumerate(chapters):
        body = "\n".join(c["lines"]).strip()
        fname = f"{idx:03d}_{safe_name(c['key'])}_{safe_name(c['title'])}.txt"
        with open(os.path.join(a.out, fname), "w", encoding="utf8") as f:
            f.write(body + "\n")
        manifest_out["chapters"].append({"key": c["key"], "title": c["title"], "file": fname, "chars": len(body)})
        print(f"{c['key']:<6}{len(body):>8}  {fname}  {c['title']}")

    with open(os.path.join(a.out, "chapters.json"), "w", encoding="utf8") as f:
        json.dump(manifest_out, f, ensure_ascii=False, indent=2)
    print(f"\n共 {len(chapters)} 章 → {a.out}\\chapters.json")
    if len(chapters) == 1:
        print("提示:只切出 1 章,可能整本在一个文件里;请人工检查后按章复制拆分。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
