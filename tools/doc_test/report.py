"""产出:逐 PDF 指标 JSON + 易懂中文 Markdown 报告(标失效 PDF + 三目标分项 + 异常指标分析 + 阈值建议)。"""

# ruff: noqa: E501  (工具脚本:报告/prompt 文案 CJK 密集,放宽行宽)

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def _stats(vals: list[float]) -> str:
    if not vals:
        return "—"
    return f"min {min(vals):.3f} / 中位 {statistics.median(vals):.3f} / max {max(vals):.3f}"


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100*n/d:.0f}%)" if d else "0/0"


def _md_table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "(无)\n"
    h = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows)
    return f"{h}\n{sep}\n{body}\n"


def write(results: list[dict], out_dir: Path, report_name: str, metrics_name: str,
          llm_enabled: bool) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    # JSON(去掉内部 _text 大字段)
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    jpath = out_dir / metrics_name
    jpath.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")

    md = _build_md(results, llm_enabled)
    rpath = out_dir / report_name
    rpath.write_text(md, encoding="utf-8")
    return rpath, jpath


def _judge(r: dict) -> dict:
    j = r.get("judge") or {}
    return j if isinstance(j, dict) and "error" not in j else {}


def _build_md(results: list[dict], llm_enabled: bool) -> str:
    n = len(results)
    by_type = Counter(r["corpus_type"] for r in results)
    failed = [r for r in results if r.get("pipeline_failed")]
    parse_fail = [r for r in results if not r.get("parse_ok")]

    s: list[str] = []
    s.append("# 第一期文档处理管线测试报告\n")
    s.append(f"- 总 PDF:**{n}** · 按类型:" + "、".join(f"{k} {v}" for k, v in by_type.items()))
    s.append(f"- **管线失效:{_pct(len(failed), n)}** · 解析失败:{_pct(len(parse_fail), n)}")
    s.append(f"- LLM 裁判:{'已启用' if llm_enabled else '未启用(仅确定性指标)'}\n")

    # ── 失效 PDF ─────────────────────────────────────────────────────────
    s.append("## ⚠ 管线失效 PDF\n")
    s.append(_md_table(["文件", "类型", "失效原因"],
                       [[r["name"], r["corpus_type"], "；".join(r["failure_reasons"])] for r in failed]))

    s.append(_goal1(results, llm_enabled))
    s.append(_goal2(results, llm_enabled))
    s.append(_goal3(results, llm_enabled))
    s.append(_anomalies(results))
    return "\n".join(s)


# ── 目标①:正则覆盖度 / 结构化提取 ──────────────────────────────────────────
def _goal1(results: list[dict], llm_enabled: bool) -> str:
    s = ["## 目标① 正则匹配覆盖度 / 结构化提取\n"]
    ok = [r for r in results if r.get("parse_ok")]
    # 1a 字段抽取命中率(逐类型)
    pres = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # type -> field -> [hit, total]
    for r in ok:
        for f, hit in (r.get("extract_presence") or {}).items():
            pres[r["corpus_type"]][f][0] += int(bool(hit))
            pres[r["corpus_type"]][f][1] += 1
    rows = []
    for ct, fields in pres.items():
        for f, (hit, tot) in fields.items():
            rows.append([ct, f, _pct(hit, tot)])
    s.append("**要素正则抽取命中率**(无 manifest,以是否抽到为准):\n")
    s.append(_md_table(["类型", "字段", "命中率"], rows))

    # 1b 条款树覆盖(P-INT/P-EXT:用 QC clause_coverage + heading_hit_rate)
    clause = [r for r in ok if r["corpus_type"] in ("P-INT", "P-EXT")]
    if clause:
        cov = [_qc_val(r, "clause_coverage") for r in clause]
        cov = [c for c in cov if c is not None]
        hh = [r["heading_hit_rate"] for r in clause if r.get("heading_hit_rate") is not None]
        s.append(f"**条款树覆盖**(内/外规 {len(clause)} 件):clause_coverage {_stats(cov)}"
                 + (f" · 表头识别率 {_stats(hh)}" if hh else "") + "\n")
        s.append("> clause_coverage = 结构化条数 ÷ 宽松「第X条」命中数。**>1 正常**(用小数/交易所编号体例,"
                 "「第X条」分母小);**<1 才是漏结构化**(正则没接住该体例的条款)——下表只列 <0.95 的件。"
                 "表头识别率 = 正文段落被识别为 章/节/条/款/项 的比例。\n")
        low = [r for r in clause if (_qc_val(r, "clause_coverage") or 1) < 0.95]
        if low:
            s.append("覆盖偏低(<0.95,疑似正则漏接编号体例)的件:\n")
            s.append(_md_table(["文件", "clause_coverage", "QC 未过"],
                               [[r["name"], _qc_val(r, "clause_coverage"), "、".join(r.get("qc_failed", []))]
                                for r in low]))

    # 1c LLM 核对:正则抽取对不对(precision)+ 漏识别
    if llm_enabled:
        rows = []
        for r in ok:
            g1 = _judge(r).get("goal1_extraction") or {}
            if not g1:
                continue
            wrong = [k for k in ("doc_number", "date", "issuer_or_org")
                     if isinstance(g1.get(k), dict) and g1[k].get("correct") is False]
            if wrong or g1.get("structure_complete") is False or g1.get("issues"):
                rows.append([r["name"], "、".join(wrong) or "—",
                             "否" if g1.get("structure_complete") is False else "是",
                             "；".join(g1.get("issues", []))[:120]])
        s.append("**LLM 核对正则抽取**(标出抽错/漏识别的件):\n")
        s.append(_md_table(["文件", "抽错字段", "结构完整", "问题"], rows))
        scores = [(_judge(r).get("goal1_extraction") or {}).get("coverage_score")
                  for r in ok]
        scores = [x for x in scores if isinstance(x, (int, float))]
        if scores:
            s.append(f"\nLLM 综合覆盖评分:{_stats(scores)}\n")
    return "\n".join(s)


# ── 目标②:是否需要 DeepDoc ─────────────────────────────────────────────────
def _goal2(results: list[dict], llm_enabled: bool) -> str:
    s = ["## 目标② 解析模块是否需要 DeepDoc\n"]
    n = len(results)
    scanned = [r for r in results if r.get("likely_scanned")]
    garb = [r for r in results if (r.get("garbled_ratio") or 0) > 0.01]
    s.append(f"- 启发式:疑似扫描件/低文本密度 **{_pct(len(scanned), n)}** · 乱码率>1% {_pct(len(garb), n)}")
    if llm_enabled:
        rec = [r for r in results if (_judge(r).get("goal2_parse") or {}).get("verdict") == "deepdoc_recommended"]
        reasons = Counter()
        for r in rec:
            reasons.update((_judge(r).get("goal2_parse") or {}).get("reasons", []))
        s.append(f"- LLM 判定**建议上 DeepDoc:{_pct(len(rec), n)}** · 原因分布:"
                 + ("、".join(f"{k}×{v}" for k, v in reasons.most_common()) or "—"))
        s.append("\n建议上 DeepDoc 的件:\n")
        s.append(_md_table(["文件", "类型", "原因", "置信"],
                           [[r["name"], r["corpus_type"],
                             "、".join((_judge(r).get("goal2_parse") or {}).get("reasons", [])),
                             (_judge(r).get("goal2_parse") or {}).get("confidence", "")] for r in rec]))
    else:
        s.append("\n(未启用 LLM:版面破碎/表格丢失需 LLM 复核,当前仅启发式扫描件判定。)\n")
    s.append("> **结论口径**:扫描件/低密度 → 必须 OCR(DeepDoc/PaddleOCR);版面破碎/表格丢失占比高 → "
             "建议 DeepDoc 提升结构化;若两者占比都低,light 解析够用。\n")
    return "\n".join(s)


# ── 目标③:QC 门控阈值是否需调整 ───────────────────────────────────────────
def _goal3(results: list[dict], llm_enabled: bool) -> str:
    s = ["## 目标③ QC 门控阈值是否需要调整\n"]
    # 按指标聚合(跨所有跑了该指标的 PDF)
    agg: dict[str, dict] = {}
    for r in results:
        for ind in r.get("qc", []):
            a = agg.setdefault(ind["name"], {"vals": [], "th": ind["threshold"], "fail": 0,
                                             "good_fail": 0, "bad_pass": 0})
            a["vals"].append(ind["value"])
            if not ind["passed"]:
                a["fail"] += 1
            if llm_enabled:
                q = (_judge(r).get("goal3_quality") or {}).get("doc_quality")
                if q == "good" and not ind["passed"]:
                    a["good_fail"] += 1       # 好文档却被拦 → 阈值可能太严
                if q == "bad" and ind["passed"]:
                    a["bad_pass"] += 1        # 坏文档却放行 → 阈值可能太松

    rows = []
    for name, a in agg.items():
        rec = "—"
        if llm_enabled and a["good_fail"] >= 2:
            rec = f"⬇ 疑似太严({a['good_fail']} 好件被拦)"
        elif llm_enabled and a["bad_pass"] >= 2:
            rec = f"⬆ 疑似太松({a['bad_pass']} 坏件放行)"
        elif a["fail"] == 0:
            rec = "✓ 无失败"
        rows.append([name, f"{a['th']}", _stats(a["vals"]), a["fail"], rec])
    s.append(_md_table(["QC 指标", "当前阈值", "数值分布", "失败数", "阈值建议"], rows))
    if llm_enabled:
        s.append("> 阈值建议依据 **LLM 判文档好坏 × QC 通过/失败** 的不一致:好却被拦=假阳(放宽)、"
                 "坏却放行=假阴(收紧)。建议项需人工复核 2~3 个具体件再定。\n")
    else:
        s.append("> (未启用 LLM:仅给出数值分布与失败数;阈值松紧需 LLM/人工判文档好坏后反推。)\n")
    return "\n".join(s)


def _anomalies(results: list[dict]) -> str:
    """异常指标分析:失败率最高的 QC 指标 + 抽取命中率最低的字段。"""
    s = ["## 异常指标分析\n"]
    fail = Counter()
    tot = Counter()
    for r in results:
        for ind in r.get("qc", []):
            tot[ind["name"]] += 1
            if not ind["passed"]:
                fail[ind["name"]] += 1
    rows = sorted(([name, _pct(fail[name], tot[name])] for name in tot),
                  key=lambda x: -(fail[x[0]] / tot[x[0]] if tot[x[0]] else 0))
    s.append("**QC 指标失败率排行**(越高越值得关注:或文档质量差,或阈值不合理):\n")
    s.append(_md_table(["QC 指标", "失败率"], rows))
    return "\n".join(s)


def _qc_val(r: dict, key: str):
    for ind in r.get("qc", []):
        if ind["key"] == key:
            return ind["value"]
    return None
