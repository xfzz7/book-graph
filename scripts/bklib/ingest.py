"""把 epub / txt / md / pdf 切成「章 → 段落」,给每个段落稳定的 id。只用标准库(pdf 需要系统有 pdftotext)。

输出(都在 work/source/ 下):
  meta.json         书名、作者、语种、章列表(键、标题、所属部、类型、是否跳过、字数)、警告
  paras.jsonl       每行一个段落 {id, ch, n, sec, text}。id 形如 c03:12(第 3 章第 12 段)
  chapters/c03.txt  给人/LLM 读的版本:每段前缀 [c03:12],小节标题单独成行

段落 id 一旦生成就不要重切——笔记里的 refs 都指向它们。
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

from .text import detect_lang, weight

# ---------------------------------------------------------------- 基础清洗

_COMPAT = re.compile(r"[⺀-⻿⼀-⿟豈-﫿　   ﻿]")


def clean(s: str) -> str:
    """只修正“长得像汉字但码位不对”的字符(康熙部首、兼容表意字),不动全角标点。"""
    def fix(m):
        c = m.group(0)
        if c in "　   ":
            return " "
        if c == "﻿":
            return ""
        return unicodedata.normalize("NFKC", c)
    s = _COMPAT.sub(fix, s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


# ---------------------------------------------------------------- 标题识别

CN_NUM = r"[零〇一二三四五六七八九十百千两\d]+"
RE_PART = re.compile(
    rf"^(第\s*{CN_NUM}\s*[部篇卷]|(part|book)\s+([ivxlcdm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b)", re.I)
RE_CHAPTER = re.compile(
    rf"^(第\s*{CN_NUM}\s*[章节回讲]|(chapter|lecture|essay)\s+([ivxlcdm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b|"
    r"[ivxlcdm]{1,6}\.\s+\S|\d{1,2}\.\s+[A-Z一-鿿])", re.I)
RE_SPECIAL = re.compile(
    r"^(序|序言|自序|前言|引言|导论|导言|绪论|楔子|序章|后记|跋|结语|结论|尾声|终章|致谢|附录|译者序|译后记|"
    r"preface|foreword|introduction|prologue|epilogue|conclusion|afterword|appendix|acknowledg(e)?ments?)"
    r"(\s|[:：、.．—\-]|$)", re.I)
RE_META = re.compile(
    r"(版权|copyright|图书在版|cip|isbn|目录|contents|table of contents|封面|cover|title page|扉页|书名页|出版说明|"
    r"also by|about the author|关于作者|作者简介|推荐语|编辑推荐|献词|dedication)", re.I)
RE_SKIPBACK = re.compile(r"^(index|bibliography|references|notes|endnotes|索引|参考文献|参考书目|注释|尾注|引文)\s*$", re.I)


def heading_kind(text: str) -> str | None:
    """返回 'part' / 'chapter' / 'special' / None。只认较短的行。"""
    t = text.strip()
    if not t or len(t) > 60:
        return None
    if RE_PART.match(t) and not RE_CHAPTER.match(t):
        return "part"
    if RE_CHAPTER.match(t):
        return "chapter"
    if RE_SPECIAL.match(t):
        return "special"
    return None


# ---------------------------------------------------------------- HTML → 块

class _Blocks(HTMLParser):
    BLOCK = {"p", "div", "li", "blockquote", "pre", "tr", "dd", "dt", "figcaption", "caption", "section", "article"}
    HEAD = {"h1", "h2", "h3", "h4", "h5", "h6"}
    SKIP = {"script", "style", "nav", "head", "title", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self.buf: list[str] = []
        self.cur = "p"
        self.skip = 0
        self.in_sup = 0
        self.title = ""
        self._in_title = False

    def _flush(self):
        text = clean("".join(self.buf).replace("\n", " "))
        self.buf = []
        if text:
            self.blocks.append((self.cur, text))
        self.cur = "p"

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag in self.HEAD:
            self._flush()
            self.cur = tag
        elif tag in self.BLOCK or tag == "br":
            self._flush()
        elif tag in ("sup", "sub"):
            self.in_sup += 1
        elif tag in ("td", "th"):
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in self.HEAD or tag in self.BLOCK:
            self._flush()
        elif tag in ("sup", "sub"):
            self.in_sup = max(0, self.in_sup - 1)
        elif tag in ("td", "th"):
            self.buf.append(" | ")

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_sup and re.fullmatch(r"[\s\d\[\]()*†‡,]+", data):
            return
        self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def html_blocks(raw: str) -> list[tuple[str, str]]:
    p = _Blocks()
    p.feed(raw)
    p.close()
    return p.blocks


# ---------------------------------------------------------------- 读取各格式

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"o": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
NCX_NS = {"n": "http://www.daisy.org/z3986/2005/ncx/"}


def read_epub(path: str) -> dict:
    z = zipfile.ZipFile(path)
    container = ET.fromstring(z.read("META-INF/container.xml"))
    rootfile = container.find(".//c:rootfile", CONTAINER_NS).get("full-path")
    opf = ET.fromstring(z.read(rootfile))
    base = os.path.dirname(rootfile)

    def meta(tag):
        node = opf.find(f".//dc:{tag}", OPF_NS)
        return (node.text or "").strip() if node is not None and node.text else ""

    manifest = {i.get("id"): i for i in opf.findall(".//o:manifest/o:item", OPF_NS)}
    docs = []
    toc_titles: dict[str, str] = {}
    # 目录标题(EPUB3 nav / EPUB2 ncx),仅用作回退时的章名
    for item in manifest.values():
        props = item.get("properties") or ""
        full = os.path.normpath(os.path.join(base, item.get("href"))).replace("\\", "/")
        try:
            if "nav" in props.split():
                raw = z.read(full).decode("utf-8", "ignore")
                for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", raw, flags=re.S | re.I):
                    t = clean(html.unescape(re.sub(r"<[^>]+>", "", m.group(2))))
                    if t:
                        toc_titles.setdefault(os.path.basename(m.group(1).split("#")[0]), t)
            elif item.get("media-type") == "application/x-dtbncx+xml":
                root = ET.fromstring(z.read(full))
                for pt in root.findall(".//n:navPoint", NCX_NS):
                    label = pt.find("n:navLabel/n:text", NCX_NS)
                    content = pt.find("n:content", NCX_NS)
                    if label is not None and content is not None and label.text:
                        toc_titles.setdefault(os.path.basename(content.get("src").split("#")[0]), clean(label.text))
        except (KeyError, ET.ParseError):
            pass
    for ref in opf.findall(".//o:spine/o:itemref", OPF_NS):
        item = manifest.get(ref.get("idref"))
        if item is None or item.get("media-type") not in (None, "application/xhtml+xml", "text/html"):
            continue
        if "nav" in (item.get("properties") or "").split():
            continue
        full = os.path.normpath(os.path.join(base, item.get("href"))).replace("\\", "/")
        try:
            raw = z.read(full).decode("utf-8", "ignore")
        except KeyError:
            continue
        blocks = html_blocks(raw)
        if blocks:
            docs.append({"file": os.path.basename(full), "blocks": blocks, "toc_title": toc_titles.get(os.path.basename(full), "")})
    return {"title": meta("title"), "author": meta("creator"), "docs": docs, "format": "epub"}


def _text_to_blocks(text: str, md: bool = False) -> list[tuple[str, str]]:
    """纯文本 → 块。有空行就按空行分段(段内折行接起来);没有空行就一行一段。"""
    text = clean(text)
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    has_blank = sum(1 for l in lines if not l.strip()) >= max(3, len(lines) // 12)
    para: list[str] = []

    def flush():
        if para:
            joined = _join_lines(para)
            if joined:
                blocks.append(("p", joined))
        para.clear()

    for line in lines:
        s = line.strip()
        if md:
            m = re.match(r"^(#{1,6})\s+(.*)$", s)
            if m:
                flush()
                blocks.append((f"h{len(m.group(1))}", m.group(2).strip()))
                continue
        if not s:
            flush()
            continue
        if has_blank:
            para.append(s)
        else:
            blocks.append(("p", s))
    flush()
    return blocks


def _join_lines(lines: list[str]) -> str:
    out = ""
    for l in lines:
        if not out:
            out = l
        elif re.search(r"[A-Za-z]-$", out) and re.match(r"^[a-z]", l):
            out = out[:-1] + l  # 断词连字符
        elif re.search(r"[㐀-鿿，。！？；：、”」』）]$", out) or re.match(r"^[㐀-鿿“「『（]", l):
            out += l
        else:
            out += " " + l
    return out.strip()


def read_pdf(path: str) -> dict:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("读取 PDF 需要系统命令 pdftotext(poppler-utils);或先自行转成 txt/epub。")
    out = subprocess.run([exe, "-enc", "UTF-8", path, "-"], capture_output=True, check=True).stdout.decode("utf-8", "ignore")
    pages = out.split("\f")
    # 页眉页脚:在多页中重复出现的短行
    from collections import Counter
    cnt: Counter = Counter()
    for pg in pages:
        ls = [l.strip() for l in pg.split("\n") if l.strip()]
        for l in set(ls[:3] + ls[-3:]):
            if len(l) <= 50:
                cnt[l] += 1
    thresh = max(4, len(pages) // 5)
    noise = {l for l, c in cnt.items() if c >= thresh}
    kept = []
    for pg in pages:
        for l in pg.split("\n"):
            s = l.strip()
            if s in noise or re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", s) or re.fullmatch(r"(page|第)\s*\d+\s*(页)?", s, re.I):
                continue
            kept.append(l)
        kept.append("")
    text = "\n".join(kept)
    blocks = _pdf_blocks(text)
    return {"title": "", "author": "", "docs": [{"file": os.path.basename(path), "blocks": blocks, "toc_title": ""}], "format": "pdf",
            "notes": [f"PDF 已去除 {len(noise)} 种疑似页眉页脚;版面还原是尽力而为,请核对章节切分与段落。"]}


def _pdf_blocks(text: str) -> list[tuple[str, str]]:
    lines = [l.rstrip() for l in text.split("\n")]
    has_blank = sum(1 for l in lines if not l.strip()) >= max(3, len(lines) // 15)
    if has_blank:
        return _text_to_blocks("\n".join(lines))
    # 无空行(常见于中文 PDF):按“行尾是句末标点且行明显短于最大行宽”判断段落结束
    widths = sorted(len(l) for l in lines if l.strip())
    mx = widths[int(len(widths) * 0.9)] if widths else 0
    blocks, cur = [], []
    for l in lines:
        s = l.strip()
        if not s:
            continue
        cur.append(s)
        if re.search(r"[。！？”」』.!?]$", s) and len(s) < mx * 0.85:
            blocks.append(("p", _join_lines(cur)))
            cur = []
    if cur:
        blocks.append(("p", _join_lines(cur)))
    return blocks


def read_any(path: str) -> dict:
    ext = Path(path).suffix.lower()
    if ext == ".epub":
        return read_epub(path)
    if ext == ".pdf":
        return read_pdf(path)
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "gb18030", "big5", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    else:
        text = raw.decode("utf-8", "ignore")
    blocks = _text_to_blocks(text, md=ext in (".md", ".markdown"))
    title = ""
    return {"title": title, "author": "", "docs": [{"file": Path(path).name, "blocks": blocks, "toc_title": ""}], "format": ext.lstrip(".") or "txt"}


# ---------------------------------------------------------------- 切章

def _drop_noise(flat: list[tuple[str, str, int]], warns: list[str]) -> list[tuple[str, str, int]]:
    """去掉纯页码行,以及整本里反复出现的短行(页眉)。标题块不动。保留文档序号。"""
    from collections import Counter
    cnt = Counter(t for k, t, _ in flat if k == "p" and len(t) <= 40)
    rep = {t for t, c in cnt.items() if c >= 5 and heading_kind(t) is None}
    out, dropped = [], 0
    for k, t, di in flat:
        if k == "p" and (re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", t) or t in rep):
            dropped += 1
            continue
        out.append((k, t, di))
    if dropped:
        warns.append(f"已丢弃 {dropped} 个疑似页码/页眉的短行(重复≥5 次或纯数字)。")
    return out


def split_chapters(src: dict, heading_regex: str | None = None, min_weight: int = 150) -> tuple[list[dict], list[str]]:
    """返回 (chapters, warnings)。chapter = {title, part, blocks:[(tag,text)]}。"""
    warns: list[str] = list(src.get("notes", []))
    custom = re.compile(heading_regex) if heading_regex else None

    # 1) 把所有文档的块摊平(带文档序号,回退方案要用),并去噪
    flat = [(k, t, di) for di, d in enumerate(src["docs"]) for k, t in d["blocks"]]
    flat = _drop_noise(flat, warns)
    blocks = [(k, t) for k, t, _ in flat]
    doc_of = [di for _, _, di in flat]

    def is_marker(idx: int, k: str, t: str, level: str | None) -> str | None:
        if custom:
            return "chapter" if custom.search(t) and len(t) <= 80 else None
        if level and k == level:
            return heading_kind(t) or "chapter"
        if level is None and k == "p":
            hk = heading_kind(t)
            # 正文里的短行才当作标题;以句号结尾的不算
            if hk and not re.search(r"[。.!?！？]$", t):
                return hk
        return None

    # 2) 选择标题层级:最浅的、数量在 [3, 120] 的 h 标签;否则退回行内正则
    counts = {lv: sum(1 for k, _ in blocks if k == lv) for lv in ("h1", "h2", "h3")}
    level = None
    if not custom:
        for lv in ("h1", "h2", "h3"):
            if 3 <= counts[lv] <= 120:
                level = lv
                break
        # 只有 1~2 个 h1 时(书名/扉页),但 h2 很多,上面已选 h2。若全无合适层级,level=None → 行内正则
    markers = [(i, is_marker(i, k, t, level)) for i, (k, t) in enumerate(blocks)]
    markers = [(i, m) for i, m in markers if m]

    chapters: list[dict] = []
    part = ""
    cur = None

    def start(title, kind, part_name):
        c = {"title": title, "part": part_name, "kind_hint": kind, "blocks": []}
        chapters.append(c)
        return c

    mset = dict(markers)
    n_ch = sum(1 for _, m in markers if m != "part")
    if n_ch >= 2:
        i = 0
        while i < len(blocks):
            k, t = blocks[i]
            m = mset.get(i)
            if m == "part":
                part = t
                # 部标题后紧跟的短行(部名副标题)并入部名
                if i + 1 < len(blocks) and blocks[i + 1][0] == "p" and len(blocks[i + 1][1]) <= 30 and (i + 1) not in mset:
                    part = f"{t} {blocks[i + 1][1]}"
                    i += 1
                cur = None
            elif m:
                title = t
                # 「第三章」单独一行,下一行是短标题:并入
                if i + 1 < len(blocks) and (i + 1) not in mset and blocks[i + 1][0] in ("p", "h2", "h3") \
                        and len(blocks[i + 1][1]) <= 30 and re.fullmatch(rf"第\s*{CN_NUM}\s*[章节回讲]|(chapter|part)\s+\w+\.?", t, re.I):
                    title = f"{t} {blocks[i + 1][1]}"
                    i += 1
                cur = start(title, m, part)
            else:
                if cur is None:
                    cur = start("前置内容", "front", part)
                cur["blocks"].append((k, t))
            i += 1
        # 低一级标题 → 小节(在 chapter blocks 里保留 h 标签即可)
    else:
        # 回退:一个文档一章(EPUB),标题取目录或首个短块
        warns.append("没有识别出足够的章标题,已回退为「一个文件一章」或按长度切分,请务必核对章列表。")
        if len(src["docs"]) >= 3 and src["format"] == "epub":
            by_doc: dict[int, list] = {}
            for (k, t), di in zip(blocks, doc_of):
                by_doc.setdefault(di, []).append((k, t))
            for di, bl in by_doc.items():
                d = src["docs"][di]
                head = next((t for k, t in bl[:3] if k.startswith("h") or len(t) <= 30), "")
                title = d["toc_title"] or head or d["file"]
                chapters.append({"title": title, "part": "", "kind_hint": "chapter", "blocks": [b for b in bl if b[1] != head or b[0] == "p"]})
        else:
            total = sum(weight(t) for _, t in blocks)
            target = 6000
            n = max(1, round(total / target))
            per = total / n
            acc, idx = 0, 1
            cur = start(f"第 {idx} 段(自动切分)", "chapter", "")
            for k, t in blocks:
                if acc >= per * idx and idx < n:
                    idx += 1
                    cur = start(f"第 {idx} 段(自动切分)", "chapter", "")
                cur["blocks"].append((k, t))
                acc += weight(t)
            warns.append("按长度自动切分只是权宜之计;若书有明确章节,请用 --heading-regex 指定标题正则后重跑。")

    # 3) 合并过短的章(并入下一章开头)
    merged: list[dict] = []
    carry: list = []
    book_title = re.sub(r"\W", "", src.get("title", ""))
    for c in chapters:
        w = sum(weight(t) for k, t in c["blocks"] if k == "p")
        if w < min_weight and c["kind_hint"] != "part" and not RE_META.search(c["title"]):
            if book_title and re.sub(r"\W", "", c["title"]) == book_title:
                warns.append("已丢弃书名页(只有书名/作者)。")
                continue
            carry.append((c["title"], c["blocks"]))
            warns.append(f"「{c['title']}」正文过短({w}),已并入相邻章节。")
            continue
        if carry:
            pre = []
            for tt, bl in carry:
                pre.append(("p", tt) if not bl else ("h2", tt))
                pre.extend(bl)
            c["blocks"] = pre + c["blocks"]
            carry = []
        merged.append(c)
    if carry and merged:
        for tt, bl in carry:
            merged[-1]["blocks"].append(("h2", tt))
            merged[-1]["blocks"].extend(bl)
    return merged, warns


def classify(title: str, kind_hint: str, body_weight: int) -> tuple[str, bool]:
    """返回 (kind, skip)。kind: body / front / back / meta"""
    t = title.strip()
    if RE_META.search(t) and body_weight < 1500:
        return "meta", True
    if RE_SKIPBACK.match(t):
        return "back", True
    if re.match(r"^(附录|appendix|后记|跋|afterword|致谢|acknowledg)", t, re.I):
        return "back", False
    if kind_hint == "front" or re.match(r"^(序|自序|序言|前言|引言|导论|preface|foreword|introduction|prologue)", t, re.I):
        return "front", False
    return "body", False


# ---------------------------------------------------------------- 落盘

def build_source(path: str, workdir: str, heading_regex: str | None = None, min_weight: int = 150) -> dict:
    src = read_any(path)
    chapters, warns = split_chapters(src, heading_regex, min_weight)
    if not chapters:
        raise RuntimeError("没有读到任何正文。")
    allt = "\n".join(t for c in chapters for k, t in c["blocks"] if k == "p")
    lang = detect_lang(allt)
    wd = Path(workdir) / "source"
    (wd / "chapters").mkdir(parents=True, exist_ok=True)
    # 清掉旧的 chapters/*.txt,避免残留
    for f in (wd / "chapters").glob("*.txt"):
        f.unlink()

    meta_ch = []
    para_rows = []
    for ci, c in enumerate(chapters, 1):
        key = f"c{ci:02d}"
        n = 0
        sec = ""
        lines = []
        weight_total = 0
        secs = []
        for k, t in c["blocks"]:
            if k != "p":
                # 章内低级标题 → 小节
                sec = t
                secs.append({"title": t, "first_para": n + 1})
                lines.append(f"\n## {t}")
                continue
            n += 1
            pid = f"{key}:{n}"
            para_rows.append({"id": pid, "ch": key, "n": n, "sec": sec, "text": t})
            lines.append(f"[{pid}] {t}")
            weight_total += weight(t)
        kind, skip = classify(c["title"], c["kind_hint"], weight_total)
        meta_ch.append({"key": key, "title": c["title"], "part": c["part"], "kind": kind, "skip": skip,
                        "n_paras": n, "chars": sum(len(r["text"]) for r in para_rows if r["ch"] == key),
                        "weight": weight_total, "sections": secs})
        (wd / "chapters" / f"{key}.txt").write_text(f"# {c['title']}\n" + "\n".join(lines) + "\n", encoding="utf8")
    with (wd / "paras.jsonl").open("w", encoding="utf8") as f:
        for r in para_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    meta = {"title": src["title"], "author": src["author"], "lang": lang, "format": src["format"],
            "source_file": os.path.basename(path), "chapters": meta_ch, "warnings": warns,
            "total_weight": sum(c["weight"] for c in meta_ch)}
    (wd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf8")
    return meta
