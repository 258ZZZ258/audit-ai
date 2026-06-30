"""恢复驱动:应用 #1(run_until_idle per-doc 隔离)+ #2(chunker seq 去重)后,把搁浅的
过渡态件(STRUCTURING/INDEXING/EMBEDDING)推到各自停态。撞车件经 #2 修复后过 STRUCTURING→META_REVIEW。
之后由 `demo meta confirm --batch` 放行 META_REVIEW→INDEXED(本脚本只做 worker 驱动,不碰人工闸)。"""

from __future__ import annotations


def main() -> None:
    from sqlalchemy import text

    from pipeline.cli import _build_stages, _can_run_s5, _worker_context
    from pipeline.orchestration import make_workflow_engine

    pg, ctx = _worker_context()
    eng = make_workflow_engine(pg, ctx, _build_stages(include_s5=_can_run_s5(ctx)))
    steps = eng.run_until_idle()  # #1 隔离:坏件不连累整批;#2:撞车件 chunk 成功
    print(f"run_until_idle 推进 {steps} 步")
    with pg.session() as s:
        for st, n in s.execute(
            text("select pipeline_status,count(*) from doc_versions group by 1 order by 2 desc")
        ):
            print(f"  {st}: {n}")


if __name__ == "__main__":
    main()
