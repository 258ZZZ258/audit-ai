"""Demo 入库装配(Phase 3a,扩展 doc_test):样本 → 单一批目录(唯一文件名)+ 格式归一。

承 ``classify.py`` 的策展分类集(仅取 案例/外规)。装配为 ``demo ingest`` 可吃的批目录:
- pdf/docx/jpg/png(S0 白名单内)→ 直接拷入,唯一命名;
- ``.doc``/``.txt``(白名单外,S0 会隔离)→ **soffice 转 pdf** 入批(LibreOffice,信创经 PIPELINE_SOFFICE);
- 扫描 pdf 不在此判 → 交管线 S2(E202 PARSE_FAILED,混合策略待 OCR)。

输出:批目录(唯一文件名)+ ``staged.jsonl``(staging 名 ↔ 分类 ↔ 原始路径/ txt 孪生,供 manifest 生成)。

跑法:.venv/bin/python tools/doc_test/stage_corpus.py \
        --in tools/doc_test/out/curated_classified.jsonl --batch-dir tools/doc_test/out/batch
"""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

WHITELIST = {"pdf", "docx", "jpg", "png"}
CONVERT = {"doc", "txt"}
_MAC_SOFFICE = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")


def soffice_bin() -> str:
    return os.environ.get("PIPELINE_SOFFICE") or shutil.which("soffice") or shutil.which("libreoffice") or str(_MAC_SOFFICE)


def safe_stem(name: str, n: int = 70) -> str:
    s = re.sub(r"\.[^.]+$", "", name)
    s = re.sub(r'[\\/:*?"<>|【】《》（）()\s]+', "_", s).strip("_")
    return s[:n] or "doc"


def convert_batch(srcs: list[tuple[Path, Path]], batch_dir: Path, timeout: int = 180) -> list[str]:
    """soffice 批转 pdf:srcs=[(唯一命名的临时源, 目标 stem)];返回成功生成的 staging 文件名。"""
    if not srcs:
        return []
    ok: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        staged_src = []
        for src, stem in srcs:
            dst = tmp / (stem.name + src.suffix.lower())  # 唯一 stem + 原扩展,避免 soffice 输出撞名
            shutil.copy2(src, dst)
            staged_src.append(dst)
        # 分批调 soffice(单次多文件,一次启动)
        for i in range(0, len(staged_src), 25):
            chunk = staged_src[i : i + 25]
            try:
                subprocess.run(
                    [soffice_bin(), "--headless", "--convert-to", "pdf", "--outdir", str(tmp), *map(str, chunk)],
                    check=True, timeout=timeout, capture_output=True,
                )
            except Exception as e:
                print(f"  ⚠ soffice 批转失败({len(chunk)} 件):{type(e).__name__}")
        for _src, stem in srcs:
            produced = tmp / (stem.name + ".pdf")
            if produced.exists():
                final = batch_dir / (stem.name + ".pdf")
                shutil.move(str(produced), str(final))
                ok.append(final.name)
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo 入库装配 + 格式归一")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--batch-dir", required=True)
    ap.add_argument("--out", default="tools/doc_test/out/staged.jsonl")
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.inp).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("llm_corpus") in {"案例", "外规"}]
    batch_dir = Path(args.batch_dir)
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True)

    staged: list[dict] = []
    to_convert: list[tuple[Path, Path]] = []
    convert_meta: dict[str, dict] = {}
    n_copy = 0
    for i, r in enumerate(rows):
        src = Path(r["path"])
        ext = r["ext"]
        stem = batch_dir / f"D{i:04d}_{safe_stem(src.name)}"
        rec = {
            "corpus_type_code": r["corpus_type_code"],
            "sub_type": r.get("llm_sub_type"),
            "orig_path": str(src),
            "txt_twin": r.get("txt_twin"),
        }
        if ext in WHITELIST and src.exists():
            dst = batch_dir / (stem.name + "." + ext)
            shutil.copy2(src, dst)
            rec["filename"] = dst.name
            staged.append(rec)
            n_copy += 1
        elif ext in CONVERT and src.exists():
            to_convert.append((src, stem))
            convert_meta[stem.name + ".pdf"] = rec
        # 其它/缺失:跳过

    print(f"直拷(pdf/docx)：{n_copy} · 待转(doc/txt)：{len(to_convert)}")
    converted = convert_batch(to_convert, batch_dir)
    for fn in converted:
        rec = dict(convert_meta[fn])
        rec["filename"] = fn
        rec["converted"] = True
        staged.append(rec)
    n_fail = len(to_convert) - len(converted)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in staged), encoding="utf-8")
    case = sum(1 for s in staged if s["corpus_type_code"] == "P-CASE")
    ext = sum(1 for s in staged if s["corpus_type_code"] == "P-EXT")
    print(f"\n装配完成:批目录 {batch_dir}")
    print(f"  入批 {len(staged)} 件(案例 {case} · 外规 {ext})· 转换成功 {len(converted)}/{len(to_convert)}(失败 {n_fail})")
    print(f"  staged 清单:{args.out}")


if __name__ == "__main__":
    main()
