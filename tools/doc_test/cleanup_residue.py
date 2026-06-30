"""收尾:① release 扫描件 quarantine(OCR 现已接入,重入解析)② reprocess 残余过渡态件
(STRUCTURING/QC_PENDING,多为调试期 fake-stage 污染、IR 缺失,全量重跑恢复)。单进程复用模型。"""

from __future__ import annotations


def main() -> None:
    from sqlalchemy import text

    from pipeline.cli import _advance_one, _drive_context, reprocess_to_indexed
    from pipeline.config import load_config
    from pipeline.queue import dispose
    from pipeline.states import PipelineState

    pg, ctx = _drive_context(load_config())

    # ① 扫描件 release → PARSING(OCR 重解析)→ 驱动
    with pg.session() as s:
        scan_qids = [
            r[0]
            for r in s.execute(
                text(
                    "select rq.queue_id from review_queue rq "
                    "join doc_versions dv on dv.doc_version_id = rq.doc_version_id "
                    "where dv.pipeline_status = 'QUARANTINED' and rq.status = 'open' "
                    "and rq.reason like '%扫描件%'"
                )
            )
        ]
    print(f"① release {len(scan_qids)} 扫描件(OCR 重解析)…")
    for qid in scan_qids:
        try:
            outcome = dispose(pg, qid, "release", operator="cli")
            _advance_one(pg, ctx, outcome.doc_version_id)
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ release {qid[:12]}: {type(e).__name__}: {str(e)[:70]}")

    # ② 残余过渡态件:force-reset REGISTERED → reprocess 全量重跑
    with pg.session() as s:
        residue = [
            r[0]
            for r in s.execute(
                text(
                    "select doc_version_id from doc_versions "
                    "where pipeline_status in ('STRUCTURING','QC_PENDING','PARSING','EMBEDDING','INDEXING')"
                )
            )
        ]
    print(f"② reprocess {len(residue)} 残余过渡态件…")
    ok = 0
    for dvid in residue:
        try:
            pg.transition(dvid, PipelineState.REGISTERED, actor="cli", detail={"reprocess": True})
            reprocess_to_indexed(pg, ctx, dvid, "cli")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {dvid[:12]}: {type(e).__name__}: {str(e)[:70]}")
    print(f"reprocess 成功 {ok}/{len(residue)}")

    with pg.session() as s:
        for st, n in s.execute(
            text("select pipeline_status,count(*) from doc_versions group by 1 order by 2 desc")
        ):
            print(f"  {st}: {n}")
        ing = s.execute(
            text(
                "select count(*) from doc_versions "
                "where pipeline_status in ('INDEXED','DEGRADED_INDEXED')"
            )
        ).scalar()
        print(f"已入库 {ing}/2944")


if __name__ == "__main__":
    main()
