# GAP: 制度查询智能体 v1.0 设计 ↔ 当前实现差距盘点(迭代 backlog)

> 基线:2026-06-22。对照 `docs/制度查询智能体_技术框架设计_v1_0.md`(v1.0,功能1)与当前 `query/` MVP。
> 当前实现 = spec-driven MVP 切片(R1 依据查询 + 覆盖感知拒答 + 八路路由骨架),全仓 **440 passed / 0 failed**
> (真 BGE-M3)。SDD 三件见 `SPEC.md` / `PLAN.md` / `TASKS.md`,决策/踩坑见 `query_devlog.md`。
> 图例:✅ 已实现 · 🟡 部分(骨架/接缝/占位/务实版)· ❌ 未实现。
> **GAP 回答"做到哪了"(选下一轮);覆盖是否可确定见 `RTM.md`(116 条需求 → SPEC SC → test,✅=测试证明)。**

## 一句话
三条红线已在 **R1 闭环**(无编造引用 / 无裸结论 / 可解释拒答);**八路全实装(R5 收官)**;判定型经三段式硬约束
+ 代码后检无裸结论(§9.2 真复核接口+toggle,默认关)。**查询理解前端 N0/N1/N3 三节点收官**(N0 多轮归并+R7 闭环 / N1 HyDE /
N3 问题分解,均 LLM 为主默认开、真-LLM 门控就位待跑绿;N0 规则版离线兜底 / N1·N3 stub→no-op + V0 待标定),横切能力(真多
模型复核/权限/观测/流式/导出)未做。

---

## 1. 查询理解前端(§3,N0–N4)

| 节点 | 状态 | 说明 |
|---|---|---|
| N0 多轮上下文归并(指代消解/省略补全) | 🟡 | **实装**(SPEC/PLAN/TASKS-N0):`understand/merge.py` + graph `n0_merge` 节点(`START→n0_merge→understand`);**LLM 为主默认开**(`merge_context`:gateway 真 LLM / stub 规则版 / fail-safe 回落)+ **R7 澄清闭环**(原问+澄清答归并,跨请求重入)+ 代词/省略顺承;`ask(query, history=None)` + CLI `--history-json`。单轮 no-op byte 等价。真-LLM 闭环门控就位、本地无 key skip → **诚实 🟡**(待真 gateway 跑绿翻✅);深度指代靠真 LLM、规则版离线兜底;`dict` 未接 |
| N1 HyDE 改写 | 🟡 | **实装**(SPEC/PLAN/TASKS-N1):`retrieve/hyde.py` + `Retriever._dense_for` dense 接缝(镜像 §5.4 `_sparse_for`)。**LLM 为主默认开**(`hyde`:gateway 真 LLM 生成假设性法言 → `embed(原问+法言)` 作 dense / stub→`hyde_llm` 不建→原问 dense no-op / fail-safe 回落)。**只改 dense**(sparse 法言归 §5.4 dict);仅主 retrieve(R1/R5),enumerate/cases 不接;§7.1 污染兜底(不产引用)。真-LLM 生成门控就位、本地无 key skip → **诚实 🟡**;**默认值/召回收益待 §13 V0 第5组 A/B 实测**(§15-⑦) |
| N2 业务事项分类 | 🟡 | `classify.py` 规则版场景分类 + 词典子串抽取;非 LLM、词典需注入(未接 PG dict 加载)、`dict_scenario_terms` 桥接未做 |
| N3 问题分解 | 🟡 | **实装**(SPEC/PLAN/TASKS-N3):`retrieve/decompose.py` + `Retriever.retrieve()` fan-out 接缝(抽 `_search_candidates`)。**LLM 为主默认开**(`decompose`:gateway 真 LLM 拆复合问句为子查询 → 每子查询并行检索 → 候选**并集**综合 / stub→`decompose_llm` 不建→单查询 no-op / fail-safe 回落 `[query]`)。**仅复合问句触发**(LLM 拆 >1);单跳直通;`decompose_max_sub` 封顶;**不进 agentic 循环**(§0.3 一次性);仅主 retrieve(R1/R5),enumerate/cases 不接;§7.1 污染兜底。真-LLM 拆分门控就位、本地无 key skip → **诚实 🟡**;**复合占比/拆分质量待 §13 V0 实测** |
| N4 八路意图路由 | 🟡 | `router.py` 规则版分满 8 类 + 置信度;非 `dict_intent_routes` 训练分类器(合成置信度) |

## 2. 八路路由(§4 / §6)—— 核心差距

| 路由 | 状态 | 说明 |
|---|---|---|
| R1 依据查询(§6.1) | 🟡 大部分 | 混合检索✅ 充分性自检✅(务实) 引用约束生成✅ 四级锚点✅ **案例附挂✅**(R3,可关)**sparse 发文字号提权✅**(§5.4);缺:entity_type 强过滤❌ |
| R2 变更查询(§6.2) | ✅ 实装 | 版本链回查 + 条款级 diff + 修订原因回查(缺失明示、不推测)+ §6.2 四栏;背景栏/多跳/字句级 diff 留后续(见 SPEC-R2 §0) |
| R3 相似案例 + 案例桥接(§6.3) | ✅ 实装 | case 分区检索✅ + 要素回填卡片✅(一案一卡)+ 附挂到 R1✅(语义∪精确反查)+ 精确反查桥接原语✅(`cited_regulations` **consumed-when-present**,默认空降级语义-only);桥接-as-入口(behavior→R5)留后续(R5 占位)、L2 `cited_regulations` 生产/`case_summary` 强过滤留后续 |
| R4 多文档列举(§6.4) | ✅ 实装 | 枚举模式高 k(`retrieve_enumerate` 50/50,不激进截断)+ **Milvus 标量预过滤**(`chunk_type=clause` 硬偏好 + `biz_domain`/`entity_type`,扩 `milvus_io.search` 加 `extra_expr` add-only,防注入白名单)+ **E1 义务 PG 后过滤**(`clause_tags.is_obligation`,consumed-when-present 空降级)+ 按 doc 聚合 TABLE + 四级 citations + 不保证穷举外规边界声明;`entity_type`(E2 默认关)/biz 词典未接 PG 加载 → consumed-when-present;sparse 提权/重排留后续 |
| R5 判定型(§6.5) | ✅ 实装 | 三段式硬约束(① 依据四级锚点 ② 构成要件框定 clause直呈/LLM toggle ③ AI辅助/人工复核标识,**无 verdict 槽**)+ **不出裸结论代码后检**(`strip_bare_conclusion` verdict+试探性 always-on)+ 桥接入口(`resolve_cited_clauses` consumed-when-present)+ §9.2 复核接口+toggle(默认关)+ `review_required=true`;真多模型复核(Kimi)/LLM 构成要件抽取默认关、§15-④ demo workaround 待甲方确认 |
| R6 统计型(§6.6) | ✅ 实装 | 规则维度抽取✅ + 参数化 SQL(白名单 + bound params **防注入**)✅ + 聚合/列表 TABLE✅;`violation_category` **consumed-when-present**(L2 空降级明示);LLM 维度抽取/占比/字典评审留后续 |
| R7 需澄清(§6.7) | ✅ 闭环 | 触发✅ + 纯对话澄清块✅ + **澄清后回 N0 重新归并✅**(N0 实装,跨请求重入 `n0_merge`:调用方带 history 重问 → 原问+澄清答归并 → 重路由;`test_r7_closure_changes_routing`)|
| R8 兜底拒答(§6.8) | ✅ | `refuse_out_of_domain` |

> **八路全实装,无占位**(R5 收官)。`_placeholder` 节点保留为防御兜底(未知 route_type 仍落它)。

## 3. 检索与重排(§5)

| 项 | 状态 | 说明 |
|---|---|---|
| §5.1 混合检索 dense+sparse+RRF | ✅ | 复用 `milvus_io`;**dense 通道接 N1 HyDE**(`_dense_for`)+ **retrieve() 接 N3 分解 fan-out**(`_subqueries_for`+`_search_candidates`,复合问句子查询候选并集;默认 stub 单查询 no-op,见 §1 N1/N3)|
| §5.2 分区并行配额(内规∥外规 top25) | ✅ | `retrieve/hybrid` 双分区合并 |
| §5.3 强制过滤位 | 🟡 | status✅前置、perm_tag🟡(写入不过滤=设计意图);entity_type/biz_domain **机制已落**(R4 `extra_expr` 经 `milvus_io.search`,consumed-when-present)、E2 默认关+词典未接 PG 加载故默认不命中 |
| §5.4 sparse 精确通道(发文字号提权 + 词典扩展) | ✅ | **实装 + 单元 + 集成绿**(SPEC/PLAN/TASKS-SPARSE):查询层 `augment_sparse` —— 发文字号/全名 regex 检出 → 重 embed → token 加权并入 query sparse(保持 `RRFRanker`、零 pipeline 改动);`dict_scenario_terms`(v0-draft seed,consumed-when-present)口语→法言扩展;仅主 `retrieve`(R1/R5)、只动 sparse;`docnum_boost`/`scenario_expand` 默认关 byte 等价。**集成 `test_sparse_boost_integration` 3 passed**(干净栈+真 BGE-M3);系数 ⚠ §15 V0 标定;dict 内容 §15⑥ |
| §5.5 重排 bge-reranker top50→top8 | ✅ | 接缝实装(`rerank/reranker`:none passthrough 默认 / bge 本地 `FlagReranker`)+ Milvus rerank-hop(`search` `with_text`)+ 仅主 retrieve(R1/R5);`rerank=none` 默认 byte 等价;真 reranker 模型需 `QUERY_RERANK_MODEL`(缺则 skip,绝不联网)|
| §5.6 父子块供证 | ✅ | `fetch_parent_text` |
| §5.7 充分性自检 | 🟡 | 务实版,接口按 §8.1 保真 |

## 4. 生成与引用(§7)

| 项 | 状态 | 说明 |
|---|---|---|
| §7.1 引用 ID 注入式生成 | ✅ | `citation_inject` + `select_faithful` 代码级兜底 |
| §7.2 流式输出(Qwen3.5 首 token<3s) | 🟡 | **B-API 落地**:`pipeline.llm_client +stream`(httpx SSE)+ `generate_evidence_stream`(两次调用:chat_json 引用 + stream 正文)+ `api/sse.py` 端点(accepted→route→structured→answer_delta*→citations→done)。离线 stub 逐块✅;**真 gateway 首 token<3s 门控⏳待跑绿** |
| §7.3 四级锚点回查 | ✅ | `anchors`(PG 权威源) |
| §7.4 prompt 模板分路由 | ✅ | R1 引用注入 / R2 四栏 / R5 三段式硬约束 / R3 卡片 / R6 表格 各路由差异化 |

## 5. 覆盖感知拒答(§8)

| 项 | 状态 | 说明 |
|---|---|---|
| §8.1 分数阈值→覆盖语境判据 | 🟡 | 务实版(命中数);非"事项分区穷尽"完整判据,接口保真 |
| §8.2 覆盖感知拒答话术 + exhausted_scope | ✅ | `refuse_coverage` |
| §8.3 判定型框定三段式 | ✅ | R5 `build_framing` 三段式无 verdict 槽 + `strip_bare_conclusion` 不出裸结论 |

## 6. 横切能力(§9)—— 几乎全缺

| 项 | 状态 | 说明 |
|---|---|---|
| §9.1 模型网关 / 模型矩阵(CP-005) | 🟡 | LLM 接缝✅(stub 默认 / gateway 可选);Qwen3.5 主答 / Kimi 复核 / bge endpoint 未真接;MCP/SKILL❌ |
| §9.2 多模型复核(Kimi faithfulness) | ✅ | R5 `review_tentative` + **独立 `review_model`(Kimi)接线 + 喂条文原文**(与主答 Qwen 分离,默认关零网络 + fail-closed;`test_r5_review`/`test_llm_stub`/`test_query_config`✅);真 Kimi faithfulness 闭环 `test_r5_review_integration` 门控就位(RL-1 真-LLM 闭环)。**⏳ 待真 gateway+key 跑绿留痕**(本地无 key 未执行) |
| §9.3 敏感词过滤 | ❌ | 未做 |
| §9.3 AI 内容标识 | 🟡 | `contract.ai_label`✅;**B-API 导出 xlsx 含固定 AI 标识页脚**✅(`export_xlsx.AI_LABEL`);答复页脚/敏感词余项❌ |
| §9.3 权限 Casbin + 操作日志 | 🟡 | **B-API 鉴权接缝 stub**(`api/auth.py`:`Principal` + `require_export_permission`,导出点无权 403 语义 + 操作日志位就位)；真 Casbin 六类权限点 + SSO + 操作日志落地 ⏳ |
| §9.3 观测 Langfuse | 🟡 | **实装**(SPEC/PLAN/TASKS-OBSERVE):`observe.py` Tracer 接缝(`NoopTracer` 默认零网络 / `LangfuseTracer` 懒导入 + contextvar 串联 + flush + **fail-safe 吞**)+ `make_tracer`(observe 开+`LANGFUSE_*` creds → Langfuse,否则 Noop)。`QueryAgent.ask` 包 trace(终态归并句/scene/route_type)+ `Retriever` 发 HyDE/子查询 event 挂同一条 trace(单一 tracer + module contextvar)。**默认关 → Noop 零网络 byte 等价**、只读旁路(开/关 result 一致)、langfuse 可选 extra。真 Langfuse 门控就位、本地无 creds skip → **诚实 🟡**;深层 per-stage span 树/采样率留后续 |
| §9.3 SSO | ❌ | 未做 |

## 7. 契约 / 导出 / 容量 / V0 / 验收

| 项 | 状态 | 说明 |
|---|---|---|
| §10 输出契约 JSON | ✅ | 全字段(`contract.py`) |
| §11 导出 Excel | 🟡 | **B-API 落地**:`api/export_xlsx.build_export_xlsx`(问题/答复摘要/依据条款四级/相似案例/路由/导出人/时间 + AI 标识页脚)+ `POST …/export`(过导出权限点)。离线 xlsx 读回✅;真 Casbin 权限 + 模板库对接 ⏳ |
| §5.9 前端接缝(结构化四-Tab / 会话历史) | 🟡 | **B-API 落地**:`contract` 加法 `structured`(命中制度/条款/监管规则/相关案例)+ `api/structured` 装配 + FastAPI 端点(会话 CRUD/分页/搜索 + 问答同步/SSE + 条款回查 + 推荐 + 上传)+ PG `query_*` 会话表(迁移 0012)。离线 TestClient 全绿(330 passed);集成/迁移 apply 留合并门 |
| §12 容量与性能(QPS / P95 / 流式) | ❌ | 未涉及 |
| §13 V0 衔接(术语断层率 / HyDE A/B / 拒答标定 / 合成评估集 / RAGAS) | ❌ | 未做 |
| §14 验收对齐 | 🟡 | 依据验收✅(四级引用)、核心目标✅(红线);权限/安全/性能验收❌ |

## 8. 上游依赖资产消费(§2)

| 资产 | 状态 | 说明 |
|---|---|---|
| `audit_corpus` 混合检索 | ✅ | R1 消费 |
| PG `chunks` 四级回查 | ✅ | anchors |
| `cases` | ✅ | **R3 已消费**(要素回填卡片 + `cited_regulations` 精确反查)+ **R6 参数化 SQL 聚合/列表**;`violation_category`(L2)consumed-when-present |
| `clause_references` | ❌ | 空表(无 resolver),R1/R2 多跳未用 |
| `clause_tags` E1/E2 | 🟡 | **R4 已消费 E1 `is_obligation`**(义务后过滤,`fetch_obligation_chunk_ids`);期限(`norm_duration_days`)/E2 事项过滤未做 |
| `dict_*` | 🟡 | entity_types/biz_domains/departments 存在;**`dict_scenario_terms` v0-draft seed**(§5.4 查询层读 CSV;PG 表/灌库未建 → GAP #11,§15⑥)/ intent_routes 未建 |

## 9. §1.3 四个关键取舍落地

| 取舍 | 状态 |
|---|---|
| 查询理解前端 vs 裸检索 | 🟡 N2/N4 规则版;HyDE 未做 |
| 八路路由 vs 单一 RAG | ✅ 路由分满,形态隔离裸结论风险 |
| 引用 ID 注入 vs 自由生成 | ✅ |
| 覆盖感知拒答 vs 分数阈值 | 🟡 务实版 |

---

## 迭代 Backlog(按优先级)

### P0 — 红线 / 验收口径
1. ~~**R5 判定型**(构成要件框定 + 三段式 + 多模型复核接口)~~ ✅(SPEC/PLAN/TASKS-R5;§15-④ demo workaround 待甲方确认产品形态)
2. ~~**§9.2 真多模型复核**(Kimi faithfulness 真接)~~ ✅ 接线落地(PR #21:独立 `review_model` 与主答分离 + 默认关零网络 + fail-closed + 喂条文原文;单测✅、门控集成测就位)— **⏳ 待真 gateway+key 跑绿门控集成测留痕**(RL-1 真-LLM 闭环;本地无 key 未执行)
3. **§9.3 权限 Casbin + 操作日志** — 权限/安全验收

### P1 — 核心功能路由
4. ~~R2 变更查询~~ ✅ / ~~R3 相似案例+案例桥接~~ ✅ / ~~R6 统计型~~ ✅ / ~~R4 多文档列举~~ ✅(SPEC/PLAN/TASKS-R4)/ **R5 判定型(仅此一路仍占位)**
5. ~~§5.5 重排(bge-reranker)~~ ✅(SPEC/PLAN/TASKS-RERANK;接缝+本地 bge+none 默认等价)/ ~~§5.4 sparse 精确通道(提权+扩展)~~ ✅ 机制+单元+集成绿(SPEC/PLAN/TASKS-SPARSE)

### P2 — 查询理解前端
6. ~~N0 多轮归并 + R7 闭环~~ ✅ 实装(SPEC/PLAN/TASKS-N0;LLM 为主默认开 + 规则版离线兜底 + 真-LLM 门控就位⏳待跑绿)/
   ~~N1 HyDE~~ ✅ 实装(SPEC/PLAN/TASKS-N1;dense 接缝、HyDE 专管 dense、LLM 为主默认开 + stub no-op + fail-safe;门控⏳待跑绿、
   默认值/召回收益待 §13 V0 第5组 A/B,§15-⑦)/ ~~N3 问题分解~~ ✅ 实装(SPEC/PLAN/TASKS-N3;retrieve fan-out 接缝、复合拆
   子查询→候选并集、LLM 为主默认开 + stub no-op + fail-safe + §0.3 不迭代;门控⏳待跑绿、复合占比/质量待 V0)。**查询理解前端
   N0/N1/N3 三节点收官**(N2/N4 规则版已在 MVP)

### P3 — 横切 / 工程
7. §7.2 流式输出 / §11 导出 / §9.3 敏感词 / ~~Langfuse 观测~~ ✅ 实装(SPEC/PLAN/TASKS-OBSERVE;Tracer 接缝、默认关 Noop、contextvar 串联、fail-safe;门控⏳待跑绿)/ SSO / AI 标识页脚
8. §13 V0 评估(RAGAS / 术语断层率 / HyDE A/B / 合成评估集)

### 依赖资产缺口(可并行补)
9. ~~`cases` 消费(R3/R6 前提)~~ ✅ R3(要素回填 + 精确反查)+ R6(参数化 SQL 聚合/列表)已消费
10. `clause_references` resolver(R1/R2 多跳;表已建,数据/逻辑待补,见 `libs/common/common/pg_models.py` TODO)
11. `dict_scenario_terms` / `dict_intent_routes` 建表 + 灌种子(18 问 + 应用场景 + 真实日志);**`dict_biz_domains`/`dict_entity_types` 接 PG 加载注入 classify/R4**(现未接 → R4 biz/entity 过滤默认不命中)
12. ~~entity_type / biz_domain 检索前置过滤 → 扩 `pipeline.index.milvus_io.search` 接受附加 expr~~ ✅(R4 `extra_expr` add-only;E2 真打标 + 词典加载待补)
13. **`dict_issuer_codes`(机关代字字典)—— §15-V0**:§5.4 发文字号提权用**字符白名单**界定机关代字边界(口语前缀不卷入 + 文种字全覆盖故永不退化为裸〔年〕号);残留:机关**简称**冷僻用字会被截短(良性,仍含文种+核心)。彻底覆盖需机关代字字典/分词,列 §15-V0(系数标定同期)。见 `query/query/retrieve/sparse_boost.py` `_DAIZI`。

---

## 与文档 §15 待确认项(P0)的关系
GAP 里多项受 v1.0 §15 八项甲方/内部待确认阻塞(轻量小模型、sparse 双输出 endpoint、R5 产品形态、E2 外规覆盖、
cases 引用外规字段、字典评审、网关配额、MCP/SKILL 规范)。开工对应路由前先清相关确认项。
