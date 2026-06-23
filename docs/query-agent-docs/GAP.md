# GAP: 制度查询智能体 v1.0 设计 ↔ 当前实现差距盘点(迭代 backlog)

> 基线:2026-06-22。对照 `docs/制度查询智能体_技术框架设计_v1_0.md`(v1.0,功能1)与当前 `query/` MVP。
> 当前实现 = spec-driven MVP 切片(R1 依据查询 + 覆盖感知拒答 + 八路路由骨架),全仓 **440 passed / 0 failed**
> (真 BGE-M3)。SDD 三件见 `SPEC.md` / `PLAN.md` / `TASKS.md`,决策/踩坑见 `query_devlog.md`。
> 图例:✅ 已实现 · 🟡 部分(骨架/接缝/占位/务实版)· ❌ 未实现。
> **GAP 回答"做到哪了"(选下一轮);覆盖是否可确定见 `RTM.md`(116 条需求 → SPEC SC → test,✅=测试证明)。**

## 一句话
三条红线已在 **R1 闭环**(无编造引用 / 无裸结论 / 可解释拒答);八路里 **R1/R2/R3/R6/R7/R8 实装,R4/R5 仅占位**;
查询理解前端(HyDE/多轮/分解)与横切能力(多模型复核/权限/观测/流式/导出)大部分未做。

---

## 1. 查询理解前端(§3,N0–N4)

| 节点 | 状态 | 说明 |
|---|---|---|
| N0 多轮上下文归并(指代消解/省略补全) | ❌ | `QueryState.history` 仅占位,单轮直通 |
| N1 HyDE 改写 | ❌ | 未做 |
| N2 业务事项分类 | 🟡 | `classify.py` 规则版场景分类 + 词典子串抽取;非 LLM、词典需注入(未接 PG dict 加载)、`dict_scenario_terms` 桥接未做 |
| N3 问题分解 | ❌ | 未做 |
| N4 八路意图路由 | 🟡 | `router.py` 规则版分满 8 类 + 置信度;非 `dict_intent_routes` 训练分类器(合成置信度) |

## 2. 八路路由(§4 / §6)—— 核心差距

| 路由 | 状态 | 说明 |
|---|---|---|
| R1 依据查询(§6.1) | 🟡 大部分 | 混合检索✅ 充分性自检✅(务实) 引用约束生成✅ 四级锚点✅ **案例附挂✅**(R3,可关);缺:sparse 发文字号提权❌、entity_type 强过滤❌ |
| R2 变更查询(§6.2) | ✅ 实装 | 版本链回查 + 条款级 diff + 修订原因回查(缺失明示、不推测)+ §6.2 四栏;背景栏/多跳/字句级 diff 留后续(见 SPEC-R2 §0) |
| R3 相似案例 + 案例桥接(§6.3) | ✅ 实装 | case 分区检索✅ + 要素回填卡片✅(一案一卡)+ 附挂到 R1✅(语义∪精确反查)+ 精确反查桥接原语✅(`cited_regulations` **consumed-when-present**,默认空降级语义-only);桥接-as-入口(behavior→R5)留后续(R5 占位)、L2 `cited_regulations` 生产/`case_summary` 强过滤留后续 |
| R4 多文档列举(§6.4) | ❌ 占位 | 枚举模式高 k / E1∩E2∩biz_domain∩entity_type 全未做 |
| R5 判定型(§6.5) | ❌ 占位 | 构成要件框定 / 三段式 / 多模型复核 全未做(P0,§15-④) |
| R6 统计型(§6.6) | ✅ 实装 | 规则维度抽取✅ + 参数化 SQL(白名单 + bound params **防注入**)✅ + 聚合/列表 TABLE✅;`violation_category` **consumed-when-present**(L2 空降级明示);LLM 维度抽取/占比/字典评审留后续 |
| R7 需澄清(§6.7) | 🟡 | 触发✅ + 纯对话澄清块✅;缺澄清后回 N0 重新归并(N0 未做) |
| R8 兜底拒答(§6.8) | ✅ | `refuse_out_of_domain` |

> R4/R5 均已正确打标 route_type(诚实占位、不裸答),二次开发 = 往既有图挂节点 + 填 handler。

## 3. 检索与重排(§5)

| 项 | 状态 | 说明 |
|---|---|---|
| §5.1 混合检索 dense+sparse+RRF | ✅ | 复用 `milvus_io` |
| §5.2 分区并行配额(内规∥外规 top25) | ✅ | `retrieve/hybrid` 双分区合并 |
| §5.3 强制过滤位 | 🟡 | status✅前置、perm_tag🟡(写入不过滤=设计意图)、entity_type❌ / biz_domain❌(暂缓) |
| §5.4 sparse 精确通道(发文字号提权 + 词典扩展) | ❌ | 用默认 RRF,无差异化权重 / 无 `dict_scenario_terms` 扩展 |
| §5.5 重排 bge-reranker top50→top8 | ❌ | 默认 `rerank=none`(用 RRF 序);接缝预留 |
| §5.6 父子块供证 | ✅ | `fetch_parent_text` |
| §5.7 充分性自检 | 🟡 | 务实版,接口按 §8.1 保真 |

## 4. 生成与引用(§7)

| 项 | 状态 | 说明 |
|---|---|---|
| §7.1 引用 ID 注入式生成 | ✅ | `citation_inject` + `select_faithful` 代码级兜底 |
| §7.2 流式输出(Qwen3.5 首 token<3s) | ❌ | 无流式;contract 有 `stream` 字段但未真推送 |
| §7.3 四级锚点回查 | ✅ | `anchors`(PG 权威源) |
| §7.4 prompt 模板分路由 | 🟡 | R1 有;R5 三段式 / R2 四栏 ❌(对应路由未实装) |

## 5. 覆盖感知拒答(§8)

| 项 | 状态 | 说明 |
|---|---|---|
| §8.1 分数阈值→覆盖语境判据 | 🟡 | 务实版(命中数);非"事项分区穷尽"完整判据,接口保真 |
| §8.2 覆盖感知拒答话术 + exhausted_scope | ✅ | `refuse_coverage` |
| §8.3 判定型框定三段式 | ❌ | R5 未实装 |

## 6. 横切能力(§9)—— 几乎全缺

| 项 | 状态 | 说明 |
|---|---|---|
| §9.1 模型网关 / 模型矩阵(CP-005) | 🟡 | LLM 接缝✅(stub 默认 / gateway 可选);Qwen3.5 主答 / Kimi 复核 / bge endpoint 未真接;MCP/SKILL❌ |
| §9.2 多模型复核(Kimi faithfulness) | ❌ | 未做 |
| §9.3 敏感词过滤 | ❌ | 未做 |
| §9.3 AI 内容标识 | 🟡 | `contract.ai_label`✅;导出页脚❌ |
| §9.3 权限 Casbin + 操作日志 | ❌ | 未做(perm_tag 仅写入不过滤) |
| §9.3 观测 Langfuse | ❌ | 未做 |
| §9.3 SSO | ❌ | 未做 |

## 7. 契约 / 导出 / 容量 / V0 / 验收

| 项 | 状态 | 说明 |
|---|---|---|
| §10 输出契约 JSON | ✅ | 全字段(`contract.py`) |
| §11 导出 Excel | ❌ | 未做 |
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
| `clause_tags` E1/E2 | 🟡 | 分类用词典,未真做义务/期限过滤 |
| `dict_*` | 🟡 | entity_types/biz_domains/departments 存在;scenario_terms / intent_routes 未建 |

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
1. **R5 判定型**(构成要件框定 + 三段式 + 多模型复核)— §15-④ 待甲方确认产品形态
2. **§9.2 多模型复核**(Kimi faithfulness)— 真 LLM 下"无裸结论"代码级保障
3. **§9.3 权限 Casbin + 操作日志** — 权限/安全验收

### P1 — 核心功能路由
4. ~~R2 变更查询~~ ✅ / ~~R3 相似案例+案例桥接~~ ✅ / ~~R6 统计型~~ ✅(SPEC/PLAN/TASKS-R6)/ R4 多文档列举 / R5 判定型(R4/R5 仍占位)
5. §5.5 重排(bge-reranker)/ §5.4 sparse 精确通道提权

### P2 — 查询理解前端
6. N0 多轮归并 / N1 HyDE(默认 on/off 待 V0 A/B)/ N3 问题分解

### P3 — 横切 / 工程
7. §7.2 流式输出 / §11 导出 / §9.3 敏感词 / Langfuse / SSO / AI 标识页脚
8. §13 V0 评估(RAGAS / 术语断层率 / HyDE A/B / 合成评估集)

### 依赖资产缺口(可并行补)
9. ~~`cases` 消费(R3/R6 前提)~~ ✅ R3(要素回填 + 精确反查)+ R6(参数化 SQL 聚合/列表)已消费
10. `clause_references` resolver(R1/R2 多跳;表已建,数据/逻辑待补,见 `libs/common/common/pg_models.py` TODO)
11. `dict_scenario_terms` / `dict_intent_routes` 建表 + 灌种子(18 问 + 应用场景 + 真实日志)
12. entity_type / biz_domain 检索前置过滤 → 需扩 `pipeline.index.milvus_io.search` 接受附加 expr / output_fields

---

## 与文档 §15 待确认项(P0)的关系
GAP 里多项受 v1.0 §15 八项甲方/内部待确认阻塞(轻量小模型、sparse 双输出 endpoint、R5 产品形态、E2 外规覆盖、
cases 引用外规字段、字典评审、网关配额、MCP/SKILL 规范)。开工对应路由前先清相关确认项。
