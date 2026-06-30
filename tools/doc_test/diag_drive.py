"""诊断:逐件驱动搁浅件,捕获每个 stage 异常的完整 traceback(定位 drive-stranding 的原始触发)。
每件用引擎单步推进;异常打印完整 traceback + doc 信息,回滚 session 后继续下一件(隔离毒化)。"""

from __future__ import annotations

import traceback


def main() -> None:
    from sqlalchemy import text

    from common.pg_models import DocVersion
    from pipeline.cli import _build_stages, _can_run_s5, _worker_context
    from pipeline.orchestration import make_workflow_engine

    pg, ctx = _worker_context()
    engine = make_workflow_engine(pg, ctx, _build_stages(include_s5=_can_run_s5(ctx)))
    transient = ("REGISTERED", "QC_PENDING", "PARSING", "STRUCTURING", "EMBEDDING", "INDEXING")
    with pg.session() as s:
        ids = [
            r[0]
            for r in s.execute(
                text("select doc_version_id from doc_versions where pipeline_status = any(:t)"),
                {"t": list(transient)},
            )
        ]
    print(f"诊断驱动 {len(ids)} 件…")
    fails: dict[str, int] = {}
    advanced = 0
    for dvid in ids:
        for _ in range(20):  # 单件最多推 20 步
            dv = pg.get(DocVersion, dvid)
            if dv is None:
                break
            try:
                if not engine.step(dv):  # 无 stage → 停
                    break
                advanced += 1
            except Exception:  # noqa: BLE001
                tb = traceback.format_exc()
                key = tb.strip().splitlines()[-1][:120]
                fails[key] = fails.get(key, 0) + 1
                if sum(fails.values()) <= 3:  # 头 3 个异常打完整 traceback
                    print(f"\n===== 异常 @ {dvid[:12]} (态={dv.pipeline_status}) =====")
                    print(tb[-2500:])
                # 回滚毒化的 session
                try:
                    ctx.db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                break
    print(f"\n=== 汇总:推进 {advanced} 步 · 异常分类 ===")
    for k, n in sorted(fails.items(), key=lambda x: -x[1]):
        print(f"  [{n}×] {k}")


if __name__ == "__main__":
    main()
