# Plan: R6 统计型 —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-R6.md`(已批准,维度集/Q1/Q2/Q4/Q6/Q8 已决策)。
> 延续 MVP/R2/R3 范式(纯函数 + 节点薄封装、零 LLM 默认)。**零契约改动、零新依赖、不走向量检索。**

## 1. 组件与依赖

```
stats/dimensions.py   extract_stat_spec(query) → StatSpec(mode, group_by, metric, year_from/year_eq, org_like)   (纯函数,规则)
        ▲
stats/sql_builder.py  build_select(spec) → sqlalchemy.Select                                                     (纯函数,**防注入核心**)
        ▲             └─ 列只来自 GroupBy 白名单枚举 → 真实 Column;过滤值 → bound params;用户串绝不入 SQL
stats/r6_stats.py     answer_stats(query, pg) → QueryResult(route_type=statistical)
   ├─ spec = extract_stat_spec(query)
   ├─ stmt = build_select(spec)                                  [纯函数]
   ├─ rows = pg.session().execute(stmt).all()                   [PG 只读;无 Milvus/embedding]
   └─ 组表:rows → TABLE 块(JSON columns+rows);CATEGORY 全 NULL → 明示"未标注";空 → 明示
        ▲
graph.py  STATISTICAL → _r6_stats 节点(替 placeholder)
```

**复用**:`contract`(`BlockType.TABLE`/`RouteType.STATISTICAL` **已存在**)、`state`、`understand.classify`(statistical scene)、
`understand.router`(statistical 已路由)、`PgIO.session()`、`common.pg_models.Case`(ORM 列)。
**零新依赖**(SQLAlchemy 已在栈内)、**零 LLM**、**不触 Milvus/embedding**、**零契约改动**(纯只读 + 新增 `stats` 子包)。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `dimensions.py`(纯函数,最先;全单元)
- `GroupBy(StrEnum)`:CATEGORY/ORG/RESPONDENT_TYPE/YEAR(全 4 维,SPEC §9)。`StatSpec`(frozen):mode/group_by/metric/year_from/year_eq/org_like。
- `extract_stat_spec(query)`:规则——聚合词("高发/排名/占比/多少起/几起/数量分布/逐年/统计")→ aggregate;列表词("有哪些/列出/列表")无聚合词 → list;**歧义默认 aggregate**(Q8)。group_by 关键词映射(板块/事由→CATEGORY、机构/哪个局→ORG、年/逐年→YEAR、个人/对象类型→RESPONDENT_TYPE);**聚合无显式维度 → CATEGORY**(§6.6 主例)。metric:"金额/罚款/罚没/总额"→ sum_amount,否则 count(Q6)。过滤:regex `20\d{2}年` →"以来/起"→year_from、否则 year_eq。
- **检查点 A**:`test_dimensions` 绿(mode/group_by/metric/filter 各分支)。**零栈零模型**。

### Phase B — `sql_builder.py`(防注入核心,纯函数;全单元 + 安全断言)
- `_GROUP_COL = {CATEGORY: Case.violation_category, ORG: Case.penalty_org, RESPONDENT_TYPE: Case.respondent_type, YEAR: extract('year', Case.penalty_date)}`——**列只能来自此白名单**,绝不接受用户串。
- `build_select(spec)`:
  - aggregate:`select(group_col.label("key"), func.count().label("n") | func.sum(Case.amount_wan))`.group_by(group_col).order_by(metric desc)。
  - list:`select(Case.doc_version_id, ...卡片列).where(filters).order_by(Case.penalty_date.desc()).limit(_LIST_CAP)`。
  - filters:year_from→`extract('year', penalty_date) >= :p`、year_eq→`== :p`、org_like→`penalty_org.like(:p)`——**值全走 bound params**(SQLAlchemy 自动绑定)。
- **检查点 B**:`test_sql_builder` 绿——**安全断言**:`stmt.compile()` 的 `.params` 含绑定值、编译 SQL **无用户串拼接**;group/order 列 ∈ 白名单;恶意输入(`"; DROP TABLE cases;--"`、`"1 OR 1=1"`)经 `extract_stat_spec` → 不进 SQL 结构(落默认维度/被忽略)。**零栈零模型**。

### Phase C — `r6_stats.py`(编排 + 集成)
- `answer_stats(query, pg)`:spec→build_select→执行→组 TABLE 块(content=JSON `{columns, rows}`,`stream=False`);**CATEGORY 全 NULL** → 表注"违规事由未标注(L2 默认关)"(不臆造);**空结果** → 明示 TEXT;`route_type=statistical`、citations 空。
- **检查点 C**:`test_r6_stats`(纯部分:用 fake pg / 直拼 rows 验组表、全 NULL 注、空)绿 + `test_r6_stats_integration`(**PG-only**:插合成 cases+最小 doc_versions → 聚合计数降序、list 过滤排序正确)绿。

### Phase D — graph 接线 + 端到端
- `graph._r6_stats` 节点替 placeholder(`_TERMINAL[STATISTICAL]="r6_stats"`、`_build` 加节点+边、`_PLACEHOLDER_NOTE` 删 STATISTICAL);`_r6_stats` 懒导入 answer_stats。
- **检查点 D**:`QueryAgent.ask("哪些板块处罚高发")`→`route_type=statistical` TABLE 端到端;全仓全量 + ruff 全绿;DAG 无环。

## 3. 并行 vs 串行
A(dimensions)→ B(sql_builder,独立纯函数,可与 A 并行编写)→ C(依赖 A+B)→ D(接线)。核心价值(维度抽取 + 防注入 SQL 构造)全在 A/B 纯函数、单元全覆盖、不依赖栈。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **SQL 注入**(红线)| 列**只来自 GroupBy 白名单枚举**(真实 Column)、值**全 bound params**;用户串只经规则映射到枚举,绝不入 SQL;`test_sql_builder` 编译断言 parametrized |
| R2 | `violation_category` L2 默认空 → CATEGORY 聚合无数据 | **consumed-when-present**:聚合 over present;全 NULL → 表注"未标注(L2 默认关)";L1 维度(年/机构/对象/金额)真数据 |
| R3 | 集成 fixture FK 链(cases→doc_versions→documents→import_batches)| **PG-only** 直插最小 doc_versions+cases(不走 ingest/模型);按 FK 序建/反序清;gate=PG |
| R4 | `func.extract('year', date)` 跨 PG/方言差异 | 集成连真 PG 验证(非 SQLite);单元只断言 SQL 结构/参数,不跑真库 |
| R5 | 维度抽取规则歧义(机构 vs 对象类型) | 关键词优先级 + 歧义默认聚合 CATEGORY(Q8);LLM 维度抽取留接缝 |
| R6 | 列表型无聚合 → 实为过滤列表 | mode=list 明确建模(过滤+排序+limit),与 aggregate 分支隔离 |

## 5. 可追溯(§6.6 → 组件 / 红线)
| §6.6 能力 | 组件 | 红线 |
|---|---|---|
| 维度抽取(规则版)| `dimensions.extract_stat_spec` | 零 LLM |
| 参数化 SQL 防注入 | `sql_builder.build_select` | **白名单列 + bound params**,拒任意 SQL |
| 聚合执行 | `r6_stats`(pg.session) | 只读 cases、统计数字逐字 PG 聚合 |
| 表格化输出 | `r6_stats`(TABLE 块)| CATEGORY 缺失明示不臆造 |
| 不走向量检索 | (R6 全程无 Milvus/embedding)| §6.6 硬约束 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–D)· [x] 并行 · [x] 风险(含注入红线)· [x] 可追溯
- [ ] **人工复核批准**
