# Plan: R3 相似案例 + 案例桥接 —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-R3.md`(已批准,Q1–Q4 已决策)。延续 MVP/R2 范式
> (`PLAN.md` §2.5 可拓展性、`PLAN-R2.md` 纯函数 + 节点薄封装)。**零契约改动、零新依赖、零 LLM。**

## 1. 组件与依赖

```
case/case_card.py    CaseCard + build_case_card(case_row, doc_meta) → AnswerBlock(CASE_CARD, json)   (纯函数,叶子)
        ▲
case/bridge.py       norm_ref(ref) + build_cited_index(pg) + cases_for_clauses(pg, clause_keys)      (PG 只读 + 纯归一)
        ▲                                                  └─ consumed-when-present:cited_regulations 空 → 返回 {}
case/r3_case.py      answer_case(query, retriever, pg, qcfg) → QueryResult(route_type=case)
   ├─ 检索:retriever.retrieve_cases(query) → drop_degraded → 候选(P-CASE 分区)
   ├─ 去重:按 doc_version_id **一案一卡**(同案多 chunk 保留更高分)→ 取 top-N
   ├─ 回填:pg.get_case(dvid) + pg.get(DocVersion, dvid) → (case_row, doc_meta)   [PG 权威]
   ├─ 组卡:build_case_card → [CASE_CARD blocks]
   └─ 空命中:明示"未检索到相似案例"(TEXT 块,不报错、不臆造)
   ─ attach_cases(result, query, citations, retriever, pg, qcfg) → 充分 evidence 答复尾挂
       └─ 语义:retrieve_cases(query) ∪ 精确反查:cases_for_clauses(pg, norm_ref(citations 外规条款))
          → 去重 → top-N(attach_topk)→ 追加 CASE_CARD 块(零命中不挂)
        ▲
retrieve/hybrid.py   Retriever.retrieve_cases(query) → list[Candidate]   (corpus="P-CASE",复用 milvus_io.search)
        ▲
graph.py             CASE → _r3_case 节点(替 placeholder);_evidence **充分分支**按 attach_cases 开关附挂
config.py            QueryConfig +attach_cases:bool=True / +attach_topk:int=3(读 [query] 段,env 可覆盖)
```

**复用**:`retrieve.hybrid.Retriever`/`drop_degraded`、`generate.anchors.fetch_anchors`(外规条款四级引用)、
`contract`(`BlockType.CASE_CARD`/`RouteType.CASE` **已存在**)、`state`、`understand.router`(case 已分类)、
`PgIO.get_case`/`PgIO.get(DocVersion, …)`/`PgIO.session()`。

**新增**:`query/query/case/`(三件)+ `Retriever.retrieve_cases` + `QueryConfig` 两字段 + graph 接线。
> 配置归位:`attach_cases`/`attach_topk` 放 **`[query]` 段 → `QueryConfig`**(与 `topk`/`partition_topk` 同源),
> **非** pipeline 摄取侧 `[toggles]`(那是 L2/E1/E2 开关)——SPEC §0 措辞统一到此。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `case_card.py`(纯函数,最先;全单元可测)
- `CaseCard`(frozen)= doc_version_id/title/penalty_org/penalty_date/respondent/penalty_type/amount_wan/
  violation_category/cited_regulations。`from_rows(case_row, doc_meta)` 组装(只读已落字段)。
- `build_case_card(case_row, doc_meta) → AnswerBlock(CASE_CARD, content=JSON 字符串)`:**L2 空字段省略**
  (violation_category=None / cited_regulations=[] 不进 JSON);标题取 doc_meta(PG 权威);**零臆造**。
- **检查点 A**:`test_case_card` 绿(present/absent 字段、JSON 形状、缺失省略);ruff。**零栈零模型**。

### Phase B — `bridge.py`(精确反查纯函数 + PG 索引;consumed-when-present)
- `norm_ref(doc_no, clause_path) → str`:发文字号/文号 + `clause_path_norm` 归一(复用 chunking 归一口径:
  半角/去空白/括号归一)——匹配契约键。
- `build_cited_index(pg) → dict[str, list[str]]`:扫 `cases` 中 **cited_regulations 非空**行 → `norm_ref → [dvid]`
  索引(默认路径 cited_regulations 全空 → 空索引;demo 规模全表扫可接受,生产换 JSONB GIN/containment,注释标注)。
- `cases_for_clauses(pg, clause_keys) → list[str]`:R1 citations 的外规条款 `norm_ref` 列表 → 命中索引 → 去重 dvid。
- **检查点 B**:`test_bridge` 绿(`norm_ref` 归一等价类、命中反查、未命中、**cited_regulations 空 → 降级 []/{}**);ruff。**零栈零模型**。

### Phase C — `retrieve_cases` + `r3_case.py`(编排 + 集成)
- `Retriever.retrieve_cases(query)`:`milvus_io.search(corpus="P-CASE")` 单分区召回 `partition_topk` → `Candidate` 列表(status==effective 前置复用)。
- `answer_case(query, retriever, pg, qcfg)`:检索 → drop_degraded → **按 dvid 去重一案一卡**(保留更高分)→ 取 top-N →
  `get_case`+`get(DocVersion)` 回填 → `build_case_card` → `QueryResult(route_type=case, answer_blocks=[卡片…])`;
  **空命中 / 无 cases 行** → 明示 TEXT 块(不报错、不臆造);get_case None 的命中跳过该卡。
- `attach_cases(result, query, citations, retriever, pg, qcfg)`:语义(retrieve_cases)∪ 精确反查
  (`cases_for_clauses(pg, [norm_ref(c) for c in citations])`)→ 去重 → top-N(attach_topk)→ **追加** CASE_CARD 块;零命中**不挂**。
- **检查点 C**:`test_r3_case`(纯部分:去重一案一卡、空命中明示、get_case None 跳过)绿 +
  `test_r3_case_integration`(真栈:ingest 处罚决定书 → `query ask` 案例问句 → `route_type=case` 卡片=PG 权威)绿。

### Phase D — graph 接线 + 附挂 + config
- `QueryConfig` +`attach_cases`/`attach_topk`;`load_query_config` 读 `[query]` 段;`settings.toml` 示例(注释标注可调)。
- `graph._r3_case` 节点替 placeholder(`_TERMINAL[CASE]="r3_case"`、`_build` 加节点+边);`_evidence` **充分分支**
  生成后:`if qcfg.attach_cases and route==evidence and scene!=definition: res = attach_cases(res, …)`(拒答分支**不**附挂)。
- **检查点 D**:`QueryAgent.ask("<案例问句>")` → `route_type=case` 端到端;`ask("<依据问句>")` → `evidence` + 默认尾挂**语义**案例卡;
  **手插** `cited_regulations` fixture(仿 R2 手插 revision_notes)→ 依据答复尾挂**精确反查**案例卡;
  全仓全量 + ruff 全绿;DAG 无环(`query → pipeline → common`)。

## 3. 并行 vs 串行
A(case_card)与 B(bridge)均叶子纯函数,**可并行编写**;C 依赖 A+B(组卡 + 反查);D 依赖 C(接线 + 附挂)。
集成测试集中在 C/D(模型 gate)。核心价值(组卡 / 反查 / 去重)全在 A/B/C 纯函数,**单元全覆盖、不依赖栈**。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | `cited_regulations` 默认空 → 精确反查无数据 | **consumed-when-present**:默认降级语义-only;fixture 手插验证机制;红线断言**无臆造引用**(SPEC SC4) |
| R2 | 同案多 chunk(case_summary+case_section)命中 | 按 `doc_version_id` **去重一案一卡**(保留更高分)|
| R3 | `chunk_type=case_summary` 主命中面无法过滤(milvus 未输出 chunk_type)| 一案一卡去重替代;case_summary 偏好留后续(GAP #12)|
| R4 | 附挂污染 R1 既有输出 / 过度推销 | 附挂为**追加 block**(既有 evidence/citation 块不变);`definition` 不挂、拒答分支不挂;`attach_cases` 可关 |
| R5 | `norm_ref` 归一与真实 JSONB shape 不符 | 定义匹配**契约** + fixture;真实 shape 随 L2 对齐落地校准(§15-⑤);`norm_ref` 归一逻辑单测覆盖 |
| R6 | 案例件无 `cases` 行(L1 抽取失败 / 未跑)| `get_case` None → 跳过该卡(不臆造);全空 → 兜底"未检索到相似案例" |
| R7 | 检索/ingest 需模型 | 集成 gate 模型;纯函数(组卡/反查/去重)全单元覆盖,核心价值不依赖栈 |

## 5. 可追溯(§6.3 能力 → 组件 / 红线)
| §6.3 能力 | 组件 | 红线 |
|---|---|---|
| case 分区语义检索 | `retrieve_cases` | `status==effective` 前置(复用 milvus_io)|
| 要素回填卡片 | `case_card` + `get_case`/`get(DocVersion)` | 逐字 PG 权威、L2 缺失省略、**不臆造** |
| 精确反查桥接(§6.3 CP-007)| `bridge.cases_for_clauses` | **consumed-when-present**、空降级、无臆造外规引用 |
| 附挂 top-N(§6.3 后置)| `attach_cases` | 仅真实命中、`definition`/拒答不挂、追加 block |
| 外规条款四级引用 | `generate.anchors` | 从 PG 回查(present 且可解析时进 citations,Q6)|

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–D)· [x] 并行 · [x] 风险 · [x] 可追溯
- [ ] **人工复核批准**
