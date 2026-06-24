# Plan: R4 多文档列举 —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-R4.md`(已批准:过滤范围=Milvus 标量+E1 义务、
> 输出=TABLE+citations)。延续 MVP/R2/R3/R6 范式(纯函数 + 节点薄封装、零 LLM、consumed-when-present)。
> **唯一承重改动 = `milvus_io.search` 加 `extra_expr`(add-only);零契约改动、零新依赖。**

## 1. 组件与依赖

```
listing/dimensions.py   extract_enum_spec(query, biz_terms, entity_terms) → EnumSpec(chunk_type_pref, biz_domains, entity_types, obligation_only)   (纯函数,规则)
        ▲
listing/r4_listing.py   build_milvus_expr(spec) → str | None         (纯函数,**防注入核心**:字段名白名单 + 值仅来自词典)
   │                    fetch_obligation_chunk_ids(pg, chunk_ids) → set[str]   (PG 只读,E1 后过滤;空→降级)
   └─ answer_enumerate(query, retriever, pg, qcfg) → QueryResult(route_type=enumerate)
        ├─ spec = extract_enum_spec(query, biz_terms, entity_terms)            [纯函数]
        ├─ expr = build_milvus_expr(spec)                                      [纯函数,白名单]
        ├─ cands = drop_degraded(retriever.retrieve_enumerate(q, extra_expr=expr, topk=enumerate_topk))   [Milvus 高 k + 标量预过滤]
        ├─ if spec.obligation_only: oblig=fetch_obligation_chunk_ids(...); cands=过滤(空→降级+note)        [PG E1 后过滤]
        ├─ 空 → refuse_coverage(scope, closest)                               [覆盖拒答]
        └─ 非空 → fetch_anchors(pg, ids) → 按 doc_version 聚合 → TABLE(JSON columns+rows+note)+ citations[] 四级锚点 + 边界声明 note
        ▲
retrieve/hybrid.py   retrieve_enumerate(query, *, extra_expr, topk)   (高 k 枚举检索,不截 top8;调 milvus.search(extra_expr=))
        ▲
pipeline/index/milvus_io.py   search(..., extra_expr: str | None = None)   (**add-only**:append 到 status/corpus 子句;extra_expr=None 与原行为等价)
        ▲
config.py   QueryConfig +enumerate_partition_topk(50) / enumerate_topk(50)
graph.py    ENUMERATE → _r4_listing 节点(替 placeholder)
```

**复用**:`contract`(`BlockType.TABLE`/`RouteType.ENUMERATE` **已存在**)、`state`、`understand.classify`(`SceneType.ENUMERATE` 已分类、`extract_terms`)、
`understand.router`(enumerate 已路由)、`generate.anchors.fetch_anchors`、`refuse.coverage_refusal.refuse_coverage`、`retrieve.hybrid.drop_degraded`、
`PgIO.session()`、`common.pg_models.ClauseTag`(E1 列)。
**零新依赖、零 LLM、零契约改动**(纯只读 + 新增 `listing` 子包 + `milvus_io.search` add-only 加参)。

> **vs SPEC §4 的细化**:`build_milvus_expr` 落 `r4_listing.py`(SPEC 同);该模块**模块级零 pipeline 导入**(Retriever/PgIO 经形参注入,
> pipeline 仅在不存在的路径),故防注入纯函数 `build_milvus_expr` 可被**零栈测试**。`dimensions.py` 纯规则、不导 pipeline/common。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `listing/dimensions.py`(纯函数,最先;全单元)
- `EnumSpec(frozen)`:`chunk_type_pref: bool`(默认 True)/`biz_domains`/`entity_types`/`obligation_only`。
- `extract_enum_spec(query, biz_terms=(), entity_terms=())`:规则——
  - `obligation_only` = query 含 **"要求/义务/必须/应当/禁止/不得"**(Q3);**"制度/规定/哪些"** 不触发。
  - `biz_domains`/`entity_types` = `extract_terms(query, biz_terms/entity_terms)`(词典子串,**只返词典成员**;dict 未注入→空)。
  - `chunk_type_pref` = True(Q5 硬偏好 clause)。
- **检查点 A**:`test_listing_dimensions` 绿(义务意图触发/不触发、词典抽取、**恶意串非词典成员→不进 spec**)。**零栈零模型**。

### Phase B — `r4_listing.build_milvus_expr`(防注入核心,纯函数;全单元 + 安全断言)
- `_FILTER_COL`/字段名白名单:`chunk_type`(VARCHAR)、`biz_domain`(ARRAY)、`entity_type`(ARRAY)——**只此三字段名可入 expr**。
- `build_milvus_expr(spec)`:
  - `chunk_type_pref` → `chunk_type == "clause"`(硬值,非用户串)。
  - `biz_domains` 非空 → `array_contains_any(biz_domain, [<词典值>])`(Q4);`entity_types` 非空同理(consumed-when-present:**仅当抽到词典词才加**,避免 E2 空数组 over-filter)。
  - AND 连接;全空 → `None`。
- **检查点 B**:`test_r4_listing`(独立函数节,零栈)绿——**安全断言**:expr 字段名 ∈ 白名单;`biz/entity` 值 ∈ 注入词典;**恶意 query 文本(`"; drop"`/`" or 1=1"`)不进 expr**(非词典成员被 `extract_terms` 丢弃);空 spec → None;`chunk_type_pref` expr 形正确。

### Phase C — `milvus_io.search` 扩展 + `retrieve_enumerate` + config(承重,守等价)
- `milvus_io.search` 加 `extra_expr: str | None = None`:`clauses` 末尾 append `extra_expr`(非空时)→ `" and ".join`;**`extra_expr=None` 时 `expr` 与原**(`SearchResult.expr` 不变);dense-only 兜底同步带 `extra_expr`。
- `retrieve/hybrid.retrieve_enumerate(query, *, extra_expr, topk, partition_topk=enumerate_partition_topk)`:同 `retrieve` 的分区配额循环,但用 enumerate k + 传 `extra_expr`;**不调 `retrieve`、零回归**(R1 路径不动)。
- `config.QueryConfig` +`enumerate_partition_topk=50`/`enumerate_topk=50`(Q2);env 无需覆盖。
- **检查点 C**:`pipeline/tests/test_milvus_search_expr` 绿——`extra_expr` 与 `status`/`corpus` **AND 拼接**正确(断言 `SearchResult.expr` 含子句)、**`extra_expr=None` expr 与原等价**(守不回归 R1/R3/R6);hybrid 与 dense-only 兜底两路都带 `extra_expr`。**单元用 fake collection / mock 断言 expr 串**(不需真 Milvus)。

### Phase D — `r4_listing.answer_enumerate`(编排 + 集成)
- `fetch_obligation_chunk_ids(pg, chunk_ids)`:`select(ClauseTag.chunk_id).where(chunk_id.in_(ids) & (tag_type=="is_obligation" | deontic_type.isnot(None)))` → set。
- `answer_enumerate`:retrieve_enumerate → (obligation_only 时)E1 后过滤(**oblig 空集 → 降级不过滤 + note "E1 义务标签未覆盖"**,consumed-when-present)→ 空 cands → `refuse_coverage` → 非空 → `fetch_anchors` → **按 `doc_version` 聚合**(同文档多条款合一行:制度名/文号/命中条款路径列表/页码范围/状态)→ TABLE(`{columns, rows, note}`,`stream=False`)+ `citations[]`(每命中条款一条四级锚点)+ **边界声明 note**"本列表基于已索引语料,不保证穷举外规(§15-③)";`route_type=enumerate`。
- **检查点 D**:`test_r4_listing`(fake retriever/pg:**按 doc 聚合**、E1 后过滤、E1 空→降级、E2 空→不过滤、空→拒答、边界 note 在)绿 + `test_r4_listing_integration`(**PG+Milvus+BGE-M3**:合成 2–3 文档同主题入索引 → 跨文档聚合、四级锚点真数据、手插 `is_obligation` clause_tags 验义务过滤、`chunk_type`/`biz_domain` extra_expr 真过滤)绿。

### Phase E — graph 接线 + 端到端
- `graph._r4_listing` 节点替 placeholder(`_TERMINAL[ENUMERATE]="r4_listing"`、`_build` 加节点+边、`_PLACEHOLDER_NOTE` 删 ENUMERATE);`_r4_listing` **懒导入** `answer_enumerate`(避 import 期拉 pipeline)。classify 需注入 biz/entity 词典 → 与现状一致(dict 未接 PG 加载,空降级;`_understand` 已抽 matters/entity_types,R4 复用 `state.scene`)。
- **检查点 E**:`QueryAgent.ask("哪些制度规定了客户身份识别")`→`route_type=enumerate` TABLE 端到端;`router`/golden 回归(enumerate 触发词不串到 R1);**全仓全量 + ruff 全绿;DAG 无环**。

## 3. 并行 vs 串行
A(dimensions)∥ B(build_milvus_expr)纯函数可并行编写 → C(milvus_io+hybrid+config,承重,独立可与 A/B 并行)→ D(依赖 A+B+C)→ E(接线)。
核心价值(枚举聚合 + 防注入 expr + add-only 检索扩展)分布 A/B/C/D,**纯函数 + 守等价测试全覆盖**。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **Milvus expr 注入**(红线)| 字段名**只来自白名单**(chunk_type/biz_domain/entity_type)、值**只来自词典抽取**(`extract_terms` 返词典成员);raw user 串绝不入 expr;`test_r4_listing` 断言恶意文本不进 expr |
| R2 | **`milvus_io.search` 扩展回归** R1/R3/R6 | **add-only**:`extra_expr=None` 时 expr **byte 等价**;`test_milvus_search_expr` 守;`retrieve_enumerate` 独立方法、不改 `retrieve` |
| R3 | **E1 义务 consumed-when-present**(clause_tags 空→过滤会清空)| oblig 空集 → **降级不过滤 + note**(非"丢光");E1 零-LLM 默认开通常有数据,集成手插验证 |
| R4 | **E2 Milvus 预过滤无法后验降级**(空数组→over-filter)| **仅当 query 抽到词典词才加** entity/biz 子句(dict 未注入→空→不加);集成注入 entity_type/biz_domain + dict 词验机制 |
| R5 | **跨文档聚合正确性** | 按 `doc_version` 分组、同文档多条款合一行;集成 2–3 同主题文档各成一行验证 |
| R6 | 枚举 k 值(召回完整性 vs 噪声)| `enumerate_partition_topk/topk` config 化(默 50/50);⚠ V0 标定;不激进截断 |
| R7 | `chunk_type=clause` 硬过滤排除 table/qa | MVP 声明(列举=条款,§2 偏好 clause);可退软偏好(权重而非过滤),留接缝 |
| R8 | pymilvus 全局连接顺序(R3 集成踩坑)| 新增 `test_r4_listing_integration` 检索用例 autouse 幂等 `mio.connect()` 重连(同 R3 修复) |

## 5. 可追溯(§6.4 → 组件 / 红线)
| §6.4 能力 | 组件 | 红线 |
|---|---|---|
| 规则维度抽取 | `dimensions.extract_enum_spec` | 零 LLM |
| 枚举模式高 k 不激进截断 | `hybrid.retrieve_enumerate` + config | 召回完整性 |
| Milvus 标量过滤(chunk_type/biz/entity)| `build_milvus_expr` + `milvus_io.search(extra_expr)` | **字段名白名单 + 值仅词典**,raw 串不入 |
| E1 义务过滤 | `fetch_obligation_chunk_ids`(clause_tags)| consumed-when-present,空→降级 |
| 去重 + 按 doc 聚合 + 四级锚点 | `answer_enumerate` + `fetch_anchors` | 条款逐字命中、锚点 PG 权威、无编造 |
| 列表化输出 | `answer_enumerate`(TABLE + citations)| 不保证穷举外规边界声明、空→覆盖拒答 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–E)· [x] 并行 · [x] 风险(含注入红线 + 承重等价)· [x] 可追溯
- [ ] **人工复核批准**
