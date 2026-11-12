#!/usr/bin/env python3
"""book.json → 两个自包含 HTML(总览导图 / 关系网),并给出图论报告。

用法:
    python scripts/build_pages.py book.json -o dist
    python scripts/build_pages.py book.json --report
    python scripts/build_pages.py book.json --report --json

依赖: networkx (pip install networkx)
模板: ../assets/templates/{overview,network}.html
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from validate_book import validate

ROOT = Path(__file__).resolve().parent.parent
TPL_DIR = ROOT / "assets" / "templates"
_DATA = re.compile(r"/\*DATA\*/.*?/\*END\*/", re.S)


def analyze(D: dict) -> dict:
    import networkx as nx
    from networkx.algorithms import community

    claims = D["claims"]
    ids = {c["id"] for c in claims}
    byid = {c["id"]: c for c in claims}
    H = {c["id"]: c["h"] for c in claims}
    order = list(D["chapters"])

    G = nx.DiGraph()
    G.add_nodes_from(ids)
    G.add_edges_from((l["s"], l["t"]) for l in D["links"])
    U = G.to_undirected()
    deg = dict(G.degree())
    bt = nx.betweenness_centrality(U) if len(ids) > 2 else {n: 0 for n in ids}

    comm, comms, mod = {}, [], 0.0
    if U.number_of_edges():
        cs = sorted(community.greedy_modularity_communities(U), key=lambda s: -len(s))
        mod = community.modularity(U, cs)
        for i, s in enumerate(cs):
            hub = max(s, key=lambda n: deg[n])
            for n in s:
                comm[n] = i
            comms.append({"id": i, "name": H[hub], "members": sorted(s, key=lambda n: -deg[n])})

    # 回路:只看因果子图
    cg = nx.DiGraph([(l["s"], l["t"]) for l in D["links"] if l["ty"] == "cause"])
    cycles = [c for c in nx.simple_cycles(cg)]

    # 最长论证链:先去掉回路里的「推断边」,仍有回路则逐条断开
    dag = nx.DiGraph(G)
    for cyc in cycles:
        for a, b in zip(cyc, cyc[1:] + cyc[:1]):
            es = [l for l in D["links"] if l["s"] == a and l["t"] == b]
            if es and all(e["basis"] == "i" for e in es) and dag.has_edge(a, b):
                dag.remove_edge(a, b)
    while not nx.is_directed_acyclic_graph(dag):
        u, v = nx.find_cycle(dag)[0][:2]
        dag.remove_edge(u, v)
    chain = nx.dag_longest_path(dag) if dag.number_of_nodes() else []

    # 缺佐证的观点:V 类命题且没有任何 support/refine 指向
    sup = {l["t"] for l in D["links"] if l["ty"] in ("support", "refine")}
    unsupported = [c["id"] for c in claims if c["ty"] == "V" and c["id"] not in sup]

    # 跨章关系:章距 >= 4
    cross = []
    for l in D["links"]:
        a, b = byid[l["s"]]["ch"], byid[l["t"]]["ch"]
        gap = abs(order.index(a) - order.index(b))
        if gap >= 4:
            cross.append({"s": l["s"], "t": l["t"], "gap": gap})
    cross.sort(key=lambda x: -x["gap"])

    return {
        "stats": {
            "claims": len(ids),
            "links": len(D["links"]),
            "inferred": sum(1 for l in D["links"] if l["basis"] == "i"),
            "components": nx.number_connected_components(U),
            "communities": len(comms),
            "modularity": round(mod, 2),
        },
        "hubs": sorted(ids, key=lambda n: -deg[n])[:6],
        "bridges": sorted(ids, key=lambda n: -bt[n])[:6],
        "comms": comms,
        "comm": comm,
        "cycles": cycles,
        "chain": chain,
        "unsupported": unsupported,
        "cross": cross[:8],
        "roots": [n for n in ids if G.in_degree(n) == 0],
        "sinks": [n for n in ids if G.out_degree(n) == 0],
        "degree": deg,
    }


def report(D: dict, A: dict) -> str:
    H = {c["id"]: c["h"] for c in D["claims"]}
    fmt = lambda xs: " → ".join(H[x] for x in xs)
    s = A["stats"]
    out = [
        f"《{D['title']}》  命题 {s['claims']} · 关系 {s['links']}(推断 {s['inferred']}) · "
        f"连通块 {s['components']} · 社群 {s['communities']}(模块度 {s['modularity']})",
        "",
        "枢纽命题:  " + "、".join(H[n] for n in A["hubs"]),
        "桥梁命题:  " + "、".join(H[n] for n in A["bridges"]),
        f"最长论证链({len(A['chain'])} 步): " + fmt(A["chain"]),
        f"反馈回路 {len(A['cycles'])} 个:",
        *[f"  - {fmt(c)} → {H[c[0]]}" for c in A["cycles"]],
        f"缺少佐证的观点 {len(A['unsupported'])} 个:",
        *[f"  - {H[n]}" for n in A["unsupported"]],
    ]
    return "\n".join(out)


def render(D: dict, outdir: Path, A: dict) -> list[Path]:
    payload = json.dumps({"D": D, "A": A}, ensure_ascii=False).replace("</", "<\\/")
    outdir.mkdir(parents=True, exist_ok=True)
    files = []
    for name, suffix in (("overview.html", "总览导图"), ("network.html", "关系网")):
        tpl = (TPL_DIR / name).read_text(encoding="utf8")
        out, n = _DATA.subn(lambda m: "/*DATA*/" + payload + "/*END*/", tpl, count=1)
        if n != 1:
            raise RuntimeError(f"模板 {name} 中找不到 /*DATA*/…/*END*/ 占位符")
        p = outdir / f"{D['title']}_{suffix}.html"
        p.write_text(out, encoding="utf8")
        files.append(p)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="book.json → 两个 HTML / 图论报告")
    ap.add_argument("book")
    ap.add_argument("-o", "--out", default="dist")
    ap.add_argument("--report", action="store_true", help="只打印图论报告,不出页面")
    ap.add_argument("--json", action="store_true", help="报告以 JSON 输出")
    a = ap.parse_args(argv)

    with open(a.book, encoding="utf8") as f:
        D = json.load(f)
    errs, warns = validate(D)
    if errs:
        for e in errs:
            print("错误:", e, file=sys.stderr)
        print("先修完错误再出图。", file=sys.stderr)
        return 1
    for w in warns:
        print("提示:", w, file=sys.stderr)

    try:
        A = analyze(D)
    except ImportError:
        print("缺少依赖 networkx,请先: pip install networkx", file=sys.stderr)
        return 2

    if a.report:
        print(json.dumps(A, ensure_ascii=False, indent=2) if a.json else report(D, A))
        return 0

    for f in render(D, Path(a.out), A):
        print("已生成", f)
    print("提示: 两页数据已内联,可直接分发;重跑前只需改 book.json。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
