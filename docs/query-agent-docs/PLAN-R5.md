# Plan: R5 判定型路由 —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-R5.md`(已批准:框定=clause直呈+LLM toggle、
> 红线=形态+代码后检+§9.2接口、入口=复用 R3 桥接)。延续 MVP/R2/R3/R4/R6 范式(纯函数 + 节点薄封装、
> 零 LLM 默认、consumed-when-present)。**零契约改动(`review_required` 已存在)、零新依赖、默认零-LLM。**

## 1. 组件与依赖

```
judge/framing.py   strip_bare_conclusion(text) → str        (纯函数,**红线核心**:verdict+试探性→中性/待核实)
        ▲          build_framing(clauses, query, llm, qcfg) → [AnswerBlock ②框定, ③标识]  (clause直呈;LLM抽取 toggle;②经 strip)
judge/review.py    review_tentative(blocks, citations, llm, qcfg) → [AnswerBlock]  (§9.2 接口;toggle 关→passthrough,开→第二LLM校验)
        ▲
judge/r5_judgment.py  resolve_cited_clauses(pg, case_dvids) → [chunk_id]   (桥接入口:cited_regulations→外规条款,consumed-when-present)
   └─ answer_judgment(query, retriever, pg, llm, qcfg) → QueryResult(judgmental, review_required=True)
        ├─ bridge = resolve_cited_clauses(pg, distinct dvid of retriever.retrieve_cases(query))   [默认空→[]]
        ├─ cands = drop_degraded(retriever.retrieve(query)) ∪ bridge                              [hybrid 内规+外规]
        ├─ 空 → refuse_coverage(scope, closest)                                                   [红线兜底,不出空 judgmental]
        ├─ citations = fetch_anchors(pg, ids)            [① 依据条款,四级锚点 PG 权威]
        ├─ blocks = build_framing(clauses, query, llm, qcfg)   [② 框定(strip)+ ③ AI辅助/人工复核标识]
        └─ blocks = review_tentative(blocks, citations, llm, qcfg)   [§9.2 接口]
        ▲
graph.py   JUDGMENTAL → _r5_judgment 节点(替 placeholder;删最后一个 _PLACEHOLDER_NOTE → 八路全实装)
config.py  QueryConfig +judge_constituent_llm(默认关)/judge_multimodel_review(默认关)
```

**复用**:`contract`(`RouteType.JUDGMENTAL`/`review_required` **已存在**)、`generate`(`sanitize_answer` 口径扩展 /
`select_faithful` / `citation_inject` / `anchors`)、`retrieve.hybrid`(`retrieve`/`retrieve_cases`/`drop_degraded`)、
`case.bridge`(`norm_ref`/`_norm`)、`refuse.coverage_refusal`、`llm`(stub/gateway)、`PgIO`、`common.pg_models`。
**零新依赖、零契约改动、默认零-LLM(stub)**(纯只读 + 新增 `judge` 子包)。

> **`judge` 模块级零 pipeline 导入**(Retriever/PgIO/llm 经形参注入;`drop_degraded` 就地 inline 同 R4)→ 纯函数
> `strip_bare_conclusion`/`build_framing` 可零栈测试。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `judge/framing.py`(红线核心 + 三段式,纯函数;全单元)
- `strip_bare_conclusion(text)`:`_VERDICT`(复用 R1:违规/违法/合规/合法)+ `_TENTATIVE`(可能违反/疑似违规/涉嫌/倾向于不合规/构成违)→ 命中替 `_NEUTRAL`("…是否构成违规须人工对照构成要件判断(本系统不作判定)")。
- `build_framing(clauses, query, llm, qcfg)`:② **clause直呈**(默认零-LLM:结构化呈现命中条款适用边界 + 框定模板语)；`qcfg.judge_constituent_llm` 开→ LLM 抽取适用前提/对象/行为类型(经 `strip_bare_conclusion`)；③ 固定 TEXT"AI 辅助判断,建议人工复核"。**无 verdict 槽**。
- **检查点 A**:`test_framing` 绿——`strip_bare_conclusion`(verdict+试探性→中性、纯依据文本不动)、三段式结构(② 框定 + ③ 标识、**无判定字段**)、clause直呈、LLM toggle 开/关。**零栈零模型**。

### Phase B — `judge/review.py`(§9.2 复核接口,toggle;单元)
- `review_tentative(blocks, citations, llm, qcfg)`:`qcfg.judge_multimodel_review` **关→passthrough**(原样返回)；**开**→ 第二 LLM 校验各块试探性表述是否被 `citations` 支持,不支持→ `strip_bare_conclusion` 降"待核实"。
- **检查点 B**:`test_framing`(或同文件 review 节)绿——toggle 关 passthrough;开(fake llm 返"不支持")→ 块被降级中性。**零栈零模型**。

### Phase C — `config` toggles + `judge/r5_judgment.py`(编排;纯部分)
- `config` +`judge_constituent_llm=False`/`judge_multimodel_review=False`。
- `resolve_cited_clauses(pg, case_dvids)`:`pg.get_case(dvid).cited_regulations` → `norm_ref` 键 → 反查外规条款 chunk(`doc_versions.doc_number` 归一匹配 + `chunks.clause_path_norm` 匹配,`version_status==effective`)；**consumed-when-present**:默认空→`[]`。
- `answer_judgment(query, retriever, pg, llm, qcfg)`:桥接(retrieve_cases→resolve)∪ hybrid(retrieve,drop_degraded 就地)→ 空→`refuse_coverage`→ `fetch_anchors`(①)→ `build_framing`(②③)→ `review_tentative`(§9.2)→ `QueryResult(judgmental, review_required=True, citations=①, answer_blocks=[②,③])`。
- **检查点 C**:`test_r5_judgment`(fake retriever/pg/llm:judgmental+review_required、三段式块、桥接 consumed-when-present(空→hybrid-only)、空→拒答、**默认无裸结论**、§9.2 toggle)绿。

### Phase D — R5 集成(PG+Milvus+BGE-M3)
- `test_r5_judgment_integration`:behavior 问句 → 三段式真数据、四级锚点 PG 权威、**断言输出无违规/合规裸结论**、**手插 `cited_regulations`** 验桥接入口(同 R3/R4 手插-复位)；autouse 幂等 `mio.connect()` 重连(R3/R4 踩坑预案)。
- **检查点 D**:`test_r5_judgment_integration` 绿(gate=PG+Milvus+BGE-M3;未起 skip)。

### Phase E — graph 接线 + 八路全实装 + router 回归
- `graph._r5_judgment` 节点替 placeholder(`_TERMINAL[JUDGMENTAL]="r5_judgment"`、`_build` 加节点+边、**`_PLACEHOLDER_NOTE` 清空**;`_r5_judgment` 懒导入 `answer_judgment`,传 `self._llm`/`self._qcfg`)；**`_placeholder` 节点保留为防御兜底**(`_route_edge` 未知 route 仍落它)；`test_graph` 删 R5 占位、加 `ask("…是否违规")`→judgmental+review_required+**无裸结论**(fake);`test_router` 八路覆盖回归。
- **检查点 E**:`test_graph`/`test_router` 绿;**八路全实装(无 route 仍打占位)**;端到端在 D 验证。

### Phase F — 收尾(devlog/GAP/RTM/devlog 时间轴)+ 全仓门
- `query_devlog.md` 记 R5 决策/踩坑;`GAP.md`(R5 ✅,**八路全实装**);`RTM.md`(R5 全组 R5-bridge/mix/elem/3seg/noraw/review/render + §8.3 + §7.4-R5 → ✅/🟡 挂 test_id,RL-1 真复核仍 🟡,§15-④ 标注 demo workaround);`docs/devlog.md` 加阶段 R5;全仓全量 + ruff 全绿、DAG 无环。
- **检查点 F**:全仓非模型门 + R5 模型门集成绿;ruff 全绿。

## 3. 并行 vs 串行
A(framing,红线纯函数)→ B(review,依赖 strip)→ C(编排,依赖 A+B+resolve)→ D(集成,依赖 C,真栈)∥ E(接线,依赖 C)→ F(收尾+全仓门)。A 的 `strip_bare_conclusion` 是红线叶子、最先且全覆盖。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **裸结论泄漏**(红线)| ①形态**无 verdict 槽** ②`strip_bare_conclusion` **always-on**(verdict+试探性)③§9.2 toggle;`test_framing` + 集成断言**任何路径无违规/合规裸结论** |
| R2 | LLM 框定 toggle 开 → 生成裸结论 | ② 框定 LLM 输出**过 `strip_bare_conclusion`**;默认 toggle 关(clause直呈零-LLM 无此风险) |
| R3 | 桥接 resolver consumed-when-present | `cited_regulations` 默认空→`resolve_cited_clauses` 返 `[]`→ hybrid-only;集成**手插**验机制(同 R3);`doc_number`/`clause_path_norm` 归一复用 `bridge.norm_ref` |
| R4 | §9.2 真复核未达(RL-1)| toggle 默认关 → 代码后检+形态保障;真-LLM 复核(Kimi)留 §9.2 另轮,RTM RL-1 维持 🟡(诚实) |
| R5 | behavior 误路由 | router 已含 判定型优先级(判定>统计>变更>列举>依据);`test_router` golden 回归 |
| R6 | 八路全实装后 placeholder 成 dead 分支 | `_placeholder` 节点**保留为防御兜底**(未知 route 仍落它,不删);`_PLACEHOLDER_NOTE` 清空 |
| R7 | pymilvus 全局别名顺序(R3/R4 踩坑)| `test_r5_judgment_integration` autouse 幂等 `mio.connect()` 重连 |
| R8 | §15-④ 产品形态越界 | 仅形态(依据+框定+标识)、`review_required=true`、**不承诺判定**;交付标注待甲方确认 |

## 5. 可追溯(§6.5/§8.3/§9.2 → 组件 / 红线)
| 设计能力 | 组件 | 红线 |
|---|---|---|
| 三段式硬约束(§8.3)| `framing.build_framing` | 无 verdict 槽 |
| 不出裸结论(§6.5/§0.1-1)| `framing.strip_bare_conclusion` | always-on,verdict+试探性→中性 |
| 构成要件框定(§6.5②)| `framing.build_framing`(clause直呈/LLM toggle)| 零-LLM 默认 |
| 案例桥接入口(§6.5/§6.3)| `r5_judgment.resolve_cited_clauses` | consumed-when-present,不臆造外规 |
| 多模型复核(§9.2)| `review.review_tentative` | toggle;校验试探性是否被引用支持 |
| 人工复核框(§6.5③)| `QueryResult(review_required=True)` | 前端差异化渲染;不承诺判定 |
| 四级锚点(§7.3)| `r5_judgment` + `fetch_anchors` | 条款逐字命中、PG 权威 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–F)· [x] 并行 · [x] 风险(含裸结论红线 + §15-④ 越界)· [x] 可追溯
- [ ] **人工复核批准**
