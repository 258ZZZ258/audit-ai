"""用 worker 驱动(_advance_one)把卡在管线中段的过渡态件(QC_PENDING/PARSING/STRUCTURING/
EMBEDDING/INDEXING)推到终态——reprocess 拒过渡态,这些搁浅件得靠 _advance_one 单件推进。
真文件 + __main__ guard:用 worker 上下文(embedding+milvus),mineru/多进程安全。"""

from __future__ import annotations


def main() -> None:
    from sqlalchemy import text

    from pipeline.cli import _advance_one, _worker_context
    from pipeline.index.pg_io import PgIO  # noqa: F401  (确保 import 副作用一致)

    pg, ctx = _worker_context()
    transient = ("REGISTERED", "QC_PENDING", "PARSING", "STRUCTURING", "EMBEDDING", "INDEXING")
    with pg.session() as s:
        ids = [
            r[0]
            for r in s.execute(
                text(
                    "select doc_version_id from doc_versions where pipeline_status = any(:t)"
                ),
                {"t": list(transient)},
            )
        ]
    print(f"驱动 {len(ids)} 件过渡态 → 终态…")
    done = 0
    for dvid in ids:
        try:
            _advance_one(pg, ctx, dvid)
            done += 1
        except Exception as e:  # noqa: BLE001 单件失败不阻断
            print(f"  ⚠ {dvid[:12]}: {type(e).__name__}: {str(e)[:80]}")
    print(f"已驱动 {done}/{len(ids)} 件")
    with pg.session() as s:
        for st, n in s.execute(
            text("select pipeline_status,count(*) from doc_versions group by 1 order by 2 desc")
        ):
            print(f"  {st}: {n}")


if __name__ == "__main__":
    main()
