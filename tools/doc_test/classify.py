"""Demo 语料内容分类(Phase 1 收尾,扩展 doc_test):LLM(Flash)确认 corpus_type + sub_type。

承 ``curate.py`` 的样本(文件名启发式仅供分层、已知有误判,如"行政处罚法"被误判案例)。读少量正文
片段(txt 孪生 / pdf 首页 / docx 首段;.doc 退化为仅文件名)+ 文件名 → LLM 在**受限标签**内判:
- corpus_type ∈ {外规, 案例, 其他} → 映射 P-EXT / P-CASE /(丢弃)
- sub_type:外规=法律/行政法规/部门规章/规范性文件/自律规则;案例=监管措施/行政处罚/纪律处分

纪律同管线富集:受限标签服务端裁剪、不臆测、JSON 输出(含 "json" 字样 + 示例,满足 DeepSeek)。
模型默认 deepseek-v4-flash(分类不吃推理);key/base_url 走 env(.env.local)。

跑法:.venv/bin/python tools/doc_test/classify.py --in tools/doc_test/out/curated_sample.jsonl \
        --out tools/doc_test/out/curated_classified.jsonl [--limit 25] [--workers 6]
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.llm_client import make_llm_client

CORPUS_MAP = {"外规": "P-EXT", "案例": "P-CASE"}
EXT_SUB = {"法律", "行政法规", "部门规章", "规范性文件", "自律规则"}
CASE_SUB = {"监管措施", "行政处罚", "纪律处分"}

_SYSTEM = (
    "你是证券审计语料的文档分类助手。仅依据【文件名 + 正文片段】判定两项,严格在受限标签内取值:"
    "(1) corpus_type:外规(法律法规/部门规章/交易所自律规则等对外规范)| 案例(对具体主体的行政处罚/"
    "监管措施/纪律处分**决定书**)| 其他(既非外规也非案例,如表格/附件/空白/无法判定);"
    "(2) sub_type:外规取『法律/行政法规/部门规章/规范性文件/自律规则』之一;案例取『监管措施/行政处罚/"
    "纪律处分』之一;其他给 null。硬性规则:**不臆测**(片段不足以判定→其他);**注意区分**——"
    "《行政处罚法》《XX处分条例》是法律/法规(外规),不是案例;案例是针对**具名主体**的处罚决定书。"
    '只输出 JSON 对象 {"corpus_type": "...", "sub_type": "..."},不输出 JSON 之外的任何文字。'
)


def _snippet(rec: dict, max_chars: int = 1600) -> str:
    """取少量正文片段:txt 孪生 > pdf 首页 > docx 首段 > 无(.doc 退化仅文件名)。"""
    src = rec.get("txt_twin") or (rec["path"] if rec["ext"] == "txt" else None)
    if src:
        try:
            return Path(src).read_text(encoding="utf-8", errors="ignore")[:max_chars]
        except OSError:
            pass
    p = rec["path"]
    if rec["ext"] == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(p) as pdf:
                return ((pdf.pages[0].extract_text() or "") if pdf.pages else "")[:max_chars]
        except Exception:
            return ""
    if rec["ext"] == "docx":
        try:
            import docx
            return "\n".join(par.text for par in docx.Document(p).paragraphs[:40])[:max_chars]
        except Exception:
            return ""
    return ""  # .doc:退化为仅文件名


def classify_one(client, rec: dict) -> dict:
    name = Path(rec["path"]).name
    snippet = _snippet(rec)
    user = (
        f"【文件名】{name}\n【正文片段】\n{snippet or '(无正文,仅据文件名判定;不足以判定则归其他)'}\n\n"
        '请按规则只输出 JSON:{"corpus_type": "外规|案例|其他", "sub_type": "...或 null"}。'
    )
    out = dict(rec)
    try:
        raw = client.chat_json(_SYSTEM, user)
        ct = raw.get("corpus_type") if isinstance(raw, dict) else None
        st = raw.get("sub_type") if isinstance(raw, dict) else None
        out["llm_corpus"] = ct if ct in {"外规", "案例", "其他"} else "其他"
        valid_sub = EXT_SUB if out["llm_corpus"] == "外规" else CASE_SUB if out["llm_corpus"] == "案例" else set()
        out["llm_sub_type"] = st if st in valid_sub else None
        out["corpus_type_code"] = CORPUS_MAP.get(out["llm_corpus"])  # P-EXT/P-CASE/None
    except Exception as e:  # 非阻断:分类失败标记,留后续人工/重试
        out["llm_corpus"] = "ERROR"
        out["llm_sub_type"] = None
        out["corpus_type_code"] = None
        out["error"] = f"{type(e).__name__}: {e}"[:160]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo 语料内容分类(LLM Flash)")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--limit", type=int, default=0, help=">0 只跑前 N 件(pilot)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.inp).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    client = make_llm_client(args.model)
    print(f"分类 {len(rows)} 件(model={args.model}, workers={args.workers})…")

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda r: classify_one(client, r), rows))

    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8"
    )

    # 对照启发式,统计纠正 + 丢弃
    corp = Counter(r["llm_corpus"] for r in results)
    sub = Counter((r["llm_corpus"], r["llm_sub_type"]) for r in results)

    # 启发式 type 与 LLM corpus 不一致计数
    def heur(r):
        return "案例" if r["type"] == "案例" else ("外规" if r["type"].startswith("外规") else "未判定")
    mism = [r for r in results if r["llm_corpus"] in {"外规", "案例"} and heur(r) != r["llm_corpus"]]
    dropped = [r for r in results if r["llm_corpus"] in {"其他", "ERROR"}]

    print(f"\nLLM corpus 分布:{dict(corp)}")
    print(f"纠正(启发式≠LLM,且 LLM 判外规/案例):{len(mism)}")
    for r in mism[:8]:
        print(f"  {heur(r)}→{r['llm_corpus']}/{r['llm_sub_type']}  {Path(r['path']).name[:48]}")
    print(f"\n判为 其他/ERROR(将丢弃):{len(dropped)}")
    for r in dropped[:8]:
        print(f"  [{r['llm_corpus']}] {Path(r['path']).name[:52]}")
    print("\nsub_type 分布:")
    for k, c in sub.most_common():
        print(f"  {k}: {c}")
    print(f"\n输出:{args.out}")


if __name__ == "__main__":
    main()
