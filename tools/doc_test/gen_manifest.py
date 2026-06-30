"""Demo manifest 全量自动生成(Phase 3b,扩展 doc_test):L1 正则 + L2 LLM → 11 列 manifest.xlsx。

无甲方登记表时,从正文/文件名自动生成 ``demo ingest`` 所需 manifest(契约 11 列,见 ``common.manifest``)。
- filename / corpus_type / sub_type ← staged.jsonl(装配 + 分类已定)
- perm_tag ← 默认「公开」(外规/案例均公开发布);supersedes ← 空(新爬取无版本链)
- title / doc_number / issuer / issue_date / effective_date / biz_domain ← **L1 正则 + L2 LLM(Flash)**
  biz_domain 约束在 ``dict_biz_domains``;此即"L2 元数据 LLM 节点"实测点(全量 manifest 下管线内 L2 被旁路)。

跑法:.venv/bin/python tools/doc_test/gen_manifest.py \
        --in tools/doc_test/out/staged.jsonl --batch-dir tools/doc_test/out/batch \
        --seeds seeds --out tools/doc_test/out/manifest.xlsx
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openpyxl import Workbook

from pipeline.llm_client import make_llm_client

COLUMNS = ["filename", "title", "doc_number", "issuer", "perm_tag",
           "corpus_type", "sub_type", "biz_domain", "issue_date", "effective_date", "supersedes"]

_DATE_RE = re.compile(r"(20\d{2})[-_.年](\d{1,2})[-_.月](\d{1,2})")
_DOCNO_RE = re.compile(r"(【[^】]*?第?\s*\d{1,4}\s*号[^】]*?】|〔20\d{2}〕\s*\d{1,4}\s*号|证监会(?:令|公告)\s*[〔\[]?20\d{2}[〕\]]?\s*第?\d{1,4}号|第\d{1,4}号)")


def l1_hints(filename: str) -> tuple[str, str]:
    """L1 正则从文件名预抽 (issue_date ISO, doc_number)。"""
    d = _DATE_RE.search(filename)
    iso = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}" if d else ""
    m = _DOCNO_RE.search(filename)
    dn = m.group(1).strip("【】") if m else ""
    return iso, dn


def snippet(rec: dict, n: int = 1200) -> str:
    src = rec.get("txt_twin") or (rec["orig_path"] if rec["orig_path"].endswith(".txt") else None)
    if src:
        try:
            return Path(src).read_text(encoding="utf-8", errors="ignore")[:n]
        except OSError:
            return ""
    p = rec["orig_path"]
    if p.lower().endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(p) as pdf:
                return ((pdf.pages[0].extract_text() or "") if pdf.pages else "")[:n]
        except Exception:
            return ""
    if p.lower().endswith(".docx"):
        try:
            import docx
            return "\n".join(par.text for par in docx.Document(p).paragraphs[:30])[:n]
        except Exception:
            return ""
    return ""


def _system(domains: list[str]) -> str:
    return (
        "你是证券制度文档的元数据抽取助手。依据【文件名 + 正文片段】抽取登记元数据,**不臆测**"
        "(文中无则留空/给 null)。硬性规则:(1) title=规范标题(去编号/日期前缀,书名号内为准);"
        "(2) doc_number=发文字号原文(如〔2020〕5号/证监会令第137号,无则 null);(3) issuer=发文机构全称"
        "(如中国证监会北京监管局,**精确到实际发文机关**,勿简写为'证监会');(4) issue_date/effective_date=ISO"
        "(YYYY-MM-DD,无则 null;生效日未写明则等于发布日);(5) biz_domain **只能取自**给定业务域清单的一项,"
        "不匹配给 null。只输出 JSON 对象 "
        '{"title":..., "doc_number":..., "issuer":..., "issue_date":..., "effective_date":..., "biz_domain":...},'
        "不输出 JSON 之外的任何文字。\n业务域清单:" + "、".join(domains)
    )


def extract(client, rec: dict, domains: list[str], domain_set: set[str]) -> dict:
    name = Path(rec["filename"]).name
    iso, dn = l1_hints(rec.get("orig_path", "") + " " + name)
    user = (
        f"【文件名】{name}\n【L1 线索】发布日={iso or '未抽到'} 文号={dn or '未抽到'}\n"
        f"【正文片段】\n{snippet(rec) or '(无正文)'}\n\n"
        '请按规则只输出 JSON:{"title":...,"doc_number":...,"issuer":...,"issue_date":...,"effective_date":...,"biz_domain":...}。'
    )
    try:
        r = client.chat_json(_system(domains), user)
    except Exception:
        r = {}

    def g(k: str) -> str:
        v = r.get(k) if isinstance(r, dict) else None
        return str(v).strip() if v not in (None, "", "null") else ""

    issue = g("issue_date") or iso
    bd = g("biz_domain")
    return {
        "title": g("title"),
        "doc_number": g("doc_number") or dn,
        "issuer": g("issuer"),
        "issue_date": issue,
        "effective_date": g("effective_date") or issue,
        "biz_domain": bd if bd in domain_set else "",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo manifest 全量生成(L1+L2)")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--seeds", default="seeds")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--perm-tag", default="公开")
    ap.add_argument("--no-title", action="store_true", help="title 留空交 L1(bulk 入库免标题冲突 META_REVIEW)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.inp).read_text(encoding="utf-8").splitlines() if line.strip()]
    with (Path(args.seeds) / "dict_biz_domains.csv").open(encoding="utf-8") as f:
        domains = [r["name"] for r in csv.DictReader(f)]
    domain_set = set(domains)
    client = make_llm_client(args.model)
    print(f"生成 manifest:{len(rows)} 行(model={args.model})…")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        metas = list(ex.map(lambda r: extract(client, r, domains, domain_set), rows))

    wb = Workbook()
    ws = wb.active
    ws.append(COLUMNS)
    filled = {c: 0 for c in COLUMNS}
    for rec, m in zip(rows, metas, strict=True):
        row = {
            # --no-title:title 也留空交 L1(消除标题冲突 → 免 mass-META_REVIEW;副作用:停用标题+文号疑似重复闸)
            "filename": rec["filename"], "title": ("" if args.no_title else m["title"]), "doc_number": m["doc_number"],
            "issuer": m["issuer"], "perm_tag": args.perm_tag, "corpus_type": rec["corpus_type_code"],
            "sub_type": rec.get("sub_type") or "", "biz_domain": m["biz_domain"],
            # ⚠ issue_date/effective_date 留空:交管线 L1 抽正文权威日期,避免与文件名日期系统性冲突
            #   (实测文件名日期 ≠ 正文发文日 → 大量 META_REVIEW)。L1 缺则降级仅告警,不阻断。
            "issue_date": "", "effective_date": "", "supersedes": "",
        }
        ws.append([row[c] for c in COLUMNS])
        for c in COLUMNS:
            if row[c]:
                filled[c] += 1
    wb.save(args.out)

    n = len(rows)
    print(f"\nmanifest:{args.out}({n} 行 × 11 列)")
    print("各列填充率:")
    for c in COLUMNS:
        print(f"  {c:16s} {filled[c]}/{n} ({filled[c]*100//max(n,1)}%)")


if __name__ == "__main__":
    main()
