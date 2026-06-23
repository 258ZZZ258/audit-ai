# Tasks: R6 统计型 —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-R6.md` + `PLAN-R6.md`(已批准,维度集/Q1/Q2/Q4/Q6/Q8 已决策)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。集成 gate = **PG only**(无模型/无 Milvus)。
> **零契约改动、零新依赖、零 LLM、不走向量检索。**

- [ ] **T1:`stats/dimensions.py`(规则维度抽取,纯函数)** — Phase A
  - Acceptance:`GroupBy(StrEnum)`(CATEGORY/ORG/RESPONDENT_TYPE/YEAR)+ `StatSpec`(frozen:mode/group_by/metric/year_from/year_eq/org_like);`extract_stat_spec(query)`:聚合词→aggregate、列表词无聚合词→list、**歧义默认 aggregate**;group_by 关键词映射(板块·事由→CATEGORY/机构→ORG/年·逐年→YEAR/对象·个人→RESPONDENT_TYPE),**聚合无显式维度→CATEGORY**;metric "金额·罚款·罚没·总额"→sum_amount 否则 count;过滤 regex `20\d{2}年`→"以来·起"→year_from 否则 year_eq。
  - Verify:`pytest query/tests/test_dimensions.py`(mode/group_by/metric/filter 各分支;零栈零模型)。
  - Files:`query/query/stats/__init__.py`、`query/query/stats/dimensions.py`、`query/tests/test_dimensions.py`。

- [ ] **T2:`stats/sql_builder.py`(防注入参数化 SQL,纯函数)** — Phase B(安全核心)
  - Acceptance:`_GROUP_COL` 白名单映射(CATEGORY→`Case.violation_category`/ORG→`Case.penalty_org`/RESPONDENT_TYPE→`Case.respondent_type`/YEAR→`extract('year', Case.penalty_date)`);`build_select(spec)→sqlalchemy.Select`:aggregate=`select(group_col, count|sum(amount_wan)).group_by(group_col).order_by(metric desc)`;list=`select(卡片列).where(filters).order_by(penalty_date desc).limit(_LIST_CAP)`;过滤值**全 bound params**。**列只来自白名单枚举,用户串绝不入 SQL**。
  - Verify:`pytest query/tests/test_sql_builder.py` —— **安全断言**:`stmt.compile()` `.params` 含绑定值、编译 SQL 无用户串拼接;group/order 列 ∈ 白名单;恶意输入(`"; DROP TABLE cases;--"`/`"1 OR 1=1"`)经 `extract_stat_spec`→不改变 SQL 结构(落默认维度/被忽略)。零栈零模型。
  - Files:`query/query/stats/sql_builder.py`、`query/tests/test_sql_builder.py`。

- [ ] **T3:`stats/r6_stats.py`(编排 + 组表,纯部分)** — Phase C
  - Acceptance:`answer_stats(query, pg)`:spec→build_select→`pg.session().execute(stmt)`→`QueryResult(route_type=statistical, answer_blocks=[TABLE 块 content=JSON {columns,rows}, stream=False])`;**CATEGORY 全 NULL→表注"违规事由未标注(L2 默认关)"**(不臆造);**空结果→明示 TEXT**;citations 空。
  - Verify:`pytest query/tests/test_r6_stats.py`(fake pg / 直拼 rows:聚合组表降序、全 NULL 注、空明示、list 形态)。
  - Files:`query/query/stats/r6_stats.py`、`query/tests/test_r6_stats.py`。

- [ ] **T4:R6 集成(PG-only 合成 cases)** — Phase C 检查点
  - Acceptance:PG-only fixture 直插最小 `import_batch`+`document`+N`doc_versions`+N`cases`(按 FK 序建/反序清,**不走 ingest/模型**)→ `answer_stats`:聚合计数降序正确(`func.extract('year')` 连真 PG)、list 过滤+日期降序正确、L1 维度真数据;统计数字逐字 PG 聚合。
  - Verify:`pytest query/tests/test_r6_stats_integration.py`(gate=PG;栈未起 skip;按 batch_id 反 FK 序清理)。
  - Files:`query/tests/test_r6_stats_integration.py`(+ `query/tests/conftest.py` 加 PG-only cases fixture)。

- [ ] **T5:graph 接线 + STATISTICAL 节点 + 端到端** — Phase D
  - Acceptance:`graph._r6_stats` 节点替 placeholder(`_TERMINAL[STATISTICAL]="r6_stats"`、`_build` 加节点+边、`_PLACEHOLDER_NOTE` 删 STATISTICAL,懒导入 answer_stats);`test_graph` 删占位 parametrize 的 STATISTICAL、加 `QueryAgent.ask("哪些板块处罚高发")`→`route_type=statistical`(fake pg,零栈);占位剩 R4/R5。
  - Verify:`pytest query/tests/test_graph.py`;PG-only 端到端在 T4 集成验证。
  - Files:`query/query/graph.py`、`query/tests/test_graph.py`。

- [ ] **T6:收尾(devlog/GAP/RTM)+ 全仓门** — Phase D 收口
  - Acceptance:`query_devlog.md` 记 R6 决策(防注入白名单+bound params、规则维度抽取、consumed-when-present CATEGORY、PG-only 集成 fixture)与踩坑;`GAP.md` 勾 R6;**`RTM.md` 更新 R6-dim/R6-sql/R6-table → ✅ 挂 test_id**(R6-precond 维持 consumed-when-present 备注),覆盖摘要重算;全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;R6 集成需 PG);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`。

## 依赖与并行
T1(规则)∥ T2(SQL,叶子纯函数)→ T3(依赖 T1+T2)→ T4(依赖 T3,真 PG)→ T5(依赖 T3,接线)→ T6(收尾+全仓门)。T1/T2 单测可并行写;T4 集成与 T5 接线共享 PG。

## 覆盖 SPEC-R6 §8 成功标准
SC1 route_type=statistical+TABLE→T3/T4/T5;SC2 聚合 GROUP BY COUNT 降序+sum_amount→T2/T3/T4;SC3 列表型过滤+日期降序→T2/T3/T4;SC4 **防注入红线**→T2;SC5 violation_category 全空明示→T3/T4;SC6 零 LLM/不触 Milvus→全程;SC7 集成+全仓门+DAG→T4/T5/T6。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC7)· [x] T6 同步更新 RTM(维护规则)
- [ ] **人工复核批准**
