# RTM: 制度查询智能体 v1.0 需求可追溯矩阵(覆盖证明)

> 基线 2026-06-23(R1/R2/R3/R7/R8 实装,R6 SPEC 进行中)。对照 `docs/制度查询智能体_技术框架设计_v1_0.md`(v1.0,功能1)。
> **GAP.md 回答"做到哪了"(按 § 的进度盘点);RTM 回答"是否可确定覆盖了 v1.0"——把每条需求挂到 SPEC SC + 测试。**
> 二者并存:迭代时先看 GAP 选下一轮,收口时更新 RTM 验证覆盖。

## 怎么读

- **分母**:从 v1.0 §0–§14 + §1.3 取舍 + §2 资产逐条抽出的 **116 条原子功能需求**(由子代理通读全文提取)。这是"100% 覆盖"的基准集——❌ 行让缺口**显式可见**,而非"没列就看不见"。
- **状态**:`✅` 实装且有测试证据 · `🟡` 部分(务实版/接口保真/部分子需求/无专测) · `❌` 未实装 · `➖` 非查询逻辑(基建/容量)。
- **证据**:`✅` 必须挂 **SPEC-Rx §SC** + **test_id**——这是 RTM 相对 GAP 的关键升级:**✅ 是测试证明,不是断言**。**架构性满足但无专测的需求记 🟡**(待补回归测),不破例。
- **§15**:该需求受 v1.0 §15 待确认项①–⑧阻塞(见末尾图例)。注:多数 §15 项是**生产确认待办**,demo 侧已用 workaround 交付(本地 BGE-M3=②、consumed-when-present=⑤、规则=①、务实判据=⑥)。

## 覆盖摘要(可量化)

| | 数 | 占比 | 说明 |
|---|---|---|---|
| ✅ 实装+测试 | **30** | 26% | 红线 / R1 / R2 / R3 / R7 / R8 / 契约 / 四级锚点 / 混合检索 |
| 🟡 部分 | **27** | 23% | 务实版充分性/拒答判据、perm_tag 写不过滤、prompt 分路由、附挂触发边界、架构性无专测项、§14 验收部分项 |
| ❌ 未实装 | **58** | 50% | R4/R5/R6 路由、查询理解前端(N0/N1/N3)、§5.4/5.5、横切(§9 网关/复核/权限/观测/SSO)、§11–13 |
| ➖ 非查询逻辑 | **1** | — | §2.3 容量(摄取/部署) |
| **合计** | **116** | | |

- **红线(RL-1/2/3 + §0.1-2)**:核心引用真实性/四级回溯/可解释拒答 **✅**;"无裸结论"在 R1 路径 ✅(代码后检),真 LLM 下的 §9.2 复核 ❌ → RL-1 记 🟡。
- **八路路由**:R1🟡(主体✅,sparse提权/entity过滤/流式 ❌)· R2✅ · R3✅ · R7🟡(回 N0 缺)· R8✅ · **R4/R5/R6 ❌**(R6 SPEC 进行中)。
- **~47 行带 §15 待确认 caveat**,其中 R5 产品形态(④)、网关/Langfuse/Casbin/SSO 横切、V0 评估是 demo 阶段真正未触的大块。

---

## 矩阵(按 v1.0 § 分组)

### 红线 / §1.3 取舍 / §0 边界
| Req | 需求 | 状态 | 证据(SPEC §SC / test) | §15 |
|---|---|---|---|---|
| RL-1 | 无编造引用 / 无裸结论 | 🟡 | SPEC §8-红线;`test_evidence_guards`(sanitize/refuse)✅;真 LLM §9.2 复核 ❌ | ④ |
| RL-2 | 拒答可解释(穷尽分区+最接近 N 条) | ✅ | SPEC §8 SC3;`test_coverage_refusal` | ⑥ |
| RL-3 | 引用真实性 clause_id ⊆ 上下文 | ✅ | SPEC §8 SC2;`test_citation_faithfulness` | — |
| §0.1-2 | 依据四级回溯 | ✅ | SPEC §8 SC1;`test_anchors_integration` | — |
| §0.1-5 | 单向只读不回写 | 🟡 | 架构(无回写路径),待补回归测;各 SPEC §7 Never | — |
| §0.3 | 范围外不做(专业判断/比对/舆情) | 🟡 | R8 兜底 + 各 SPEC §0 边界;无专测 | — |
| TO-1 | 查询理解前端替代裸检索 | 🟡 | N2 规则版✅(`test_classify`);HyDE ❌ | ①⑦ |
| TO-2 | 八路路由形态隔离裸结论 | ✅ | SPEC §8 SC4;`test_router`/`test_graph` | — |
| TO-3 | 引用 ID 注入(只选不生成) | ✅ | `test_citation_inject`/`test_citation_faithfulness` | — |
| TO-4 | 覆盖感知拒答替代分数阈值 | 🟡 | 务实版命中数(`test_sufficiency`);事项分区穷尽完整判据 ❌ | ⑥ |

### §2 上游资产消费
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| §2-corpus | 消费 audit_corpus 混合检索 | ✅ | `test_hybrid_integration` | ② |
| §2-status | status=effective 强过滤 | ✅ | `test_hybrid_integration`/`test_anchors_integration` | — |
| §2-perm | perm_tag 前置权限过滤 | 🟡 | 写入✅过滤❌(M1 设计意图,与摄取侧一致) | — |
| §2-entity | entity_type[] 强过滤 | ❌ | milvus_io.search 未暴露 expr(GAP #12) | ⑥ |
| §2-biz | biz_domain/issuer_level/effective_date 圈定 | ❌ | 同上 | — |
| §2-chunktype | chunk_type 命中偏好 | ❌ | search 未输出 chunk_type(R3 用 dvid 去重替代) | — |
| §2-chunks | PG chunks 全文+父块权威源 | ✅ | `test_anchors_integration`(fetch_texts/parent) | — |
| §2-docver | doc_versions+revision_notes 变更源 | ✅ | `test_r2_change_integration` | — |
| §2-cases | cases 桥接反查+卡片+SQL源 | ✅ | `test_r3_case_integration`/`test_bridge`;SQL(R6)❌ | ⑤ |
| §2-clauseref | clause_references 多跳查表 | ❌ | 空表无 resolver(GAP #10) | — |
| §2-tagsE1 | E1 义务/期限过滤 | ❌ | 未消费 | — |
| §2-tagsE2 | E2 事项/部门/entity 过滤 | ❌ | 未消费 | ③⑥ |
| §2-scenario | dict_scenario_terms 桥接+扩展 | ❌ | 未建表 | ⑥ |
| §2-introutes | dict_intent_routes 路由样例 | ❌ | 未建表(用内置规则种子) | — |
| §2-entitydict | dict_entity_types 抽取约束 | 🟡 | classify 可注入;未接 PG 加载 | ⑥ |
| §2-role | 三类语料角色分工 | 🟡 | 架构(分区路由),待补回归测;R1/R2/R3 消费 | — |
| §2.3 | 单机 standalone 容量 | ➖ | 摄取/部署侧,非查询逻辑 | — |

### §3 查询理解前端 / §4 路由
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| N0 | 多轮上下文归并 | ❌ | QueryState.history 占位 | — |
| N0-nocheck | 澄清纯对话不出复选框 | ✅ | `test_graph`(clarify=CLARIFY_QUESTION) | — |
| N1 | HyDE 改写 | ❌ | 未做 | ①⑦ |
| N1-fail | HyDE 失败回落原句 | ❌ | N1 未做 | — |
| N1-decision | HyDE on/off V0 A/B 标定 | ❌ | V0 未做 | ①⑦ |
| N2-scene | 场景类型标签 | ✅ | `test_classify` | — |
| N2-event | 涉及事项标签(E2 字典) | 🟡 | extract_terms✅;未接 PG dict 加载 | ⑥ |
| N2-entity | entity_type 抽取 | 🟡 | extract_terms✅;未用于过滤 | ⑥ |
| N2-bridge | scenario_terms 口语→法言 | ❌ | 词典未建 | ⑥ |
| N3 | 问题分解 | ❌ | 未做 | — |
| N3-noloop | 不进 agentic 循环 | 🟡 | 架构(单跳直通);无专测 | — |
| §3-degrade | 前端三节点可降级 | 🟡 | classify/router 降级✅;N0/N1/N3 缺 | — |
| N4 | 八路意图路由+置信度 | ✅ | `test_router`(规则版,合成置信度) | — |
| §4.3-conf | 低置信→R7 澄清 | 🟡 | clarify 触发✅;置信度阈值门 部分 | — |
| §4.3-prio | 多标签优先级裁决 | ✅ | `test_classify`/`test_router`(_RULES 序) | — |

### §5 检索与重排
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| §5.1 | dense+sparse+RRF 混合 | ✅ | `test_hybrid_integration` | ② |
| §5.2 | 分区并行配额 top25 | ✅ | `test_hybrid_integration` | — |
| §5.3 | 强制过滤位 | 🟡 | status✅ perm_tag🟡 entity/biz❌ | ⑥ |
| §5.3-hist | 问历史放开 status | 🟡 | include_superseded 参数(R2 用) | — |
| §5.4 | sparse 发文字号提权+扩展 | ❌ | 默认 RRF 序 | ⑥ |
| §5.5 | bge-reranker top50→top8 | ❌ | 默认 rerank=none(接缝预留) | — |
| §5.6 | 父子块供证 | ✅ | `test_anchors_integration`(fetch_parent_text) | — |
| §5.7 | 充分性自检→覆盖判据 | 🟡 | 务实版(`test_sufficiency`) | ⑥ |

### §6 八路路由
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| R1-mix | 混合检索∥案例桥接 | ✅ | `test_r1_integration`;桥接=R3 附挂✅ | — |
| R1-filter | 重排+status/perm/entity 过滤 | 🟡 | status✅;rerank/entity ❌ | — |
| R1-suff | 充分性→生成/拒答 | ✅ | `test_r1_integration`/`test_sufficiency` | ⑥ |
| R1-gen | 引用约束生成+案例附挂+导出 | 🟡 | 生成✅ 附挂✅(R3);流式/导出 ❌ | — |
| R1-sparse | 发文字号 sparse 提权+entity 强过滤 | ❌ | 见 §5.4 / §2-entity | — |
| R2-version | 版本栏(版本链) | ✅ | `test_r2_change_integration` | — |
| R2-diff | 条款级 diff | ✅ | `test_version_diff` | — |
| R2-reason | 修订原因逐字+缺失明示禁推测 | ✅ | `test_r2_change`(format_reason) | — |
| R2-bg | 背景栏同期案例 | ❌ | 占位"未纳入本期" | ⑤ |
| R2-align | 修订条目↔diff LLM 对齐 | ❌ | 不做(LLM) | — |
| R3-bridge | 桥接-as-入口(行为咨询) | ❌ | R5 占位,入口未做 | ⑤ |
| R3-attach | 附挂通道(语义∪精确反查) | ✅ | `test_r3_case`/`test_graph_integration` | ⑤ |
| R3-trigger | 桥接仅行为咨询触发 | 🟡 | 附挂边界 definition 排除;入口未做 | — |
| R3-similar | 纯相似案例 case 检索→卡片 | ✅ | `test_r3_case_integration`(cited consumed-when-present) | ⑤ |
| R4-filter | E1∩E2∩biz∩entity 过滤 | ❌ | 占位 | ③⑥ |
| R4-mode | 枚举高 k 不激进截断 | ❌ | 占位 | — |
| R4-bound | 声明不保证穷举外规 | ❌ | R4 未做 | ③ |
| R5-bridge | 案例反查→外规定位 | ❌ | 占位 | ⑤ |
| R5-mix | 内+外规补充候选 | ❌ | 占位 | — |
| R5-elem | 构成要件提取(LLM) | ❌ | 占位 | — |
| R5-3seg | 三段式硬约束输出 | ❌ | 占位 | ④ |
| R5-noraw | 不出违规/合规裸结论 | ❌ | R5 占位(R1 路径有代码后检) | ④ |
| R5-review | 多模型复核 | ❌ | 未做 | — |
| R5-render | route_type=judgmental 人工复核框 | ❌ | 占位 | ④ |
| R5-noloop | 单轮不进推理循环 | ❌ | R5 未实装 | — |
| R6-dim | 维度抽取 | ❌ | **SPEC-R6 进行中**(规则版) | ⑤ |
| R6-sql | 参数化 SQL 防注入 | ❌ | **SPEC-R6 进行中** | ⑤ |
| R6-table | 表格化输出+下钻 | ❌ | **SPEC-R6 进行中** | — |
| R6-precond | cases 完整率≥90%+字典评审 | ❌ | 摄取侧前提(consumed-when-present 不阻塞) | ⑤⑥ |
| R7 | 单问题纯对话澄清+回 N0 | 🟡 | 触发✅(`test_graph`);回 N0 ❌(N0 缺) | — |
| R8 | 兜底拒答 | ✅ | `test_graph`(refuse_out_of_domain) | — |

### §7 生成 / §8 拒答
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| §7.1 | 引用 ID 注入式生成 | ✅ | `test_citation_inject`/`test_citation_faithfulness` | — |
| §7.2 | 流式输出 首 token<3s | ❌ | contract.stream 字段未真推送 | — |
| §7.3 | 四级锚点 PG 回查 | ✅ | `test_anchors_integration` | — |
| §7.4 | prompt 模板分路由 | 🟡 | R1✅ R2 四栏✅(文本);R5 三段式 ❌ | ④ |
| §8.1 | 覆盖语境判据(事项分区穷尽) | 🟡 | 务实版(`test_sufficiency`);接口保真 | ⑥ |
| §8.2 | 拒答话术+exhausted_scope | ✅ | `test_coverage_refusal` | ⑥ |
| §8.3 | 判定型框定三段式 | ❌ | R5 未实装 | ④ |

### §9 横切
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| §9.1-gateway | LLM/Embed/Rerank 过网关 | 🟡 | LLM 接缝✅(stub/gateway);embed/rerank endpoint 未真接 | ①⑧ |
| §9.1-matrix | 模型矩阵(Qwen/Kimi/bge) | ❌ | 未真接 | ① |
| §9.1-embed | embedding endpoint dense+sparse 双输出验证 | ❌ | 走本地 BGE-M3 | ② |
| §9.1-mcp | 检索/SQL 工具 MCP 注册 | ❌ | 未做 | ⑧ |
| §9.2 | 多模型复核 Kimi faithfulness | ❌ | 未做 | — |
| §9.2-r5 | R5 试探性表述复核 | ❌ | 未做 | ④ |
| §9.3-sensitive | 敏感词双向过滤 | ❌ | 未做 | — |
| §9.3-ailabel | AI 内容标识+导出页脚 | 🟡 | contract.ai_label✅;导出页脚 ❌ | — |
| §9.3-perm | Casbin+操作日志 | ❌ | 未做 | — |
| §9.3-obs | Langfuse 全链路 trace | ❌ | 未做 | — |
| §9.3-sso | SSO 统一认证 | ❌ | 未做 | — |

### §10 契约 / §11 导出 / §12 容量 / §13 V0 / §14 验收
| Req | 需求 | 状态 | 证据 | §15 |
|---|---|---|---|---|
| §10 | 输出契约统一 JSON 全字段 | ✅ | `test_contract` | — |
| §11 | Excel 导出 | ❌ | 未做 | — |
| §12-qps | QPS50 / 并发 5–8 | ❌ | 未涉及 | ⑦ |
| §12-p95 | P95<12s | ❌ | 未涉及 | ⑦ |
| §12-quota | 网关并发配额 | ❌ | 未涉及 | ①⑦ |
| §13-fault | 术语断层率标定 | ❌ | V0 未做 | — |
| §13-hyde | HyDE A/B 标定 | ❌ | V0 未做 | ①⑦ |
| §13-refuse | 拒答阈值标定 | ❌ | V0 未做 | ⑥ |
| §13-evalset | 合成评估集 300–500→2000 问 | ❌ | 未做 | — |
| §13-ragas | RAGAS+引用准确率盲评 | ❌ | 未做 | — |
| §14-a | 数据验收(完整问答) | ✅ | `test_r1_integration` | — |
| §14-b | 依据验收(四级+盲评≥95%) | 🟡 | 四级✅;盲评≥95% 未做 | — |
| §14-c | 权限验收(Casbin+日志) | ❌ | 未做 | — |
| §14-d | 安全验收(Langfuse+日志) | ❌ | 未做 | — |
| §14-e | 非功能(复核+敏感词+标识) | 🟡 | ai_label✅;复核/敏感词 ❌ | — |
| §14-f | 性能验收 | ❌ | 未做 | ⑦ |
| §14-g | 核心目标(不裸答) | 🟡 | 引用注入✅+覆盖拒答✅;判定型框定 ❌ | ④ |

---

## 缺口清单(按 GAP backlog 优先级)

- **P0 红线/验收**:R5 全组(R5-bridge/mix/elem/3seg/noraw/review/render,⛔④)· §9.2 多模型复核 · §9.3-perm 权限验收(§14-c)。
- **P1 路由**:**R6**(进行中)· R4(R4-filter/mode/bound)· §5.4 sparse 提权 · §5.5 重排。
- **P2 查询理解前端**:N0 · N1 HyDE · N3 分解。
- **P3 横切/工程**:§7.2 流式 · §11 导出 · §9.3 敏感词/Langfuse/SSO/AI 页脚 · §12 容量 · §13 V0 评估(RAGAS/断层率/评估集)。
- **依赖资产**:§2-entity/biz/chunktype 检索过滤(扩 milvus_io.search,GAP #12)· §2-clauseref resolver · §2-scenario/introutes 字典建表 · §2-tagsE1/E2 富集过滤。

## §15 待确认图例(阻塞标记)

① 网关轻量小模型(HyDE/路由/分类/分解/维度抽取) · ② embedding sparse 双输出 endpoint+版本钉死 · ③ E2 外规覆盖范围(R4 穷举边界) · ④ R5 不裸答产品形态(P0,红线验收) · ⑤ cases"引用外规条款"结构化字段(桥接/SQL 前提) · ⑥ 字典评审/维护(scenario_terms/entity_types/违规类别——覆盖拒答可靠性) · ⑦ 网关并发配额/限流(QPS/HyDE-on) · ⑧ MCP/SKILL 接入规范。

> 多数 §15 项是**生产确认待办**,demo 已用 workaround 交付(本地 BGE-M3=② · consumed-when-present=⑤ · 规则分类=① · 务实判据=⑥)。真正 demo 阶段未触的大块:R5 产品形态(④)、网关/Langfuse/Casbin/SSO 横切、V0 评估。

## 维护规则(每轮 SDD 收口强制 reconcile)

1. 实装一条需求 → 该行改 ✅ **并挂 test_id**(无测试只能记 🟡)。
2. 新轮 SPEC 的 §0 边界"不做"项 → 对应 RTM 行保持 ❌/🟡,不偷改。
3. 每轮 TASKS 的收尾任务(如 R3-T6)同时更新 GAP **和** RTM,并核对 ✅ 行确有通过测试。
4. §15 项 confirmed 落地 → 去该行 §15 标记。
