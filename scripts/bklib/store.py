"""工作目录的读写。所有状态都在文件里——LLM 上下文被压缩/换人接手时,靠这些文件和 `bk status` 恢复。

work/
  source/            ingest 产物(meta.json, paras.jsonl, chapters/*.txt)   ← 含原文,不要交付/提交
  orient.json        第 0 步:全书定向(假设,待修正)
  notes/cNN.json     第 1 步:每章笔记(可拆成 cNN.2.json 等多份)
  synthesis.json     第 2 步:全书综合(论点、支柱、挂接、因果链、概念表、误读提醒)
  critique.json      第 3 步:审读(证据强弱、缺口、外部判断)
  questions.json     第 4 步:自测题
  audit/             第 5 步:独立核对(packets + verdicts.json)
  book.json          build 的合并结果
"""
from __future__ import annotations

import json
import re
from pathlib import Path


class Work:
    def __init__(self, root: str):
        self.root = Path(root)
        self.src = self.root / "source"
        self.notes_dir = self.root / "notes"
        self.audit_dir = self.root / "audit"
        self._paras = None
        self._meta = None
        self.load_errors: list[str] = []

    # ---- source
    @property
    def meta(self) -> dict:
        if self._meta is None:
            p = self.src / "meta.json"
            if not p.exists():
                raise SystemExit(f"找不到 {p};先运行: bk ingest <书文件> -w {self.root}")
            self._meta = json.loads(p.read_text(encoding="utf8"))
        return self._meta

    def save_meta(self):
        (self.src / "meta.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf8")

    @property
    def paras(self) -> dict[str, dict]:
        if self._paras is None:
            self._paras = {}
            with (self.src / "paras.jsonl").open(encoding="utf8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        self._paras[r["id"]] = r
        return self._paras

    def chapters(self, include_skipped: bool = False) -> list[dict]:
        return [c for c in self.meta["chapters"] if include_skipped or not c.get("skip")]

    def chapter(self, key: str) -> dict:
        for c in self.meta["chapters"]:
            if c["key"] == key:
                return c
        raise SystemExit(f"没有章 {key}。可用: " + ", ".join(c["key"] for c in self.meta["chapters"]))

    def ch_paras(self, key: str) -> list[dict]:
        return [p for p in self.paras.values() if p["ch"] == key]

    def ch_text(self, key: str) -> str:
        return "\n".join(p["text"] for p in self.ch_paras(key))

    def book_text(self) -> str:
        return "\n".join(p["text"] for p in self.paras.values())

    # ---- json helpers
    def read_json(self, rel: str, default=None):
        p = self.root / rel
        if not p.exists():
            return default
        try:
            return json.loads(p.read_text(encoding="utf8"))
        except json.JSONDecodeError as e:
            self.load_errors.append(f"{rel}: JSON 解析失败(第 {e.lineno} 行第 {e.colno} 列): {e.msg}")
            return default

    def write_json(self, rel: str, obj):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf8")

    # ---- notes
    def note_files(self, key: str) -> list[Path]:
        if not self.notes_dir.exists():
            return []
        return sorted(p for p in self.notes_dir.glob(f"{key}*.json") if re.fullmatch(rf"{key}(\..+)?\.json", p.name))

    def load_notes(self) -> dict[str, dict]:
        """合并每章的所有 part 文件。返回 {key: {meta, cards, concepts, links, files, meta_count}}。"""
        out: dict[str, dict] = {}
        for c in self.meta["chapters"]:
            key = c["key"]
            files = self.note_files(key)
            if not files:
                continue
            merged = {"meta": None, "cards": [], "concepts": [], "links": [], "files": [f.name for f in files], "meta_count": 0}
            for f in files:
                try:
                    d = json.loads(f.read_text(encoding="utf8"))
                except json.JSONDecodeError as e:
                    self.load_errors.append(f"notes/{f.name}: JSON 解析失败(第 {e.lineno} 行第 {e.colno} 列): {e.msg}")
                    continue
                if not isinstance(d, dict):
                    self.load_errors.append(f"notes/{f.name}: 顶层必须是对象")
                    continue
                if d.get("chapter") not in (None, key):
                    self.load_errors.append(f"notes/{f.name}: chapter 字段是 {d.get('chapter')!r},应为 {key!r}")
                if d.get("meta"):
                    merged["meta"] = d["meta"]
                    merged["meta_count"] += 1
                for fld in ("cards", "concepts", "links"):
                    v = d.get(fld, [])
                    if isinstance(v, list):
                        for it in v:
                            if isinstance(it, dict):
                                it.setdefault("_file", f.name)
                        merged[fld].extend(v)
                    else:
                        self.load_errors.append(f"notes/{f.name}: {fld} 必须是数组")
            out[key] = merged
        return out

    def next_card_id(self, key: str) -> str:
        n = 0
        for f in self.note_files(key):
            try:
                d = json.loads(f.read_text(encoding="utf8"))
            except Exception:
                continue
            for c in d.get("cards", []):
                m = re.fullmatch(rf"{key}\.k(\d+)", str(c.get("id", "")))
                if m:
                    n = max(n, int(m.group(1)))
        return f"{key}.k{n + 1}"
