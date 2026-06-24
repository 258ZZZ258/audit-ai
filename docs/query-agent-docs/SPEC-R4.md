# Spec: R4 多文档列举(枚举模式高 k + E1 义务∩Milvus 标量过滤 + 按文档聚合列表)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md P1(backlog #4 / 依赖资产 #12)。延续
> MVP/R2/R3/R6 范式(纯函数 + 节点薄封装、零 LLM 默认、consumed-when-present)。上游设计:
> `制度查询智能体_技术框架设计_v1_0.md` §6.4 / §5.2-5.3 / §2 / §10。本文件只述 R4 增量。
> **已决(2026-06-24,AskUserQuestion)**:过滤范围 = **Milvus 标量 + E1 义务(clause_tags PG)**;
> 输出形态 = **TABLE + citations**。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **R4 路由实装**(替占位):`route_type=enumerate` —— **规则维度抽取** → **枚举模式高 k 检索**(不激进截断,确保召回完整性)→ **过滤**(① **Milvus 标量预过滤**:扩 `milvus_io.search` 加 `extra_expr`,**add-only**,GAP #12 —— `chunk_type=clause` 偏好 + `biz_domain` + `entity_type`,**consumed-when-present**;② **E1 义务 PG 后过滤**:义务意图问句 → `clause_tags.is_obligation` 过滤,**consumed-when-present**)→ **去重 + 按 `doc_version` 聚合** → **TABLE**(制度名/文号/命中条款/页码/状态)+ **citations[]** 四级锚点(同 R1,`fetch_anchors`)。空结果 → **覆盖感知拒答**;非空附**不保证穷举外规边界声明**。**全程零 LLM**。 |
| **不做** | LLM 维度抽取(规则 MVP)。E1 细粒度数值过滤(`deontic_type`/`norm_duration_days` 期限,MVP 只 `is_obligation`)。`entity_type` 真数据强过滤(E2 **默认关** → 机制 + fixture 验,不依赖真打标)。sparse 发文字号提权(§5.4)、bge-reranker(§5.5)。`clause_references` 多跳 resolver(空表)。**穷举外规保证**(§15-③ 声明不做)。Excel 导出(§11)、下钻链接。P-QA/P-CASE 分区(列举只打 P-INT/P-EXT,同 R1)。 |

## 1. Objective

让用户做**多文档列举**(§6.4),追求**召回完整性**而非 top8 精排:
- "哪些制度规定了 X""列出所有关于 Y 的制度" → 命中条款**按文档聚合**的列表(每项四级锚点)。
- "列出所有关于 Z 的**要求/义务**" → **E1 义务过滤** + 列表。

成功 = 列举问句返回 `route_type=enumerate` 契约,含 **TABLE**(按文档聚合)+ **citations** 四级锚点,
条款**逐字来自检索命中**、四级锚点 **PG 回查**;过滤 **consumed-when-present**(E1 义务有真数据、E2 entity/事项
默认空降级);**声明不保证穷举外规**;全程零 LLM。

## 2. Tech Stack(增量)

- 复用 `query/` 既有:`contract`(`BlockType.TABLE` / `RouteType.ENUMERATE` **已存在**)/`state`/`graph`(LangGraph)/
  `understand.classify`(`SceneType.ENUMERATE` 已分类;`extract_terms` 抽 biz/entity)/`understand.router`(enumerate 已路由)/
  `generate.anchors`(`fetch_anchors` 四级锚点)/`refuse.coverage_refusal`(`refuse_coverage`)。
- 复用 `pipeline` 脊柱:`Retriever`(混合检索)+ `PgIO.session()`(`clause_tags` 义务后过滤)+ `common.pg_models.ClauseTag`。
- **扩 `pipeline`**:`milvus_io.search` 加 **`extra_expr: str | None`**(append 到 status/corpus 子句,**add-only**,GAP #12)。
- 新增 `query/query/listing/`:`dimensions.py`(规则维度抽取)+ `r4_listing.py`(编排)。
- **零新依赖、零 LLM、不触额外模型加载**(embedding 复用 R1 检索栈)。

## 3. Commands

```bash
demo up                                               # R4 集成需 PG + Milvus + 本地 BGE-M3(同 R1/R3)
query ask "哪些制度规定了客户身份识别"                  # → route_type=enumerate 按文档聚合列表
query ask "列出所有关于反洗钱的要求"                    # → E1 义务过滤 + 列表
.venv/bin/python -m pytest query/tests/test_listing_dimensions.py query/tests/test_r4_listing.py \
  query/tests/test_r4_listing_integration.py pipeline/tests/test_milvus_search_expr.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/listing/
  __init__.py
  dimensions.py     # extract_enum_spec(query, biz_terms, entity_terms) → EnumSpec(chunk_type_pref, biz_domains, entity_types, obligation_only)  纯函数,规则
  r4_listing.py     # answer_enumerate(query, retriever, pg, qcfg) → QueryResult:枚举检索 → Milvus 预过滤(extra_expr) → PG 义务后过滤 → 按 doc 聚合 → TABLE + citations;含 build_milvus_expr / fetch_obligation_ids
pipeline/pipeline/index/milvus_io.py  # search 加 extra_expr(add-only,append 子句)
query/query/retrieve/hybrid.py        # retrieve_enumerate(query, *, extra_expr, topk)  高 k 枚举检索(不截 top8)
query/query/config.py                 # +enumerate_partition_topk / enumerate_topk
query/query/graph.py                  # ENUMERATE → r4_listing 节点(替 placeholder)
query/tests/
  test_listing_dimensions.py          # 纯单元:维度/过滤/义务意图抽取;恶意串不进 spec
  test_r4_listing.py                  # 单元(fake retriever/pg):按 doc 聚合、义务后过滤、E2 空降级、空→拒答、边界声明;build_milvus_expr 白名单+防注入
  test_r4_listing_integration.py      # 连真栈(PG+Milvus+BGE-M3):合成多文档 → 跨文档聚合、四级锚点真数据、义务过滤、Milvus extra_expr 真过滤
pipeline/tests/test_milvus_search_expr.py  # extra_expr 与 status/corpus AND 拼接正确;extra_expr=None 与原行为等价(不回归 R1/R3/R6)
docs/query-agent-docs/SPEC-R4.md / PLAN-R4.md / TASKS-R4.md
```

## 5. Code Style

沿用既有(中文 docstring、`from __future__ import annotations`、frozen dataclass、纯函数 + 节点薄封装)。
维度抽取与 expr 构造为纯函数;**Milvus expr 字段名只来自白名单,值只来自词典抽取**(`extract_terms` 返回的是
**注入词典的成员**,非 raw user 串):

```python
@dataclass(frozen=True)
class EnumSpec:
    chunk_type_pref: bool      # 列举偏好 clause(默认 True → 硬过滤 chunk_type=="clause")
    biz_domains: list[str]     # E2 涉及事项(词典抽取,空→不过滤)
    entity_types: list[str]    # E2 实体类型(词典抽取,空→不过滤)
    obligation_only: bool      # E1 义务意图("要求/义务/必须…")→ is_obligation 后过滤

def build_milvus_expr(spec: EnumSpec) -> str | None:
    """从 EnumSpec 构 Milvus 标量过滤 expr。字段名白名单(chunk_type/biz_domain/entity_type);
    biz/entity 值来自受限词典(array_contains_any);raw user 串绝不拼入。空 spec → None(不附加过滤)。"""
```

## 6. Testing Strategy

- **单元(零栈零模型)**:
  - `listing_dimensions`:enumerate 问句 → `chunk_type_pref` / `biz_domains` / `entity_types` / `obligation_only` 抽取;义务意图("要求/义务/必须/应当/禁止/不得")触发 `obligation_only`、"制度/规定"型不触发;**非词典串不进 spec**(`extract_terms` 只返词典成员)。
  - `r4_listing`(fake retriever/pg):高 k 候选 → **按 `doc_version` 聚合**(同文档多条款合并一行,列命中条款路径/数)→ TABLE 列正确;**E1 义务后过滤**(只留 `is_obligation` chunk);`biz/entity` 空 → **不过滤降级**;空结果 → `refuse_coverage`(`exhausted_scope` 非空);**边界声明 note 在**。
  - `build_milvus_expr`(**安全核心**):字段名白名单;`biz/entity` 值来自词典(**恶意 query 文本不进 expr**——非词典成员);`chunk_type` 偏好 expr 形;空 spec → None。
- **集成(gate = PG + Milvus + 本地 BGE-M3,同 R1/R3)**:合成**多文档**(同主题跨 2–3 个 `doc_versions`)入索引 → `answer_enumerate`:**跨文档聚合**(多 doc 各成一行)、四级锚点真数据、**E1 义务过滤**(手插 `is_obligation` clause_tags 验证)、**Milvus extra_expr 真过滤**(`chunk_type`/`biz_domain`)。
- **`pipeline` `test_milvus_search_expr`**:`extra_expr` 与 `status`/`corpus` 子句 **AND 拼接**正确;**`extra_expr=None` 时 expr 与原行为等价**(守不回归 R1/R3/R6 检索)。
- **红线断言**:列出条款**逐字来自检索命中**(无编造);四级锚点 **PG 权威回查**;过滤值**仅来自词典白名单**(无 raw user 串入 expr);**不保证穷举外规边界声明在**。

## 7. Boundaries

- **Always**:R4 **零 LLM**;**枚举模式高 k 不激进截断**;过滤 **consumed-when-present**(E1 义务有真数据、E2 空降级);四级锚点 **PG 回查**;**Milvus expr 字段名白名单 + 值来自受限词典**(raw user 串绝不入 expr);只读(不写源);**声明不保证穷举外规**。
- **Ask first**:**扩 `milvus_io.search`**(`pipeline` 承重检索层 —— 本切片确认 **add-only**:加可选 `extra_expr`,既有调用零行为变化,`test_milvus_search_expr` 守等价);改 `common` 契约 / PG schema(**预期零改动**,纯只读 + 新增 `query/listing` 子包);新增依赖。
- **Never**:**拼接 raw user query 进 Milvus expr** / 执行任意 expr;LLM 生成过滤条件;**臆造条款 / 四级锚点**;**向甲方承诺穷举外规**;改 `status`/`corpus` 既有过滤语义。

## 8. Success Criteria(可测)

1. `query ask "<列举问句>"` → `route_type=enumerate` 的 §10 契约,含 **TABLE**(按文档聚合,content=JSON columns+rows)+ **citations[]** 四级锚点。
2. **枚举模式**:高 k 检索(`enumerate_topk` > 默认 `topk`),按 `doc_version` 去重聚合(同文档多条款合一行,列命中条款路径/数);**不激进截断**(`test_r4_listing` + 集成)。
3. **Milvus 标量预过滤(GAP #12)**:`extra_expr` 加 `chunk_type=clause` 偏好 + `biz_domain`/`entity_type`(consumed-when-present);**`extra_expr=None` 时不回归既有检索**(`test_milvus_search_expr` 等价断言)。
4. **E1 义务后过滤**:义务意图问句 → `clause_tags.is_obligation` 过滤(consumed-when-present:clause_tags 空则不过滤);**"制度/规定"型不加 E1 过滤**(避免误缩)。
5. **安全(红线)**:`build_milvus_expr` 字段名白名单 + 值仅来自词典抽取;**恶意 query 文本不进 expr**(`test` 断言);raw user 串绝不拼入。
6. **边界声明**:输出含"本列表基于已索引语料,不保证穷举外规(E2 覆盖边界,§15-③)";**空结果 → 覆盖感知拒答**(`exhausted_scope` 非空)。
7. **零 LLM / 红线**:列出条款逐字来自检索命中,四级锚点 PG 权威;无编造。
8. R4 集成(PG+Milvus+BGE-M3 合成多文档)绿;全仓全量 + ruff 全绿;**DAG 无环**(`query → pipeline → common`)。

## 9. Open Questions(已决 2 项 + 默认待 gate 确认)

| # | 事项 | 处置(✅=AskUserQuestion 已定 / 默认待确认) |
|---|---|---|
| **过滤范围** | E1∩E2∩biz∩entity 切片范围 | ✅ **Milvus 标量(chunk_type/biz_domain/entity_type)+ E1 义务(clause_tags PG)**;E1 细粒度期限留后续。 |
| **输出形态** | 列表化块形态 | ✅ **TABLE(按文档聚合)+ citations[] 四级锚点**(沿用 R6 TABLE + R1 citations,前端已能渲染)。 |
| Q1 | 维度抽取 LLM vs 规则 | 默认规则 MVP(同 classify/R6 dimensions);LLM 留可选接缝。 |
| Q2 | 枚举 k 值 | 默认 `enumerate_partition_topk=50` / `enumerate_topk=50`(默认 25/8 放大);⚠ V0 标定,config 化。 |
| Q3 | E1 义务过滤触发词 | 默认规则:含 **"要求/义务/必须/应当/禁止/不得"** → `obligation_only`;**"制度/规定/哪些"** 型不触发(避免"列出制度"被误缩为义务)。 |
| Q4 | biz/entity ARRAY 匹配算子 | 默认 `array_contains_any`(命中任一即取);值来自 `extract_terms` 词典。 |
| Q5 | chunk_type 偏好:硬过滤 vs 软偏好 | 默认**硬过滤** `chunk_type=="clause"`(列举制度规定=条款;table 不在列举面);⚠ 可退软偏好。 |
| Q6 | 空结果处置 | 默认 `refuse_coverage`(`exhausted_scope`=识别事项 or 兜底);非空附边界声明 note。 |
| Q7 | 集成 fixture | 默认 **PG+Milvus+BGE-M3** 合成多文档(2–3 `doc_versions` 同主题),手插 `is_obligation` clause_tags 验义务过滤;gate 同 R1/R3。 |
| Q8 | TABLE content 形状 | 默认 JSON `{columns, rows[, note]}`(沿用 R3/R6);`stream=False` 原子块;`route_type=enumerate`。 |

## 10. 与文档 §15 / §6.4 边界的关系

- **§15-③(E2 对外规覆盖范围)→ R4 有效边界**:E2 **默认关** + 仅打标内规/外规子集 → "列出所有外规中关于 X"
  **无法保证完整**。R4 **consumed-when-present** 消费现有标量,**显式声明不保证穷举外规**(§6.4 + §15-③),
  **不向甲方承诺穷举**(边界声明)。**E1 义务标签(零-LLM 默认开)有真数据**;E2 entity/事项默认空降级。
- **GAP #12(扩 `milvus_io.search` expr)= 本切片落地的依赖资产**;**add-only**,守等价不回归 R1/R3/R6。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§7 Ask-first 扩 `milvus_io.search` **add-only**、§8 SC3/SC5 安全、§9 Q3/Q5)
