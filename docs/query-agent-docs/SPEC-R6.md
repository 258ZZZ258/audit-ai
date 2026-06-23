# Spec: R6 统计型(cases 参数化 SQL 聚合 + 规则维度抽取 + 防注入)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md P1(backlog #4 / 依赖资产 #9)。延续 MVP/R2/R3
> 范式(纯函数 + 节点薄封装、零 LLM 默认)。上游设计:`制度查询智能体_技术框架设计_v1_0.md` §6.6 / §10。
> 本文件只述 R6 增量。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **R6 路由实装**(替占位):`route_type=statistical` —— **规则维度抽取** → **参数化 SQL**(SQLAlchemy Core + bound params + **列白名单**,**防注入**)over `cases` 表 → **TABLE** 输出。两模式:**聚合型**(GROUP BY 维度 → COUNT / SUM(amount) 降序)+ **列表型**(date/org 过滤 → 按 `penalty_date` 降序列案例)。**全程零 LLM**、**不走向量检索**(§6.6)。 |
| **不做** | LLM 维度抽取(默认关;规则版 MVP)。`违规类别字典`(张老师评审,§6.6)→ `violation_category` 聚合按 **consumed-when-present** 降级。`cases` 字段完整率 ≥90% **闸**(摄取侧批次度量,非查询侧)。场景 5 舆情分析后台周期报告(§6.6 边界,另文)。跨表/跨语料统计(只 `cases`)。复杂时间表达(季度/月/相对日期)、多 metric 组合、聚合型的 top-N 下钻链接(列表型即列案例)。 |

## 1. Objective

让用户做**即问即答的轻量统计分析**(§6.6):
- **聚合型**:"哪些板块处罚高发" → 按 `violation_category` 分类计数表(降序);"哪个局处罚最多" → 按 `penalty_org`;"逐年处罚数" → 按年。
- **列表型**:"2024 年以来的处罚有哪些" → date 过滤 → 按 `penalty_date` 降序的案例列表(标题 + 机构 + 日期 + 类型)。

成功 = 统计型问句返回 `route_type=statistical` 契约,含 **TABLE**(聚合计数/列表),数据**逐字来自 PG `cases` 聚合**、
**SQL 全程参数化(防注入)**;`violation_category` 全空时**明示未标注**(不臆造);全程零 LLM。

## 2. Tech Stack(增量)

- 复用 `query/` 既有:`contract`(`BlockType.TABLE` / `RouteType.STATISTICAL` **已存在**)/`state`/`graph`(LangGraph)/
  `understand.classify`(statistical scene 已分类)/`understand.router`(statistical 已路由)。
- 复用 `pipeline` 脊柱:`PgIO.session()`(SQLAlchemy `Session`)+ `common.pg_models.Case`(ORM 列)。
  **SQL 经 SQLAlchemy Core/ORM 构造,bound params,绝不裸拼**。**零新依赖、零 LLM、不触 Milvus/embedding**。
- 新增 `query/query/stats/`:`dimensions.py`(规则维度抽取)+ `sql_builder.py`(白名单参数化查询)+ `r6_stats.py`(编排)。

## 3. Commands

```bash
demo up                                       # R6 集成仅需 PG(无模型、无 Milvus)
query ask "哪些板块处罚高发"                    # → route_type=statistical 聚合计数表
query ask "2024年以来的处罚有哪些"              # → route_type=statistical 案例列表(按日期降序)
.venv/bin/python -m pytest query/tests/test_dimensions.py query/tests/test_sql_builder.py query/tests/test_r6_stats.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/stats/
  __init__.py
  dimensions.py    # extract_stat_spec(query) → StatSpec(mode, group_by, metric, year_from/year_eq, org_like)  纯函数,规则
  sql_builder.py   # build_select(StatSpec) → SQLAlchemy Select;**列白名单 + bound params**,防注入  纯函数
  r6_stats.py      # answer_stats(query, pg) → QueryResult:维度抽取 → 构 SQL → 执行 → TABLE 块
query/query/graph.py   # STATISTICAL → r6_stats 节点(替 placeholder)
query/tests/
  test_dimensions.py             # 纯单元:维度/模式/过滤抽取
  test_sql_builder.py            # 纯单元:**防注入**(白名单强制、bound params、恶意输入不进 SQL 结构)
  test_r6_stats.py               # 单元(fake pg / SQLite):聚合计数、列表、空降级
  test_r6_stats_integration.py   # 连 PG(无模型):合成 cases 行 → 聚合/列表 SQL 正确
docs/query-agent-docs/SPEC-R6.md / PLAN-R6.md / TASKS-R6.md
```

## 5. Code Style

沿用既有(中文 docstring、`from __future__ import annotations`、frozen dataclass、纯函数 + 节点薄封装)。维度抽取与
SQL 构造为纯函数;**SQL 列只能来自白名单枚举,值走 bound params**:

```python
class GroupBy(StrEnum):
    CATEGORY = "violation_category"   # 事由/板块(L2,默认空)
    ORG = "penalty_org"               # 处罚机构(L1)
    RESPONDENT_TYPE = "respondent_type"  # 对象类型(L1)
    YEAR = "year"                     # penalty_date 年(L1)

@dataclass(frozen=True)
class StatSpec:
    mode: str                 # aggregate | list
    group_by: GroupBy | None  # 聚合维度(白名单枚举,非用户串)
    metric: str               # count | sum_amount
    year_from: int | None     # 过滤:年 >= (bound param)
    org_like: str | None      # 过滤:机构含(bound param)

def build_select(spec: StatSpec) -> Select:
    """白名单列 + bound params 构造 SQLAlchemy Select;用户输入只经枚举/绑定参数,绝不拼入 SQL。"""
```

## 6. Testing Strategy

- **单元(零栈零模型)**:
  - `dimensions`:关键词 → mode(聚合/列表)、group_by(事由/机构/对象/年)、metric(count/sum_amount)、过滤(year_from/org_like);默认("高发/排名"无显式维度)→ `violation_category` 聚合。
  - `sql_builder`(**安全核心**):列只来自白名单枚举;过滤值走 bound params;**恶意输入**("`; DROP TABLE cases;--`"、"`1 OR 1=1`")→ 不进 SQL 结构(编译 SQL 断言无用户串、parametrized);未知维度 → 安全默认。
  - `r6_stats`:聚合计数/降序、列表按日期降序、`violation_category` 全空 → 明示"未标注"(不臆造)。
- **集成(gate = PG;无模型、无 Milvus)**:插入若干**合成 cases 行**(+ 最小 `doc_versions`)→ `answer_stats`:聚合计数正确、列表过滤+排序正确、L1 维度真数据。
- **红线断言**:**SQL 全程 parametrized**(无用户串拼接);统计数字逐字来自 PG 聚合(不臆造);`violation_category` 缺失明示。

## 7. Boundaries

- **Always**:R6 **零 LLM**、**不走向量检索**;**防注入**(SQLAlchemy Core + bound params + **列白名单枚举**);只读 `cases`(不写源);`violation_category`/缺失维度**明示不臆造**;聚合 over present 值。
- **Ask first**:改 `common` 契约 / PG schema(**预期零改动**,纯只读 + 新增 `query/stats` 子包);新增依赖。
- **Never**:**拼接用户输入进 SQL** / 执行任意 SQL;LLM 生成完整 SQL(只允许填白名单参数,且本 MVP 用规则不用 LLM);臆造统计数字 / 编造 `violation_category` 分类。

## 8. Success Criteria(可测)

1. `query ask "<统计问句>"` → `route_type=statistical` 的 §10 契约,含 **TABLE** 块(content=JSON columns+rows)。
2. **聚合型**:GROUP BY 维度 COUNT 降序正确(`test_r6_stats` + 集成);"金额"问句 → SUM(amount_wan)。
3. **列表型**:date/org 过滤 + 按 `penalty_date` 降序的案例列表(标题/机构/日期/类型)。
4. **防注入(红线)**:`sql_builder` 列只来自白名单、值走 bound params;恶意输入不改变 SQL 结构;`test_sql_builder` 断言编译 SQL parametrized、无用户串拼接。
5. `violation_category` 全空 → 明示"违规事由未标注(L2 默认关)",**不臆造**;L1 维度(年/机构/对象/金额)有真数据。
6. **零 LLM / 不触 Milvus**:默认路径零 LLM/网络/向量检索。
7. R6 集成(PG-only 合成 cases)绿;全仓全量 + ruff 全绿;DAG 无环(`query → pipeline → common`)。

## 9. Open Questions(Q1/Q2/Q4/Q6/Q8 + 维度集 已人工决策 2026-06-23,锁定如下)

| # | 事项 | 处置(✅=已定 / 默认) |
|---|---|---|
| **维度集** | MVP 支持的 GROUP BY 维度 | ✅ **全 4 维**:`violation_category`(事由/板块,L2 空降级)+ `penalty_org`(机构)+ `year`(年)+ `respondent_type`(对象类型)。 |
| Q1 | 维度抽取 LLM vs 规则 | ✅ 规则 MVP(零-LLM,同 classify/router);LLM 识别维度留可选增强接缝。 |
| Q2 | `violation_category` L2 默认空 → 板块/事由聚合无数据 | ✅ **consumed-when-present**:聚合 over present 值;全空明示"违规事由未标注(L2 默认关)";L1 维度真数据。 |
| Q3 | TABLE `content` 形状 | 默认:JSON 字符串(`{columns:[...], rows:[[...]]}`),沿用 R3 Q4 卡片 JSON 约定;`stream=False` 原子块。 |
| Q4 | **防注入策略** | ✅ SQLAlchemy Core + **bound params** + **列白名单枚举**(硬约束);用户串绝不入 SQL。**拒任意 SQL / 拒 LLM 生成 SQL**。 |
| Q5 | 时间窗解析粒度 | 默认:"X 年以来"→`year>=X`、"X 年"→`year==X`(规则);季度/月/相对日期(近 3 月)留后续。 |
| Q6 | 聚合 metric | ✅ 默认 `count`;"金额/罚款/罚没"→ `sum(amount_wan)`。占比/多 metric 组合留后续。 |
| Q7 | 集成 fixture | 默认:**PG-only**,直插合成 `cases`(+ 最小 `doc_versions`),不走 ingest/模型;gate=PG(比 R3 轻)。 |
| Q8 | 列表型 vs 聚合型判定 | ✅ "有哪些/列出"(无聚合词)→ 列表;"高发/排名/占比/多少起/逐年/分布"→ 聚合;**歧义默认聚合**(§6.6 主例,按 `violation_category`)。 |

## 10. 与文档 §15 / §6.6 前提的关系

- §6.6 前提"`cases` 字段完整率 ≥90% 闸 + 违规类别字典经张老师评审":属**摄取侧数据质量**,**不阻塞**查询侧 R6
  实装——R6 **consumed-when-present** 消费现有 `cases`(L1 字段真数据;`violation_category` 空则明示)。**不向甲方
  承诺统计完整性/分类权威**(边界声明)。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§7 防注入红线、§8 SC4、§9 Q1/Q2/Q4/Q8)
