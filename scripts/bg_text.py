"""原书 → 带段落锚点的分章文本。只依赖标准库(PDF 需要 pypdf,可选)。

产出(都在工作目录 work/ 下,属于原书内容,不要交付、不要提交到仓库):
    work/source/c1.txt ...   每行一个段落,行首是锚点,如 "[c3.p12] 段落文字"
    work/manifest.json       书名、作者、语言、章表(id/标题/字数/段数/阅读分块)

设计要点:
- 段落锚点是整套流程的"坐标系":后面所有命题、概念、题目都必须引用锚点,
  校验脚本据此检查"有没有出处""出处里是否真有这回事""是否大段照抄"。
- 章切分优先用 EPUB 的 h1-h3 / Markdown 标题,其次用中英文标题行规则;
  "第X节"不切(节在章内),"第X篇/Part"记为篇名而不单独成章。
- 过长的章按字数切成阅读分块(chunk),保证 LLM 每次读入的原文有上限。
"""
from __future__ import annotations

import html
import json
import os
import re
import statistics
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

CN_NUM = "零〇一二三四五六七八九十百千两"
EN_NUM = r"(?:\d+|[IVXLC]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"

# (级别, 正则)。级别: part=篇, chap=章, front=序/前言, back=后记/结语, matter=注释/参考文献等
HEADING_RULES = [
    ("part", re.compile(rf"^第\s*[{CN_NUM}\d]+\s*[篇部卷](?:\s|[、:：.]|$)")),
    ("chap", re.compile(rf"^第\s*[{CN_NUM}\d]+\s*[章讲课](?:\s|[、:：.]|$)")),
    ("front", re.compile(r"^(自序|序言|序章|序|前言|引言|导言|导论|绪论|楔子|推荐序|译者序)(?:\s|[、:：]|$)")),
    ("back", re.compile(r"^(后记|结语|结论|尾声|终章|跋|附录)(?:\s|[A-Za-z0-9一二三四五六七八九十、:：]|$)")),
    ("matter", re.compile(r"^(注释|尾注|参考文献|参考书目|致谢|索引|版权信息|出版说明)\s*$")),
    ("part", re.compile(rf"^part\s+{EN_NUM}\b", re.I)),
    ("chap", re.compile(rf"^chapter\s+{EN_NUM}\b", re.I)),
    ("front", re.compile(r"^(preface|foreword|introduction|prologue)\b", re.I)),
    ("back", re.compile(r"^(epilogue|afterword|conclusion|appendix)\b", re.I)),
    ("matter", re.compile(r"^(notes|bibliography|references|acknowledg(e)?ments|index|copyright)\s*$", re.I)),
]
H_MARK = "\x00H"          # EPUB/Markdown 里明确的标题,前置此标记
SENT_END = "。!?!?…」』”\"'.;;"


def norm(s: str) -> str:
    # NFKC:把「⼀」这类康熙部首/全角兼容字符归一,否则「第一章」匹配不到
    s = unicodedata.normalize("NFKC", s)
    s = s.replace(" ", " ").replace("　", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def cjk_ratio(text: str) -> float:
    sample = text[:20000]
    cjk = sum(1 for ch in sample if "一" <= ch <= "鿿")
    letters = sum(1 for ch in sample if ch.isalpha())
    return cjk / letters if letters else 0.0


def classify_heading(line: str, custom: re.Pattern | None = None):
    s = line.strip()
    explicit = s.startswith(H_MARK)
    if explicit:
        s = s[len(H_MARK):].strip()
    if not s or len(s) > 60:
        return None
    if custom is not None:
        return ("chap", s) if custom.search(s) else None
    for level, pat in HEADING_RULES:
        if pat.match(s):
            return level, s
    if explicit:
        return "chap", s
    return None


# ---------- 读入各种格式,统一成"行"列表 ----------

def html_to_lines(raw: str) -> list[str]:
    raw = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    # 显式标题:h1-h3 标出来,让切分器优先采用
    raw = re.sub(r"<h[1-3][^>]*>(.*?)</h[1-3]>",
                 lambda m: "\n" + H_MARK + re.sub(r"<[^>]+>", "", m.group(1)) + "\n", raw, flags=re.S | re.I)
    raw = re.sub(r"<br\s*/?>|</p>|</div>|</h[4-6]>|</li>|</tr>|</blockquote>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = html.unescape(raw)
    return [norm(x) if not x.strip().startswith(H_MARK) else H_MARK + norm(x.strip()[len(H_MARK):])
            for x in raw.splitlines() if norm(x.replace(H_MARK, ""))]


def read_epub(path: str):
    z = zipfile.ZipFile(path)
    ns_c = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    ns_o = {"o": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
    rootfile = ET.fromstring(z.read("META-INF/container.xml")).find(".//c:rootfile", ns_c).get("full-path")
    opf = ET.fromstring(z.read(rootfile))
    base = os.path.dirname(rootfile)

    def meta(tag):
        node = opf.find(f".//dc:{tag}", ns_o)
        return norm(node.text) if node is not None and node.text else ""

    manifest = {i.get("id"): i for i in opf.findall(".//o:manifest/o:item", ns_o)}
    lines: list[str] = []
    for ref in opf.findall(".//o:spine/o:itemref", ns_o):
        item = manifest.get(ref.get("idref"))
        if item is None or "nav" in (item.get("properties") or ""):
            continue
        if item.get("media-type") not in (None, "application/xhtml+xml", "text/html"):
            continue
        full = os.path.normpath(os.path.join(base, item.get("href"))).replace("\\", "/")
        try:
            doc = html_to_lines(z.read(full).decode("utf-8", "ignore"))
        except KeyError:
            continue
        if looks_like_toc(doc):
            continue
        lines.extend(doc)
    return lines, meta("title"), meta("creator")


def looks_like_toc(lines: list[str]) -> bool:
    if not lines:
        return True
    heads = sum(1 for x in lines if classify_heading(x))
    total = sum(len(x) for x in lines)
    return heads >= 3 and total < 150 * heads


def read_pdf(path: str) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise SystemExit("读取 PDF 需要 pypdf(pip install pypdf),或先自行转成 txt。") from e
    raw_lines = []
    for page in PdfReader(path).pages:
        for x in (page.extract_text() or "").splitlines():
            x = norm(x)
            if x and not re.fullmatch(r"[\d\s\-—–·/]+|第?\s*\d+\s*页", x):  # 去掉纯页码行
                raw_lines.append(x)
    return reflow(raw_lines)


def reflow(lines: list[str]) -> list[str]:
    """PDF 每行是排版行,不是段落:按"句末标点 + 明显短行"重新拼段。"""
    if not lines:
        return []
    width = statistics.median(len(x) for x in lines)
    out, buf = [], ""
    for x in lines:
        if classify_heading(x):
            if buf:
                out.append(buf)
                buf = ""
            out.append(x)
            continue
        sep = " " if buf and buf[-1].isascii() and x[:1].isascii() else ""
        buf = buf + sep + x
        if x[-1:] in SENT_END and len(x) < 0.9 * width:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def read_plain(path: str) -> list[str]:
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = []
    md = path.lower().endswith((".md", ".markdown"))
    for x in raw.splitlines():
        if md and re.match(r"^#{1,3}\s+\S", x):
            lines.append(H_MARK + norm(x.lstrip("#")))
            continue
        x = norm(x)
        if x:
            lines.append(x)
    return lines


# ---------- 切章、切段、切块 ----------

def split_long(par: str, limit: int = 900) -> list[str]:
    """超长段落按句子切开,保证锚点足够精确。"""
    if len(par) <= limit:
        return [par]
    sents = re.findall(r".+?(?:[。!?!?]+[」』”\"']?|\.(?=\s)|$)", par)
    out, buf = [], ""
    for s in sents:
        if buf and len(buf) + len(s) > limit * 0.7:
            out.append(buf.strip())
            buf = ""
        buf += s
    if buf.strip():
        out.append(buf.strip())
    return out or [par]


def split_chapters(lines: list[str], custom: re.Pattern | None, min_chars: int):
    """返回 [{title, kind, part, paras}];标题前的文字记为 front matter。"""
    chapters, part = [], ""
    cur = {"title": "开篇(标题之前的文字)", "kind": "pre", "part": "", "paras": []}
    for x in lines:
        h = classify_heading(x, custom)
        if not h:
            cur["paras"].append(x.replace(H_MARK, ""))
            continue
        level, title = h
        if level == "part":
            part = title
            # 篇名本身不成章;若篇首有导语,导语会进入"篇首"小章,稍后按长度决定去留
        chapters.append(cur)
        cur = {"title": title, "kind": level, "part": part, "paras": []}
    chapters.append(cur)

    # 只有一个"开篇":说明没找到标题,整本作为一章
    real = [c for c in chapters if sum(len(p) for p in c["paras"]) >= min_chars]
    merged = []
    for c in chapters:
        size = sum(len(p) for p in c["paras"])
        if size >= min_chars:
            merged.append(c)
        elif merged and c["paras"]:
            # 很短的块(如篇首导语、目录残片)并入前一章末尾,避免丢字
            merged[-1]["paras"].extend(c["paras"])
    if not real:
        merged = [{"title": "全文", "kind": "chap", "part": "", "paras": [p for c in chapters for p in c["paras"]]}]
    return merged


def prepare(src: str, out: str, chunk_chars: int = 6000, min_chars: int = 200,
            heading_regex: str | None = None, title: str | None = None, author: str | None = None) -> dict:
    ext = src.lower().rsplit(".", 1)[-1]
    meta_title, meta_author = "", ""
    if ext == "epub":
        lines, meta_title, meta_author = read_epub(src)
    elif ext == "pdf":
        lines = read_pdf(src)
    elif ext in ("html", "htm", "xhtml"):
        lines = html_to_lines(Path(src).read_text(encoding="utf-8", errors="replace"))
    else:
        lines = read_plain(src)
    if not lines:
        raise SystemExit("没有读到任何文字。扫描版 PDF 需要先 OCR。")

    # txt 常见:第一行书名、第二行作者
    if not meta_title and ext not in ("epub",) and lines and not classify_heading(lines[0]) and len(lines[0]) < 60:
        meta_title = lines[0].replace(H_MARK, "")
        if len(lines) > 1 and re.search(r"(著|编著|编|译|^by\s)", lines[1].strip(), re.I) and len(lines[1]) < 40:
            meta_author = re.sub(r"\s*(著|编著|编)$|^by\s+", "", lines[1].strip(), flags=re.I)
    custom = re.compile(heading_regex) if heading_regex else None
    chapters = split_chapters(lines, custom, min_chars)

    outp = Path(out)
    (outp / "source").mkdir(parents=True, exist_ok=True)
    for f in (outp / "source").glob("c*.txt"):
        f.unlink()
    man_ch = []
    full_text = []
    for i, c in enumerate(chapters, 1):
        cid = f"c{i}"
        paras = [q for p in c["paras"] for q in split_long(p)]
        rows = [f"[{cid}.p{j}] {p}" for j, p in enumerate(paras, 1)]
        (outp / "source" / f"{cid}.txt").write_text(f"# {cid} {c['title']}\n" + "\n".join(rows) + "\n", encoding="utf-8")
        # 分块:按段累加到 chunk_chars
        chunks, start, acc = [], 1, 0
        for j, p in enumerate(paras, 1):
            acc += len(p)
            if acc >= chunk_chars and j < len(paras):
                chunks.append([start, j])
                start, acc = j + 1, 0
        chunks.append([start, len(paras)])
        chars = sum(len(p) for p in paras)
        full_text.append("".join(paras))
        man_ch.append({
            "id": cid, "title": c["title"], "kind": c["kind"], "part": c["part"],
            "file": f"source/{cid}.txt", "chars": chars, "paras": len(paras),
            "chunks": [f"p{a}-p{b}" for a, b in chunks],
            "skip_hint": c["kind"] == "matter",
        })
    text = "".join(full_text)
    manifest = {
        "title": title or meta_title or Path(src).stem,
        "author": author or re.sub(r"\s*(著|编著|编|主编)$", "", meta_author or ""),
        "source_file": os.path.basename(src),
        "lang": "zh" if cjk_ratio(text) > 0.3 else "en",
        "total_chars": len(text),
        "chunk_chars": chunk_chars,
        "chapters": man_ch,
    }
    (outp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_source(work: str) -> dict[str, dict[str, str]]:
    """返回 {chapter_id: {anchor: text}},锚点形如 c3.p12。"""
    out = {}
    for f in sorted(Path(work, "source").glob("c*.txt")):
        cid = f.stem
        paras = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\[(c\d+\.p\d+)\] (.*)$", line)
            if m:
                paras[m.group(1)] = m.group(2)
        out[cid] = paras
    return out
