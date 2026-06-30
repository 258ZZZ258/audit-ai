"""批量 degrade 所有 QC_FAILED → DEGRADED_INDEXED(全文可检索,完成其入库)。
单进程复用模型:dispose(degrade)+ _advance_one 驱动到终态,逐件隔离异常(#1 韧性精神)。
demo 收尾用:解析层 QC 失败的件以降级形态入库(仅全文检索、不参与条款级引用,T4 豁免)。"""

from __future__ import annotations


def main() -> None:
    from sqlalchemy import text

    from pipeline.cli import _advance_one, _drive_context
    from pipeline.config import load_config
    from pipeline.queue import dispose

    pg, ctx = _drive_context(load_config())  # worker 上下文(degrade 重入需 s5)
    with pg.session() as s:
        qids = [
            r[0]
            for r in s.execute(
                text(
                    "select rq.queue_id from review_queue rq "
                    "join doc_versions dv on dv.doc_version_id = rq.doc_version_id "
                    "where dv.pipeline_status = 'QC_FAILED' "
                    "and rq.queue_type = 'qc_fix' and rq.status = 'open'"
                )
            )
        ]
    print(f"degrade {len(qids)} 件 QC_FAILED → DEGRADED_INDEXED…")
    ok = 0
    fail = 0
    for qid in qids:
        try:
            outcome = dispose(pg, qid, "degrade", operator="cli")
            _advance_one(pg, ctx, outcome.doc_version_id)
            ok += 1
            if ok % 30 == 0:
                print(f"  …已处理 {ok}/{len(qids)}")
        except Exception as e:  # noqa: BLE001 单件失败隔离
            fail += 1
            print(f"  ⚠ {qid[:12]}: {type(e).__name__}: {str(e)[:80]}")
    print(f"完成:degrade {ok} 件,失败 {fail} 件")
    with pg.session() as s:
        for st, n in s.execute(
            text("select pipeline_status,count(*) from doc_versions group by 1 order by 2 desc")
        ):
            print(f"  {st}: {n}")


if __name__ == "__main__":
    main()
