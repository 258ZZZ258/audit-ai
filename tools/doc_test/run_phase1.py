"""第一期文档处理管线测试 —— 主程序。

对一批已分类好的 PDF(无 manifest,跳过 S0 登记),逐件跑 解析→切块→QC→正则抽取 的确定性指标,
+ 可选 LLM 无标注裁判,产出易懂 Markdown 报告(标失效 PDF + 三目标分项 + 异常指标分析 + 阈值建议)。

跑法:.venv/bin/python tools/doc_test/run_phase1.py --config tools/doc_test/config.yaml
"""

# ruff: noqa: E501  (工具脚本:报告/prompt 文案 CJK 密集,放宽行宽)

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import judge as judge_mod
import metrics as metrics_mod
import report as report_mod
import yaml

from pipeline.config import load_config


def resolve_type(pdf: Path, root: Path, corpus_map: dict, overrides: dict, unclassified: str):
    if pdf.name in overrides:
        return overrides[pdf.name]
    for part in pdf.relative_to(root).parts[:-1]:  # 父目录名 → 类型
        if part in corpus_map:
            return corpus_map[part]
    return None if unclassified == "skip" else unclassified


def discover(cfg: dict) -> list[tuple[Path, str]]:
    root = Path(cfg["pdf_root"]).expanduser()
    if not root.is_dir():
        sys.exit(f"pdf_root 不存在或非目录:{root}")
    pat = "**/*.pdf" if cfg.get("recurse", True) else "*.pdf"
    pairs, skipped = [], []
    for pdf in sorted(root.glob(pat)):
        ct = resolve_type(pdf, root, cfg.get("corpus_map", {}), cfg.get("file_overrides", {}),
                          cfg.get("unclassified", "skip"))
        (pairs if ct else skipped).append((pdf, ct))
    if skipped:
        print(f"⚠ 未分类跳过 {len(skipped)} 件(目录名不在 corpus_map):"
              + "、".join(p.name for p, _ in skipped[:10]) + (" …" if len(skipped) > 10 else ""))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="第一期文档处理管线测试")
    ap.add_argument("--config", required=True, help="config.yaml 路径")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))

    settings = load_config()
    chunk_cfg = settings.chunk
    qc_over = cfg.get("qc_thresholds") or {}
    qc_th = settings.qc.model_copy(update=qc_over) if qc_over else settings.qc
    scanned_max = int((cfg.get("parse") or {}).get("scanned_char_per_page_max", 50))

    pairs = discover(cfg)
    if not pairs:
        sys.exit("没有可测 PDF(检查 pdf_root / corpus_map)。")
    print(f"开始测试 {len(pairs)} 件 PDF …")

    llm_cfg = cfg.get("llm") or {}
    llm_enabled = bool(llm_cfg.get("enabled"))
    client = None
    if llm_enabled:
        try:
            client = judge_mod.make_llm_client(llm_cfg.get("model"))
        except Exception as e:
            print(f"⚠ LLM 不可用,降级为仅确定性指标:{e}")
            llm_enabled = False
    max_pdfs = int(llm_cfg.get("max_pdfs", 0))

    results, judged = [], 0
    for i, (pdf, ct) in enumerate(pairs, 1):
        print(f"[{i}/{len(pairs)}] {ct}  {pdf.name}")
        try:
            r = metrics_mod.compute(pdf, ct, scanned_max, chunk_cfg, qc_th)
        except Exception as e:  # 单件异常不阻断整批
            r = {"path": str(pdf), "name": pdf.name, "corpus_type": ct, "pipeline_failed": True,
                 "failure_reasons": [f"指标计算异常:{type(e).__name__}: {e}"], "qc": [], "qc_failed": []}
        if llm_enabled and r.get("parse_ok") and (max_pdfs == 0 or judged < max_pdfs):
            r["judge"] = judge_mod.judge_pdf(r, llm_cfg, client=client)
            judged += 1
        results.append(r)

    out = cfg.get("output") or {}
    out_dir = Path(out.get("dir", "tools/doc_test/out"))
    rpath, jpath = report_mod.write(
        results, out_dir, out.get("report_name", "phase1_report.md"),
        out.get("metrics_name", "phase1_metrics.json"), llm_enabled)
    nfail = sum(1 for r in results if r.get("pipeline_failed"))
    print(f"\n完成。管线失效 {nfail}/{len(results)} · LLM 裁判 {judged} 件")
    print(f"报告:{rpath}\n指标:{jpath}")


if __name__ == "__main__":
    main()
