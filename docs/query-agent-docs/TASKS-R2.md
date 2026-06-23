# Tasks: R2 变更查询 —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-R2.md` + `PLAN-R2.md`(已批准)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。集成 gate = 模型+PG+Milvus+soffice(无则 skip)。

- [ ] **T1:`change/version_diff.py`(纯函数 diff)**
  - Acceptance:`ClauseChange(clause_path_norm, kind, old_text, new_text)`;`diff_clauses(old, new)` 按 `clause_path_norm` 对齐 → 两侧 text 不等=`changed`、仅新=`added`、仅旧=`removed`、相等不计;同 path 去重;入参为含 `.clause_path_norm`/`.text` 的对象或 dict。
  - Verify:`pytest query/tests/test_version_diff.py`(零栈零模型)。
  - Files:`query/query/change/__init__.py`、`query/query/change/version_diff.py`、`query/tests/test_version_diff.py`。

- [ ] **T2:`change/r2_change.py`(编排 + PG helper + 纯组装)**
  - Acceptance:`resolve_version_pair(pg, dvid)`(→ logical 的 effective=current + 其 `supersedes_version_id` 前驱|None)、`fetch_clause_chunks(pg, dvid)`(非 parent/非 degraded/clause_path_norm 非空)、`fetch_revision`+`format_reason`(有→回查;无→明示"修订说明未提供…",**不推测**)、纯 `build_change_result(current, predecessor, changes, reason, citations)→QueryResult`(route_type=change;table[变更]+text[原因/背景占位];无前驱→明示"无历史版本");`answer_change(query, retriever, pg)` 编排。
  - Verify:`pytest query/tests/test_r2_change.py`(单元:`format_reason` 有/无、`build_change_result` 含无前驱分支、route_type=change、原因无推测)。
  - Files:`query/query/change/r2_change.py`、`query/tests/test_r2_change.py`。

- [ ] **T3:R2 集成(真栈双版本)**
  - Acceptance:复用 `version_demo` 双版本夹具(老→新真实 supersedes)+ 手插一条 `revision_notes` → `answer_change` 产出契约:版本对正确、条款级 diff 有变更项、修订原因回查到、变更条款四级引用;**答复不含推测性原因**。
  - Verify:`pytest query/tests/test_r2_change_integration.py`(栈未起/无模型 skip)。
  - Files:`query/tests/test_r2_change_integration.py`(+ 必要时 `query/tests/conftest.py` 加双版本 fixture)。

- [ ] **T4:graph R2 节点接线 + 端到端 + 收尾门**
  - Acceptance:`graph` 的 `_change` 节点实装(`CHANGE` 分支 placeholder → `answer_change`);`QueryAgent.ask("<变更问句>")` → `route_type=change` 端到端;`query_devlog.md` 记 R2 决策、`GAP.md` 勾 R2;全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`pytest query/tests/test_graph_integration.py`(加 R2 例);`.venv/bin/python -m pytest -q`;`.venv/bin/ruff check .`。
  - Files:`query/query/graph.py`、`query/tests/test_graph_integration.py`、`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`。

## 依赖与并行
T1(纯,最先)→ T2(依赖 T1)→ T3(依赖 T2,真栈)→ T4(依赖 T2/T3,接线+收尾)。基本串行;T1 单测与 T2 纯组装测可并行写。

## 覆盖 SPEC-R2 §8 成功标准
SC1/SC5 契约+四级引用→T2/T4;SC2 diff→T1;SC3 修订原因明示→T2;SC4 无前驱→T2;SC6 零 LLM→全程(R2 不调 LLM);SC7 集成+全仓门→T3/T4。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准
- [ ] **人工复核批准**
