"""生成各种格式的测试书(都是合成文本,无版权问题)。供 test_ingest 等使用。"""
from __future__ import annotations

import random
import shutil
import subprocess
import zipfile
from pathlib import Path

CANARY = Path(__file__).resolve().parent.parent / "evals" / "canary" / "book.md"

EN_SENT = [
    "The committee observed that delays grew faster than demand did.",
    "In practice, the slack that managers remove is the slack that absorbs surprises.",
    "We should not confuse being busy with being fast, for the two often diverge.",
    "A reserve that nobody can find is not a reserve at all, merely a forgotten asset.",
    "Measurements taken over three winters suggest that the effect is real but modest.",
    "It would be a mistake to treat this rule of thumb as a law of nature.",
    "Several objections deserve a reply, and the first is that waiting is cheap.",
    "Where demand is steady and predictable, the argument loses most of its force.",
]


def en_paragraph(rng: random.Random, n: int = 5) -> str:
    return " ".join(rng.choice(EN_SENT) for _ in range(n))


def wrap(text: str, width: int = 70) -> str:
    out, line = [], ""
    for w in text.split():
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    out.append(line)
    return "\n".join(out)


def make_en_txt(path: Path, chapters: int = 6, paras: int = 7, running_header=True, seed: int = 1):
    """Gutenberg 风格:折行 70 列、空行分段、罗马数字章标题、页眉与页码。"""
    rng = random.Random(seed)
    roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
    L = ["THE PROJECT-LIKE LICENSE BLOCK", "", "ON SLACK AND SPEED", "", "by A. Nobody", "", "CONTENTS", ""]
    for i in range(chapters):
        L.append(f"  CHAPTER {roman[i]}. TITLE NUMBER {i + 1}")
    L += ["", ""]
    page = 1
    for i in range(chapters):
        L += ["", f"CHAPTER {roman[i]}.", f"TITLE NUMBER {i + 1}", ""]
        for _ in range(paras):
            L += wrap(en_paragraph(rng)).split("\n") + [""]
            if running_header and rng.random() < 0.5:
                L += ["ON SLACK AND SPEED", str(page), ""]
                page += 1
    path.write_text("\n".join(L), encoding="utf8")


def make_zh_txt(path: Path, parts: bool = True):
    """一行一段,有「第一部分」「第N章」标题。"""
    L = ["缓冲小史", "某某 著", ""]
    n = 0
    for p in range(2 if parts else 1):
        if parts:
            L.append(f"第{'一二'[p]}部分")
            L.append("两条路线")
        for c in range(3):
            n += 1
            L.append(f"第{'一二三四五六'[n - 1]}章")
            L.append(f"标题{n}")
            for k in range(5):
                L.append(f"这是第{n}章第{k + 1}段的内容,讲的是一个关于容量和延误的论断,它并不复杂,但需要足够长以便被当作正文而不是标题。")
    path.write_text("\n".join(L), encoding="utf8")


def make_md(path: Path):
    L = ["# 书名", ""]
    for c in range(1, 5):
        L += [f"# 第{c}章 题目{c}", "", f"## 小节{c}.1", "", "这是一段足够长的正文,用来测试 markdown 标题的章节切分是否正常工作,并保持段落。", "",
              f"## 小节{c}.2", "", "第二个小节的正文同样需要比较长一些,这样才不会被当作过短的章节并入相邻章节里去。", ""]
    path.write_text("\n".join(L), encoding="utf8")


def make_flat_epub(path: Path, chapters: int = 5):
    """v0.1 的老大难:整本在一个 HTML 里,章标题只是普通 <p>。"""
    ps = []
    for c in range(1, chapters + 1):
        ps.append(f"<p>第{'一二三四五六七八'[c - 1]}章 题目{c}</p>")
        for k in range(4):
            ps.append(f"<p>第{c}章的第{k + 1}段正文,足够长,用来模拟真实书里没有 h1 标签时的情形;内容并不重要,只要能被当作段落。</p>")
    body = "\n".join(ps)
    xhtml = f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body>{body}</body></html>'
    opf = '''<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>平铺的书</dc:title><dc:creator>某人</dc:creator><dc:identifier id="id">x</dc:identifier></metadata><manifest><item id="c" href="all.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>'''
    cont = '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", cont)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/all.xhtml", xhtml)


def make_canary_epub(path: Path):
    subprocess.run(["pandoc", str(CANARY), "-o", str(path), "--split-level=1"], check=True)


def make_pdf_from_en(txt: Path, pdf: Path) -> bool:
    """用 libreoffice 把 txt 转 pdf;没有就返回 False。"""
    if not shutil.which("libreoffice") and not shutil.which("soffice"):
        return False
    exe = shutil.which("libreoffice") or shutil.which("soffice")
    out = pdf.parent
    r = subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(out), str(txt)], capture_output=True, timeout=180)
    produced = out / (txt.stem + ".pdf")
    if produced.exists():
        if produced != pdf:
            produced.rename(pdf)
        return True
    return False


def make_big_zh(path: Path, chapters: int = 60, per: int = 40, seed: int = 3):
    """压力测试:~60 章,约 40 万汉字的合成文本。"""
    rng = random.Random(seed)
    bank = ["组织越忙交付越慢这件事并不反直觉", "容量被全部分配之后任何意外都只能靠挤占别的工作来消化", "反馈延迟让更多决策建立在错误判断之上",
            "可见性不对称使得缓冲的成本被高估而缺口的损失被低估", "需求的波动程度决定了应该预留多少余量", "没有被度量的东西往往会在优化中被牺牲"]
    L = []
    for c in range(1, chapters + 1):
        L.append(f"第{c}章 压力测试章节{c}")
        for k in range(per):
            L.append("".join(rng.choice(bank) + "," for _ in range(rng.randint(8, 14))) + "这是结尾。")
    path.write_text("\n".join(L), encoding="utf8")
