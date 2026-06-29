"""Demo 语料策展(Phase 1,扩展 doc_test):去重 → 引用感知分层抽样 → 扫描标记。

输入:爬取语料根(混合格式、目录名不可信)。输出:待分类的代表性样本清单 + 覆盖报告。
**纯确定性**(零 LLM、零栈):类型用文件名启发式(仅供分层);精确 corpus_type/sub_type 由后续
``classify.py`` 用 LLM(Flash)在样本上确认。跨格式去重:同题留首选格式(案例→PDF 保页锚,外规→
最佳可解析)。引用感知:从案例 txt 正则采集所引外规(《》题名 / 证监会令·公告文号)→ 外规抽样优先
覆盖,使 case_l2 T2.1 对齐可真演示。

跑法:.venv/bin/python tools/doc_test/curate.py --root <语料根> --target 250 --out tools/doc_test/out
"""

# ruff: noqa: E501  (工具脚本:CJK 密集,放宽行宽)

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

JUNK_EXT = {"csv", "json", "xls", "xlsx", "ds_store", ""}
DOC_EXT = ["pdf", "docx", "doc", "txt"]  # 首选优先级(同题去重时靠前者胜)
CASE_PREF = ["pdf", "txt", "docx", "doc"]   # 案例:留 PDF(页锚)
EXT_PREF = ["pdf", "docx", "doc", "txt"]    # 外规:留最佳可解析

_CASE_RE = re.compile(r"(警示函|监管措施|行政处罚|纪律处分|处分(决定)?|监管谈话|责令改正|认定为不适当人选|采取.{0,8}措施.{0,4}决定)")
_LAW_RE = re.compile(r"中华人民共和国.{1,12}法([（(].*?[)）])?$")
_SELF_RE = re.compile(r"(交易所|结算|登记).{0,20}(规则|办法|细则|指引|指南|规定|业务规则|手册|章程)")
_RULE_RE = re.compile(r"(通知|公告|批复|复函|意见|办法|规定|细则|指引|准则|解释)")

# 引用采集:《书名号题名》 + 证监会令第N号 / 公告〔YYYY〕N号 / [YYYY]N号
_CITE_TITLE = re.compile(r"《([^》]{4,40})》")
_CITE_DOCNO = re.compile(r"((?:证监会|证监)?(?:令|公告|发)?\s*[〔\[【(]?\s*\d{4}\s*[〕\]】)]?\s*第?\s*\d{1,4}\s*号)")


def guess_type(name: str) -> str:
    s = re.sub(r"\.[^.]+$", "", name)
    if _CASE_RE.search(s):
        return "案例"
    if _LAW_RE.search(s):
        return "外规·法律"
    if _SELF_RE.search(s):
        return "外规·自律规则"
    if _RULE_RE.search(s):
        return "外规·部门规章通知"
    return "未判定"


def norm_title(name: str) -> str:
    s = re.sub(r"\.[^.]+$", "", name)
    s = re.sub(r"^\d{1,4}[_-]", "", s)
    s = re.sub(r"^\d{4}-\d{2}-\d{2}[_-]", "", s)
    s = re.sub(r"^\d{1,4}[_-]", "", s)
    s = re.sub(r"[（(【].*?年.*?[)）】]", "", s)
    return s.strip()


def is_case(t: str) -> bool:
    return t == "案例"


def collect(root: Path) -> tuple[list[dict], dict]:
    """遍历 → 去重 → 唯一逻辑文档(带可用格式 + txt 孪生)。返回 (unique_docs, stats)。"""
    groups: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    junk = empty = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower().lstrip(".")
        if ext in JUNK_EXT:
            junk += 1
            continue
        if ext not in DOC_EXT:
            continue
        try:
            if p.stat().st_size < 64:
                empty += 1
                continue
        except OSError:
            continue
        groups[norm_title(p.name)].append((ext, p))

    unique: list[dict] = []
    for title, members in groups.items():
        exts = {e for e, _ in members}
        t = guess_type(members[0][1].name)
        pref = CASE_PREF if is_case(t) else EXT_PREF
        chosen = min(members, key=lambda m: pref.index(m[0]) if m[0] in pref else 9)
        twin_txt = next((p for e, p in members if e == "txt"), None)
        unique.append({
            "title": title,
            "type": t,
            "ext": chosen[0],
            "path": str(chosen[1]),
            "formats": sorted(exts),
            "txt_twin": str(twin_txt) if twin_txt else None,
        })
    stats = {"junk": junk, "empty": empty, "groups": len(groups), "unique": len(unique)}
    return unique, stats


def harvest_citations(case_docs: list[dict]) -> tuple[set[str], set[str]]:
    """从案例 txt(孪生或本体)正则采集引用外规题名 + 文号。"""
    titles: set[str] = set()
    docnos: set[str] = set()
    for d in case_docs:
        src = d["txt_twin"] or (d["path"] if d["ext"] == "txt" else None)
        if not src:
            continue
        try:
            text = Path(src).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _CITE_TITLE.findall(text):
            titles.add(m.strip())
        for m in _CITE_DOCNO.findall(text):
            docnos.add(re.sub(r"\s+", "", m))
    return titles, docnos


def cites_match(doc: dict, titles: set[str], docnos: set[str]) -> bool:
    nm = doc["title"]
    if any(t in nm or nm in t for t in titles):
        return True
    return any(re.sub(r"\s+", "", n) in nm.replace(" ", "") for n in docnos)


def stratified(docs: list[dict], k: int, rng: random.Random) -> list[dict]:
    """按 (type, ext) 分层近似均衡抽 k 件。"""
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for d in docs:
        buckets[(d["type"], d["ext"])].append(d)
    for b in buckets.values():
        rng.shuffle(b)
    out: list[dict] = []
    i = 0
    keys = list(buckets)
    while len(out) < k and any(buckets[key] for key in keys):
        key = keys[i % len(keys)]
        if buckets[key]:
            out.append(buckets[key].pop())
        i += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo 语料策展(去重+引用感知抽样)")
    ap.add_argument("--root", required=True)
    ap.add_argument("--target", type=int, default=250)
    ap.add_argument("--out", default="tools/doc_test/out")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    root = Path(args.root).expanduser()
    unique, stats = collect(root)
    cases = [d for d in unique if is_case(d["type"])]
    exts = [d for d in unique if d["type"].startswith("外规")]
    undecided = [d for d in unique if d["type"] == "未判定"]

    # 配额:案例 ~36% / 外规 ~56% / 未判定 ~8%
    n_case = round(args.target * 0.36)
    n_ext = round(args.target * 0.56)
    n_und = args.target - n_case - n_ext

    case_sample = stratified(cases, n_case, rng)
    titles, docnos = harvest_citations(cases)  # 全案例采集,最大化覆盖信号
    cited_pool = [d for d in exts if cites_match(d, titles, docnos)]
    rng.shuffle(cited_pool)
    n_cited = min(len(cited_pool), round(n_ext * 0.5))  # 半数额度优先给被引外规
    ext_sample = cited_pool[:n_cited]
    chosen_paths = {d["path"] for d in ext_sample}
    rest = [d for d in exts if d["path"] not in chosen_paths]
    ext_sample += stratified(rest, n_ext - n_cited, rng)
    und_sample = stratified(undecided, n_und, rng)

    sample = case_sample + ext_sample + und_sample
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "curated_sample.jsonl").write_text(
        "\n".join(json.dumps(d, ensure_ascii=False) for d in sample), encoding="utf-8"
    )

    # 报告
    fmt = Counter((d["type"], d["ext"]) for d in sample)
    cov = sum(1 for d in ext_sample if cites_match(d, titles, docnos))
    lines = [
        "# Demo 语料策展报告(Phase 1 · 确定性)\n",
        f"- 语料根:{root}",
        f"- 去重:{stats['groups']} 题 → 唯一 {stats['unique']}(垃圾 {stats['junk']} · 空 {stats['empty']})",
        f"- 唯一池:案例 {len(cases)} · 外规 {len(exts)} · 未判定 {len(undecided)}",
        f"- 采集引用:题名 {len(titles)} 种 · 文号 {len(docnos)} 种",
        f"- **样本 {len(sample)}**:案例 {len(case_sample)} · 外规 {len(ext_sample)}(覆盖引用 {cov})· 未判定 {len(und_sample)}",
        "\n## 样本 类型×格式",
    ]
    for (t, e), c in sorted(fmt.items(), key=lambda x: -x[1]):
        lines.append(f"- {t} · {e}: {c}")
    (outdir / "curate_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\n样本清单:{outdir/'curated_sample.jsonl'}")


if __name__ == "__main__":
    main()
