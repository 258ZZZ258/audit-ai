# Spec: R2 变更查询(制度版本变更:版本/内容/原因/背景)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md P1。延续 MVP 切片的包/范式/基础设施(见
> `SPEC.md`),本文件只述 R2 增量。上游设计:`制度查询智能体_技术框架设计_v1_0.md` §6.2 / §7.4。

## 0. 切片边界
| | 范围 |
|---|---|
| **做** | R2 路由**实装**(替换 MVP 占位):定位制度 → 版本链回查(PG)→ **条款级 diff** → 修订原因回查(`revision_notes`)→ §6.2 四栏输出 → §10 契约(`route_type=change`)。**零 LLM**。 |
| **不做** | 背景(同期监管案例 by 日期窗,§6.2 第4栏)留占位明示;多跳历史(只做**最近一跳**前驱);条款内文本级 diff(只做**条款级** added/removed/changed);修订说明条目与 diff 的 LLM 对齐(§6.2 ⚠) |

## 1. Objective
让用户查"某制度改了什么/何时改/为何改"。定位到当前现行版本与其**直接前驱版本**,产出**条款级变更**(新增/删除/修改)+ **修订原因**(权威取自 `revision_notes`,**缺失则明示、绝不 LLM 推测**)。成功 = 对变更型问句返回 `route_type=change` 的契约,含版本对、条款级 diff、修订原因(或缺失明示)、变更条款的四级引用。

## 2. Tech Stack(增量)
- 复用 `query/` 既有:`contract`/`state`/`graph`(LangGraph)/`understand.router`(change 已分类)/`generate.anchors`(四级回查)。
- 新增 `query/query/change/`:`version_diff.py`(纯函数 diff)+ `r2_change.py`(编排)。
- 数据:PG `doc_versions`(logical_id / supersedes_version_id / version_status)、`chunks`(clause_path_norm/text)、`revision_notes`(raw_text/entries)。**零新依赖、零 LLM**。

## 3. Commands
```bash
demo up                                  # R2 集成需真栈(PG;diff/回查不需模型,但定位用检索→需 BGE-M3)
query ask "合同管理办法什么时候修订的,改了什么"   # → route_type=change 契约 JSON
.venv/bin/python -m pytest query/tests/test_version_diff.py query/tests/test_r2_change.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)
```
query/query/change/
  __init__.py
  version_diff.py      # diff_clauses(old_chunks, new_chunks) → ClauseDiff(added/removed/changed/unchanged),纯函数
  r2_change.py         # answer_change(query, retriever, pg) → QueryResult:定位→版本对→diff→修订原因→契约
query/query/graph.py   # R2 节点接实装(替换 placeholder→change 分支)
query/tests/
  test_version_diff.py        # 纯单元:对齐/分类
  test_r2_change.py           # 单元(纯函数部分)
  test_r2_change_integration.py  # 连真栈:两版本 + revision_note → 契约
docs/query-agent-docs/SPEC-R2.md / PLAN-R2.md / TASKS-R2.md
```

## 5. Code Style
沿用既有(中文 docstring、`from __future__ import annotations`、dataclass 承载、纯函数 + 节点薄封装)。diff 为纯函数:
```python
@dataclass(frozen=True)
class ClauseChange:
    clause_path_norm: str
    kind: str            # added | removed | changed
    old_text: str | None
    new_text: str | None

def diff_clauses(old: list, new: list) -> list[ClauseChange]:
    """按 clause_path_norm 对齐两版本条款;text 不等=changed,仅一侧=added/removed。零 LLM。"""
```

## 6. Testing Strategy
- **单元**:`version_diff`(added/removed/changed/unchanged 分类、按 clause_path_norm 对齐、去重);`r2_change` 的修订原因格式化(present / absent 明示);无前驱明示。**零栈零模型**。
- **集成**(gate 同 MVP:模型+PG+Milvus+soffice):复用 `version_demo` 双版本夹具(老→新真实 supersedes)+ 手插一条 `revision_notes` → `query ask` 变更问句 → 契约含版本对 + diff + 修订原因 + 四级引用。
- **红线断言**:修订原因仅来自 `revision_notes`(无则明示"修订说明未提供",答复**不含任何推测性原因**);diff 不臆造条款。

## 7. Boundaries
- **Always**:R2 **零 LLM**(diff 机械、原因逐字回查);四级锚点从 PG 回查;degraded 块不入 diff 引用(沿用契约);定位失败/无前驱/无修订说明一律**明示缺失**。
- **Ask first**:改 `common` 契约 / PG schema(本切片应纯只读消费,**预期零契约改动**);新增依赖。
- **Never**:**LLM 推测变更原因**(§6.2 硬规则);臆造条款 diff;回写源系统。

## 8. Success Criteria(可测)
1. `query ask "<变更问句>"` → `route_type=change` 的 §10 契约;含版本对(当前+前驱 doc_version_id/issue_date/status)。
2. 条款级 diff 正确:同 clause_path_norm 文本不等→changed、仅新→added、仅旧→removed;`test_version_diff` 绿。
3. 修订原因:`revision_notes` 有→回查展示;无→明示"修订说明未提供,无法给出官方修订原因",**答复无推测**;`test_r2_change` 绿。
4. 无前驱版本(首版)→ 明示"无历史版本可比",不报错。
5. 变更条款带四级引用(当前版本 PG 回查)。
6. **零 LLM**:默认路径不发任何 LLM/网络调用(stub 都不需要——R2 不调 LLM)。
7. R2 集成端到端(真栈双版本)绿;全仓全量 + ruff 全绿;DAG 无环。

## 9. Open Questions
| # | 事项 | 默认处置 |
|---|---|---|
| Q1 | 定位制度:问句未点名制度时定位哪部?| MVP 用 R1 检索 top 命中的 doc_version → 取其 logical_id 现行版本 + 前驱;歧义则可降级 R7 澄清(本切片暂取 top1) |
| Q2 | 多版本历史(>1 前驱)| MVP 只 diff **最近一跳**;全链历史留后续 |
| Q3 | 条款内文本级 diff(高亮字句)| MVP 只到条款级(added/removed/changed);字句级 diff 后续 |
| Q4 | 背景栏(同期监管案例)| 本切片不做,契约里明示"同期监管背景:未纳入本期" |
| Q5 | 修订说明条目↔diff 对齐(§6.2 ⚠ LLM 辅助)| 不做(LLM);原样回查 revision_notes 全文/entries |

## 10. 验证清单(进 Phase 2 前)
- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§9 默认处置)
