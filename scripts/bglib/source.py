"""把一本书(epub / txt / md / pdf / 章节目录)变成"按章、按段编号"的原文工作区。

产物(都在 <work>/source/,只供标注时阅读,绝不进入交付物):
    manifest.json   章节清单:id、标题、字数、段数、估算 token、分批阅读范围、是否建议跳过
    c01.txt …       每行一段:[c01-p001] 段落文字
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .textutil import cjk_ratio, est_tokens, nfkc

HEAD = "\x01"  # 标记"这一行来自 <h1>-<h3>"

_CN_N = "零〇一二三四五六七八九十百两\\d"
HEADING_PATTERNS = [
    re.compile(rf"^第\s*[{_CN_N}]+\s*[章讲课篇部卷](\s*$|[\s::、.·—-]+.{{0,40}}$)"),
    re.compile(r"^(自序|序言?|代序|推荐序|译者序|前言|引言|导言|导论|绪论|楔子|引子)([\s::——-].{0,40})?$"),
    re.compile(r"^(后记|结语|结论|尾声|终章|跋|致谢|附录|参考文献|注释|索引|译后记)([\s::——-]?.{0,40})?$"),
    re.compile(r"^(chapter|part|book|lecture)\s+([0-9]+|[ivxlc]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b.{0,60}$", re.I),
    re.compile(r"^(introduction|preface|foreword|prologue|epilogue|conclusions?|afterword|"
               r"acknowledge?ments?|appendix|notes|bibliography|references|index|"
               r"about the author)\b.{0,40}$", re.I),
    re.compile(r"^#{1,2}\s+\S.{0,80}$"),
]
SKIP_TITLE = re.compile(
    r"版权|出版说明|目\s*录|致\s*谢|鸣谢|索引|参考文献|参考书目|注\s*释|作者简介|关于作者|封面|扉页|书名页|"
    r"copyright|contents|acknowledge?ments?|index|bibliography|references|^notes$|about the author|"
    r"also by|title page|cover|dedication|praise for", re.I)


# ---------------------------------------------------------------- 读入
def _html_to_lines(raw: str) -> list[str]:
    raw = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<h([1-3])[^>]*>", "\n" + HEAD, raw, flags=re.I)
    raw = re.sub(r"<br\s*/?>|</p>|</div>|</h[1-6]>|</li>|</tr>|</blockquote>|<(?:p|div)\b[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = nfkc(html.unescape(raw)).replace(" ", " ")
    out = []
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and line != HEAD:
            out.append(line)
    return out


def _read_epub(path: Path):
    z = zipfile.ZipFile(path)
    container = ET.fromstring(z.read("META-INF/container.xml"))
    rootfile = next(e for e in container.iter() if e.tag.endswith("rootfile")).get("full-path")
    opf = ET.fromstring(z.read(rootfile))
    base = os.path.dirname(rootfile)
    full = lambda href: os.path.normpath(os.path.join(base, href.split("#")[0])).replace("\\", "/")

    def meta(tag):
        for e in opf.iter():
            if e.tag.endswith("}" + tag) and e.text:
                return e.text.strip()
        return ""

    items = {e.get("id"): e for e in opf.iter() if e.tag.endswith("}item")}
    docs = []  # [(path, lines)]
    for ref in (e for e in opf.iter() if e.tag.endswith("}itemref")):
        it = items.get(ref.get("idref"))
        if it is None or "html" not in (it.get("media-type") or "html"):
            continue
        p = full(it.get("href"))
        try:
            docs.append((p, _html_to_lines(z.read(p).decode("utf-8", "ignore"))))
        except KeyError:
            continue

    # 目录:[(depth, file, title)]
    toc: list[tuple[int, str, str]] = []
    ncx = next((i for i in items.values() if i.get("media-type") == "application/x-dtbncx+xml"), None)
    nav = next((i for i in items.values() if "nav" in (i.get("properties") or "").split()), None)
    if ncx is not None:
        try:
            root = ET.fromstring(z.read(full(ncx.get("href"))))
            ncx_base = os.path.dirname(full(ncx.get("href")))

            def walk(node, depth):
                for pt in node:
                    if not pt.tag.endswith("navPoint"):
                        continue
                    text = next((t.text for t in pt.iter() if t.tag.endswith("text") and t.text), "")
                    src = next((c.get("src") for c in pt if c.tag.endswith("content")), "")
                    if text and src:
                        f = os.path.normpath(os.path.join(ncx_base, src.split("#")[0])).replace("\\", "/")
                        toc.append((depth, f, nfkc(text).strip()))
                    walk(pt, depth + 1)
            navmap = next((e for e in root.iter() if e.tag.endswith("navMap")), None)
            if navmap is not None:
                walk(navmap, 1)
        except (KeyError, ET.ParseError):
            pass
    if not toc and nav is not None:
        try:
            raw = z.read(full(nav.get("href"))).decode("utf-8", "ignore")
            nav_base = os.path.dirname(full(nav.get("href")))
            depth = 0
            for m in re.finditer(r"<(/?)ol\b|<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", raw, flags=re.S | re.I):
                if m.group(0).lower().startswith("<ol"):
                    depth += 1
                elif m.group(0).lower().startswith("</ol"):
                    depth -= 1
                elif m.group(2):
                    title = nfkc(html.unescape(re.sub(r"<[^>]+>", "", m.group(3)))).strip()
                    f = os.path.normpath(os.path.join(nav_base, m.group(2).split("#")[0])).replace("\\", "/")
                    if title:
                        toc.append((max(depth, 1), f, title))
        except KeyError:
            pass
    return docs, toc, {"title": meta("title"), "author": meta("creator")}


def _txt_to_lines(text: str) -> list[str]:
    """纯文本 → 段落行。处理硬换行(Gutenberg / pdftotext 风格)。"""
    text = nfkc(text.replace("\r\n", "\n").replace("\r", "\n")).replace(" ", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)             # 英文行尾连字符
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    multi = sum(1 for b in blocks if b.strip().count("\n") >= 1)
    hard_wrapped = len(blocks) > 5 and multi / len(blocks) > 0.4
    out: list[str] = []
    for b in blocks:
        lines = [re.sub(r"\s+", " ", l).strip() for l in b.split("\n")]
        lines = [l for l in lines if l and not re.fullmatch(r"[-–—\s]*\d{1,4}[-–—\s]*", l)]  # 页码行
        if not lines:
            continue
        if not hard_wrapped:
            out.extend(lines)
            continue
        # 硬换行:块内首行若是标题则独立成行,其余合并成一段
        while lines and _is_heading(lines[0]):
            out.append(lines.pop(0))
        if lines:
            joined = lines[0]
            for l in lines[1:]:
                sep = "" if (cjk_ratio(joined[-1:]) or cjk_ratio(l[:1])) else " "
                joined += sep + l
            out.append(joined)
    return out


def _read_pdf(path: Path) -> list[str]:
    exe = shutil.which("pdftotext")
    if exe:
        text = subprocess.run([exe, "-enc", "UTF-8", str(path), "-"], capture_output=True, check=True).stdout.decode("utf-8", "ignore")
    else:
        try:
            import pypdf  # type: ignore
        except ImportError as e:
            raise SystemExit("读 PDF 需要 pdftotext(poppler-utils)或 pypdf;也可以先自行转成 txt 再运行。") from e
        text = "\n\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(str(path)).pages)
    text = text.replace("\f", "\n\n")
    if len(text.strip()) < 500:
        raise SystemExit("PDF 里几乎抽不出文字(可能是扫描版)。请先 OCR 成文本再运行。")
    return _txt_to_lines(text)


# ---------------------------------------------------------------- 分章
def _is_heading(line: str, extra: re.Pattern | None = None) -> bool:
    if line.startswith(HEAD):
        return True
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if extra is not None:
        return bool(extra.search(s))
    return any(p.match(s) for p in HEADING_PATTERNS)


def _clean_title(line: str) -> str:
    return re.sub(r"^#{1,6}\s+", "", line.lstrip(HEAD)).strip()


def _split_by_headings(lines: list[str], extra: re.Pattern | None, use_h_tags: bool) -> list[dict]:
    chapters = [{"title": "(开头部分)", "lines": []}]
    i = 0
    while i < len(lines):
        line = lines[i]
        tagged = line.startswith(HEAD)
        is_h = (tagged and use_h_tags) or (not tagged and _is_heading(line, extra)) \
            or (tagged and _is_heading(line.lstrip(HEAD), extra))
        if is_h:
            title = _clean_title(line)
            # "第三章" 单独一行、标题在下一行的情况
            if re.fullmatch(rf"(第\s*[{_CN_N}]+\s*[章讲课篇部卷]|(chapter|part)\s+\S+)", title, flags=re.I) \
                    and i + 1 < len(lines) and len(lines[i + 1].lstrip(HEAD)) <= 40 \
                    and not re.search(r"[。.!?!?]$", lines[i + 1]):
                title += " " + _clean_title(lines[i + 1])
                i += 1
            chapters.append({"title": title, "lines": []})
        else:
            chapters[-1]["lines"].append(line.lstrip(HEAD))
        i += 1
    return chapters


def _split_epub(docs, toc, by: str, toc_depth: int | None, extra):
    flat = [l for _, ls in docs for l in ls]
    h_tag_count = sum(1 for l in flat if l.startswith(HEAD))
    regex_count = sum(1 for l in flat if not l.startswith(HEAD) and _is_heading(l, extra))

    def by_toc():
        if not toc:
            return None
        depth = toc_depth
        if depth is None:
            depth = 1
            if sum(1 for d, _, _ in toc if d <= 1) < 5 and 5 <= sum(1 for d, _, _ in toc if d <= 2) <= 80:
                depth = 2
        entries = [(f, t) for d, f, t in toc if d <= depth]
        files = [p for p, _ in docs]
        starts: dict[tuple[int, int], str] = {}   # (doc_idx, line_idx) -> title
        from .textutil import norm
        for f, title in entries:
            if f not in files:
                continue
            di = files.index(f)
            pos = 0
            same_file = [t for ff, t in entries if ff == f]
            if len(same_file) > 1:       # 多个目录项指向同一文件:在文件内按标题文字定位
                nt = norm(title)
                hit = next((k for k, l in enumerate(docs[di][1]) if nt and norm(l) == nt), None)
                if hit is None:
                    hit = next((k for k, l in enumerate(docs[di][1]) if nt and len(l) < 80 and norm(l).startswith(nt)), None)
                if hit is None and same_file.index(title) > 0:
                    continue
                pos = hit or 0
            starts.setdefault((di, pos), title)
        if len(starts) < 3:
            return None
        chapters = [{"title": "(开头部分)", "lines": []}]
        for di, (_, ls) in enumerate(docs):
            for k, l in enumerate(ls):
                if (di, k) in starts:
                    chapters.append({"title": starts[(di, k)], "lines": []})
                    if norm(l) == norm(starts[(di, k)]):   # 标题行本身不算正文
                        continue
                chapters[-1]["lines"].append(l.lstrip(HEAD))
        return chapters

    def by_file():
        chs = []
        for p, ls in docs:
            if not ls:
                continue
            title = _clean_title(ls[0]) if (ls[0].startswith(HEAD) or len(ls[0]) <= 40) else Path(p).stem
            chs.append({"title": title, "lines": [l.lstrip(HEAD) for l in ls]})
        return chs

    if by == "toc":
        return by_toc() or by_file(), "toc"
    if by == "heading":
        return _split_by_headings(flat, extra, use_h_tags=h_tag_count >= 3 and regex_count < 3), "heading"
    if by == "file":
        return by_file(), "file"
    got = by_toc()
    if got and len(got) >= 4:
        return got, "toc"
    if regex_count >= 3 or h_tag_count >= 3:
        return _split_by_headings(flat, extra, use_h_tags=regex_count < 3), "heading"
    return by_file(), "file"


# ---------------------------------------------------------------- 主流程
def _split_long_para(p: str, limit: int = 1200) -> list[str]:
    if len(p) <= limit:
        return [p]
    sents = re.findall(r".+?(?:[。!?!?]+[”」』\"')）]*|\.(?=\s)|$)\s*", p, flags=re.S)
    out, cur = [], ""
    for s in sents:
        if cur and len(cur) + len(s) > limit:
            out.append(cur.strip())
            cur = ""
        cur += s
    if cur.strip():
        out.append(cur.strip())
    final = []
    for seg in out:                                   # 无标点的超长串:硬切
        final.extend(seg[i:i + limit] for i in range(0, len(seg), limit))
    return final


def prepare(src: str, work: str, by: str = "auto", toc_depth: int | None = None,
            heading_regex: str | None = None, min_chars: int = 150,
            part_tokens: int = 9000, title: str | None = None, author: str | None = None) -> dict:
    path = Path(src)
    extra = re.compile(heading_regex) if heading_regex else None
    meta = {"title": "", "author": ""}
    how = "heading"
    if path.is_dir():
        chapters = []
        for f in sorted(path.iterdir()):
            if f.suffix.lower() in (".txt", ".md"):
                ls = _txt_to_lines(f.read_text(encoding="utf-8", errors="ignore"))
                if ls:
                    t = _clean_title(ls[0]) if len(ls[0]) <= 60 else f.stem
                    chapters.append({"title": t, "lines": ls[1:] if len(ls[0]) <= 60 else ls})
        how = "file"
    elif path.suffix.lower() == ".epub":
        docs, toc, meta = _read_epub(path)
        chapters, how = _split_epub(docs, toc, by, toc_depth, extra)
    else:
        if path.suffix.lower() == ".pdf":
            lines = _read_pdf(path)
        else:
            lines = _txt_to_lines(path.read_text(encoding="utf-8", errors="ignore"))
        chapters = _split_by_headings(lines, extra, use_h_tags=False)

    # 过短的"章"(目录页里的标题行、空白分隔页)并入前一章
    merged: list[dict] = []
    for ch in chapters:
        size = sum(len(l) for l in ch["lines"])
        if merged and size < min_chars and not (ch is chapters[-1] and size > 80):
            prev = merged[-1]
            prev["lines"].extend(([ch["title"]] if ch["title"] != "(开头部分)" else []) + ch["lines"])
        elif size or merged:
            merged.append(ch)
    chapters = [c for c in merged if sum(len(l) for l in c["lines"]) > 0]

    out_dir = Path(work) / "source"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    all_text = "".join(l for c in chapters for l in c["lines"])
    lang = "zh" if cjk_ratio(all_text[:20000]) > 0.3 else "en"
    width = max(2, len(str(len(chapters))))
    man_ch = []
    for idx, ch in enumerate(chapters, 1):
        cid = f"c{idx:0{width}d}"
        paras = [seg for l in ch["lines"] for seg in _split_long_para(l)]
        pw = max(3, len(str(len(paras))))
        ids = [f"{cid}-p{k:0{pw}d}" for k in range(1, len(paras) + 1)]
        (out_dir / f"{cid}.txt").write_text(
            "".join(f"[{i}] {p}\n" for i, p in zip(ids, paras)), encoding="utf-8")
        # 分批:每批不超过 part_tokens
        parts, start, acc = [], 0, 0
        for k, p in enumerate(paras):
            t = est_tokens(p)
            if acc and acc + t > part_tokens:
                parts.append({"from": ids[start], "to": ids[k - 1], "lines": [start + 1, k], "tokens": acc})
                start, acc = k, 0
            acc += t
        if paras:
            parts.append({"from": ids[start], "to": ids[-1], "lines": [start + 1, len(paras)], "tokens": acc})
        chars = sum(len(p) for p in paras)
        skip_reason = ""
        if SKIP_TITLE.search(ch["title"]) and chars < 30000:
            skip_reason = "标题像版权/目录/致谢/索引等非正文"
        elif ch["title"] == "(开头部分)" and chars < 6000:
            skip_reason = "正文开始前的零散内容(封面/版权/目录)"
        man_ch.append({"id": cid, "title": ch["title"], "chars": chars, "paras": len(paras),
                       "tokens": sum(p["tokens"] for p in parts), "skip": bool(skip_reason),
                       "skip_reason": skip_reason, "parts": parts})
    manifest = {
        "title": title or meta.get("title") or path.stem,
        "author": author or meta.get("author") or "",
        "lang": lang, "split_by": how, "source_file": path.name,
        "chars": sum(c["chars"] for c in man_ch), "tokens": sum(c["tokens"] for c in man_ch),
        "chapters": man_ch,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (Path(work) / "notes").mkdir(exist_ok=True)
    return manifest


def split_warnings(man: dict) -> list[str]:
    """分章结果的可疑之处,提示执行者人工核对。"""
    chs = [c for c in man["chapters"] if not c["skip"]]
    w = []
    if len(chs) < 3:
        w.append(f"只切出 {len(chs)} 个正文章节——很可能没切对。试试 --by heading/file/toc、--toc-depth 2 或 --heading-regex。")
    if chs:
        big = max(chs, key=lambda c: c["chars"])
        if len(chs) >= 3 and big["chars"] > 0.45 * sum(c["chars"] for c in chs):
            w.append(f"{big['id']}《{big['title']}》占了全书 {big['chars'] * 100 // sum(c['chars'] for c in chs)}%,可能有多章被并在一起。")
        tiny = [c["id"] for c in chs if c["chars"] < 800]
        if tiny:
            w.append(f"这些章不足 800 字,确认是不是正文:{'、'.join(tiny)}(不是就 mark --skip)。")
    if len(man["chapters"]) > 60:
        w.append("章节数超过 60,可能切得太碎(小节被当成章)。试试 --toc-depth 1 或更严格的 --heading-regex。")
    return w


# ---------------------------------------------------------------- 读取工作区
class Source:
    def __init__(self, work: str | Path):
        self.work = Path(work)
        mp = self.work / "source" / "manifest.json"
        if not mp.exists():
            raise SystemExit(f"找不到 {mp};先运行 prepare。")
        self.manifest = json.loads(mp.read_text(encoding="utf-8"))
        self.chapters = {c["id"]: c for c in self.manifest["chapters"]}
        self._paras: dict[str, dict[str, str]] = {}

    def paras(self, cid: str) -> dict[str, str]:
        if cid not in self._paras:
            d = {}
            f = self.work / "source" / f"{cid}.txt"
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    m = re.match(r"\[([^\]]+)\] ?(.*)", line)
                    if m:
                        d[m.group(1)] = m.group(2)
            self._paras[cid] = d
        return self._paras[cid]

    def para(self, pid: str) -> str | None:
        cid = pid.split("-")[0]
        if cid not in self.chapters:
            return None
        return self.paras(cid).get(pid)

    def active(self) -> list[dict]:
        return [c for c in self.manifest["chapters"] if not c["skip"]]

    def save_manifest(self):
        (self.work / "source" / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=1), encoding="utf-8")
