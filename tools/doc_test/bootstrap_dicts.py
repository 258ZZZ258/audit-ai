"""Demo 字典自举(Phase 2,扩展 doc_test):从策展样本用 LLM(Flash)反推约束字典。

无甲方业务配合时,从本语料反推 demo 字典(v0-draft-demo,**仍需甲方评审**才能转正)。聚焦本语料
**强信号**四类(schema 严格对齐 seeds,见 ``pg_io.seed_dicts`` 消费):
- ``dict_violation_types``(code,name,dict_version)← 案例正文聚类违规事由(case_l2 T2.2 约束)
- ``dict_issuers``(code,name,issuer_level)← 外规题名抽发文机构(manifest issuer_level)
- ``dict_aliases``(alias,canonical_doc_number,canonical_title,dict_version)← 外规简称(case_l2 T2.1 对齐)
- ``dict_biz_domains``(code,name,parent_code)← 外规/案例主题(L2 业务域约束)

``entity_types``/``departments`` 是券商内部分类、外规+案例弱信号 → 沿用现有 v0-draft seed(不覆盖)。
纪律:JSON 输出(含 "json" + 示例);受限聚类、不臆造编码。模型默认 deepseek-v4-flash。

跑法:.venv/bin/python tools/doc_test/bootstrap_dicts.py \
        --in tools/doc_test/out/curated_classified.jsonl --seeds seeds [--dry-run]
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pipeline.llm_client import make_llm_client

DICT_VER = "v0-draft-demo-2026-06-29"


def _txt(rec: dict, n: int = 800) -> str:
    src = rec.get("txt_twin") or (rec["path"] if rec["ext"] == "txt" else None)
    if src:
        try:
            return Path(src).read_text(encoding="utf-8", errors="ignore")[:n]
        except OSError:
            return ""
    return ""


def _batch(xs: list, size: int):
    for i in range(0, len(xs), size):
        yield xs[i : i + size]


def _code(name: str, used: set[str], prefix: str = "") -> str:
    """为中文名造稳定 ASCII code(拼音不引依赖 → 用序号 + 前缀)。"""
    base = prefix or "C"
    i = 1
    while f"{base}{i:02d}" in used:
        i += 1
    c = f"{base}{i:02d}"
    used.add(c)
    return c


def bootstrap_violations(client, cases: list[dict]) -> list[dict]:
    """案例正文 → 分批抽违规事由 → 末次合并为 ~15-25 规范类目。"""
    raw_cats: set[str] = set()
    sys_b = (
        "你是证券处罚案例的违规事由归纳助手。给定多份处罚决定书的标题+正文片段,归纳其**违规事由类别**"
        "(如:信息披露违规、未勤勉尽责、内控不健全、违规交易、廉洁从业违规…)。只输出该批出现的类别,"
        '不臆造。只输出 JSON:{"categories": ["类别1", "类别2", ...]}。'
    )
    for batch in _batch(cases, 20):
        body = "\n\n".join(f"标题:{Path(c['path']).name}\n片段:{_txt(c, 500)}" for c in batch)
        try:
            r = client.chat_json(sys_b, body + '\n\n请按规则只输出 JSON:{"categories": [...]}。')
            for c in (r.get("categories") or []) if isinstance(r, dict) else []:
                if isinstance(c, str) and 2 <= len(c) <= 20:
                    raw_cats.add(c.strip())
        except Exception:
            continue
    # 末次合并:去同义、收敛
    sys_m = (
        "你是分类法归并助手。把下列违规事由候选合并去同义,收敛为 15-25 个**规范、互斥**的类别。"
        '只输出 JSON:{"categories": ["规范类别1", ...]}。'
    )
    try:
        r = client.chat_json(sys_m, "候选:" + "、".join(sorted(raw_cats)) + '\n\n只输出 JSON:{"categories": [...]}。')
        final = [c.strip() for c in (r.get("categories") or []) if isinstance(c, str) and c.strip()]
    except Exception:
        final = sorted(raw_cats)
    used: set[str] = set()
    return [{"code": _code(n, used, "V"), "name": n, "dict_version": DICT_VER} for n in final]


def bootstrap_issuers(client, exts: list[dict]) -> list[dict]:
    titles = [Path(e["path"]).name for e in exts]
    sys_i = (
        "你是发文机构抽取助手。从下列外规文件名中归纳**去重后的发文机构**及其层级"
        "(层级取:部级/会管/自律组织/地方监管局/其他)。只输出 JSON:"
        '{"issuers": [{"name": "中国证券监督管理委员会", "issuer_level": "部级"}, ...]}。'
    )
    try:
        r = client.chat_json(sys_i, "\n".join(titles[:160]) + '\n\n只输出 JSON:{"issuers": [...]}。')
        items = r.get("issuers") or [] if isinstance(r, dict) else []
    except Exception:
        items = []
    used: set[str] = set()
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("name"), str):
            out.append({"code": _code(it["name"], used, "ISS"), "name": it["name"].strip(),
                        "issuer_level": (it.get("issuer_level") or "其他").strip()})
    return out


def bootstrap_aliases(client, exts: list[dict]) -> list[dict]:
    titles = sorted({Path(e["path"]).name for e in exts})
    sys_a = (
        "你是法规简称助手。为下列外规给出**业内通用简称**(仅给确有通用简称的,不臆造)。"
        '只输出 JSON:{"aliases": [{"alias": "适当性办法", "canonical_title": "证券期货投资者适当性管理办法"}, ...]}。'
    )
    out: list[dict] = []
    for batch in _batch(titles, 40):
        try:
            r = client.chat_json(sys_a, "\n".join(batch) + '\n\n只输出 JSON:{"aliases": [...]}。')
            for it in (r.get("aliases") or []) if isinstance(r, dict) else []:
                if isinstance(it, dict) and it.get("alias") and it.get("canonical_title"):
                    out.append({"alias": it["alias"].strip(), "canonical_doc_number": "",
                                "canonical_title": it["canonical_title"].strip(), "dict_version": DICT_VER})
        except Exception:
            continue
    return out


def bootstrap_domains(client, recs: list[dict]) -> list[dict]:
    titles = [Path(r["path"]).name for r in recs]
    sys_d = (
        "你是证券业务域归纳助手。从下列文件名归纳 10-20 个**一级业务域**(如:信息披露、投资者适当性、"
        "经纪业务、资产管理、投资银行、合规风控、交易结算…)。只输出 JSON:"
        '{"domains": ["信息披露", ...]}。'
    )
    try:
        r = client.chat_json(sys_d, "\n".join(titles[:200]) + '\n\n只输出 JSON:{"domains": [...]}。')
        doms = [d.strip() for d in (r.get("domains") or []) if isinstance(d, str) and d.strip()]
    except Exception:
        doms = []
    used: set[str] = set()
    return [{"code": _code(n, used, "BD"), "name": n, "parent_code": ""} for n in doms]


def _write(path: Path, rows: list[dict], cols: list[str], dry: bool) -> None:
    print(f"  {path.name}: {len(rows)} 行 → {[r.get('name') or r.get('alias') for r in rows][:6]}…")
    if dry or not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo 字典自举(LLM Flash)")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--seeds", default="seeds")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写盘")
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.inp).read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [r for r in rows if r.get("llm_corpus") == "案例"]
    exts = [r for r in rows if r.get("llm_corpus") == "外规"]
    client = make_llm_client(args.model)
    sd = Path(args.seeds)
    print(f"自举字典:案例 {len(cases)} · 外规 {len(exts)}(model={args.model}, dry={args.dry_run})")

    _write(sd / "dict_violation_types.csv", bootstrap_violations(client, cases),
           ["code", "name", "dict_version"], args.dry_run)
    _write(sd / "dict_issuers.csv", bootstrap_issuers(client, exts),
           ["code", "name", "issuer_level"], args.dry_run)
    _write(sd / "dict_aliases.csv", bootstrap_aliases(client, exts),
           ["alias", "canonical_doc_number", "canonical_title", "dict_version"], args.dry_run)
    _write(sd / "dict_biz_domains.csv", bootstrap_domains(client, cases + exts),
           ["code", "name", "parent_code"], args.dry_run)
    print("\n(entity_types/departments 沿用现有 v0-draft seed,未覆盖)")


if __name__ == "__main__":
    main()
