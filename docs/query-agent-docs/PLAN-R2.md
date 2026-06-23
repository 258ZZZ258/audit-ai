# Plan: R2 变更查询 —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-R2.md`(已批准)。延续 MVP 范式(`PLAN.md` §2.5 可拓展性)。

## 1. 组件与依赖

```
change/version_diff.py   diff_clauses(old, new) → list[ClauseChange]   (纯函数,叶子)
        ▲
change/r2_change.py      answer_change(query, retriever, pg) → QueryResult
   ├─ 定位:retriever.retrieve → drop_degraded → top1 → dvid_hit
   ├─ 版本对:resolve_version_pair(pg, dvid_hit) → (current_effective, predecessor|None)   [PG]
   ├─ 取条款:fetch_clause_chunks(pg, dvid) → [(clause_path_norm, text, chunk_id)]          [PG,非 parent/非 degraded]
   ├─ diff:diff_clauses(old, new)
   ├─ 修订原因:fetch_revision(pg, current.dvid) → RevisionNote|None(缺失明示,绝不推测)
   └─ 组装:§6.2 四栏 → §10 契约(route_type=change;diff 表 + 原因文本;变更条款四级引用 via generate.anchors)
        ▲
graph.py  R2 节点实装(CHANGE 分支:placeholder → answer_change)
```

**复用**:`generate.anchors.fetch_anchors`(四级引用)、`retrieve.hybrid.Retriever`/`drop_degraded`、`contract`、`state`、`understand.router`(change 已分类)。**零契约改动、零新依赖、零 LLM**。

**新增 PG 只读 helper**(放 `change/r2_change.py`):`resolve_version_pair` / `fetch_clause_chunks` / `fetch_revision`。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `version_diff.py`(纯函数,最先;全单元可测)
- `ClauseChange(clause_path_norm, kind[added|removed|changed], old_text, new_text)` + `diff_clauses(old, new)`:按 `clause_path_norm` 对齐;两侧均有且 text 不等→changed、仅新→added、仅旧→removed、相等→不计。
- **检查点 A**:`test_version_diff` 绿(四类分类 + 对齐 + 同 path 去重);ruff。**零栈零模型**。

### Phase B — `r2_change.py`(编排 + PG helper)
- `resolve_version_pair(pg, dvid_hit)`:dvid→logical_id→该 logical 的 effective 版本=current;`current.supersedes_version_id`→predecessor(无则 None)。
- `fetch_clause_chunks(pg, dvid)`:非 parent、非 degraded、`clause_path_norm` 非空的块 → 列表。
- `fetch_revision(pg, dvid)` + `format_reason`:有→raw_text/entries;无→明示"修订说明未提供…"(**不推测**)。
- `answer_change(query, retriever, pg)`:定位→版本对→(无前驱→明示"无历史版本"契约)→双版本取块→diff→原因→§10 契约(answer_blocks: table[变更条款] + text[原因/背景占位];citations: 变更条款四级)。
- **检查点 B**:`test_r2_change`(纯部分:契约组装/原因格式/无前驱)绿 + `test_r2_change_integration`(真栈双版本 + 手插 revision_note)绿。

### Phase C — graph 接线
- `graph._change` 节点:`route_type==change` → `answer_change`(替换 placeholder 分支);`_TERMINAL` 加 `change→"change"` 节点。
- **检查点 C**:`QueryAgent.ask("<变更问句>")` → `route_type=change` 端到端;全仓全量 + ruff 全绿;DAG 无环。

## 3. 并行 vs 串行
A(纯 diff)→ B(编排,依赖 A)→ C(接线,依赖 B)。小切片,基本串行;A 的单测与 B 的纯组装测可并行编写。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | 定位歧义/top1 命中错制度 | drop_degraded + top1;无候选→明示无法定位(不臆造);§9-Q1 已认可暂不降级澄清 |
| R2 | 条款改号/移位 → diff 显示为 remove+add | 条款级 MVP 可接受,devlog/输出标注"按 clause_path_norm 对齐";字句级留后续 |
| R3 | `revision_notes` ingest 不填(仅人工录入)| 集成测试手插一条;真实场景人工录入(符合 §6.2);无则明示缺失 |
| R4 | 命中的是旧版(superseded)| `resolve_version_pair` 一律取 logical 的 effective 为 current、其前驱为 old;与命中哪版无关 |
| R5 | 定位需检索→需模型 | 集成 gate 模型;**纯 diff/原因逻辑全单元覆盖**(零模型),核心价值不依赖栈 |
| R6 | degraded 块入 diff/引用 | `fetch_clause_chunks` 排除 degraded(沿用契约)|

## 5. 可追溯(§6.2 四栏 → 组件 / 红线)
| §6.2 栏 | 组件 | 红线 |
|---|---|---|
| 版本 | resolve_version_pair | — |
| 变更内容 | diff_clauses | 不臆造条款(纯对齐) |
| 变更原因 | fetch_revision + format_reason | **缺失明示、绝不 LLM 推测**(test 断言) |
| 背景 | (占位"未纳入本期") | — |
| 四级引用 | generate.anchors | 从 PG 回查 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点 · [x] 并行 · [x] 风险 · [x] 可追溯
- [ ] **人工复核批准**
