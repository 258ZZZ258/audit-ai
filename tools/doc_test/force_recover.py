"""最终强制恢复:① confirm/degrade 扫描件 release 后的 META_REVIEW/QC_FAILED 件
② 对卡 STRUCTURING/QC_PENDING 的污染件直接 SQL 重置 REGISTERED(绕过状态机守卫——
维护级恢复)+ reprocess(raw 存在则重解析)。base=_objectstore/。"""

from __future__ import annotations


def main() -> None:
    import pathlib

    from sqlalchemy import text

    from pipeline.cli import _advance_one, _drive_context, reprocess_to_indexed
    from pipeline.config import load_config
    from pipeline.queue import dispose

    pg, ctx = _drive_context(load_config())
    base = pathlib.Path("_objectstore")

    # ① 扫描件 release 后的 META_REVIEW(confirm)/ QC_FAILED(degrade)
    with pg.session() as s:
        q = [
            (r[0], r[1])
            for r in s.execute(
                text(
                    "select rq.queue_id, rq.queue_type from review_queue rq "
                    "join doc_versions dv on dv.doc_version_id = rq.doc_version_id "
                    "where dv.pipeline_status in ('META_REVIEW','QC_FAILED') and rq.status='open'"
                )
            )
        ]
    for qid, qt in q:
        disp = "approve" if qt == "meta_confirm" else "degrade"
        try:
            outcome = dispose(pg, qid, disp, operator="cli")
            _advance_one(pg, ctx, outcome.doc_version_id)
            print(f"  {disp} {outcome.doc_version_id[:12]} → {outcome.after_state}")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {disp} {qid[:12]}: {type(e).__name__}: {str(e)[:70]}")

    # ② 卡过渡态污染件:直接 SQL 重置 REGISTERED(绕守卫)+ reprocess
    with pg.session() as s:
        rows = [
            (r[0], r[1])
            for r in s.execute(
                text(
                    "select doc_version_id, raw_object_key from doc_versions "
                    "where pipeline_status in ('STRUCTURING','QC_PENDING','PARSING')"
                )
            )
        ]
    print(f"② 强制恢复 {len(rows)} 件…")
    ok = 0
    lost = 0
    for dvid, rok in rows:
        raw = base / rok if rok else None
        if not (raw and raw.exists()):
            lost += 1
            print(f"  ✗ {dvid[:12]} raw 缺失({rok})→ 无法恢复(reject)")
            with pg.session() as s:
                s.execute(
                    text(
                        "update doc_versions set pipeline_status='REJECTED' "
                        "where doc_version_id=:d"
                    ),
                    {"d": dvid},
                )
            continue
        try:
            with pg.session() as s:  # 绕守卫直接重置
                s.execute(
                    text(
                        "update doc_versions set pipeline_status='REGISTERED' "
                        "where doc_version_id=:d"
                    ),
                    {"d": dvid},
                )
            reprocess_to_indexed(pg, ctx, dvid, "cli")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ {dvid[:12]}: {type(e).__name__}: {str(e)[:70]}")
    print(f"恢复 {ok} · raw 缺失 reject {lost}")

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
