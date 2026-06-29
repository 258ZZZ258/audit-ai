# GAP: 文档处理管线 v1.6 设计 ↔ 当前实现差距盘点(迭代 backlog)

> 基线:2026-06-25。对照 `docs/文档处理与语料库构建_技术框架设计_v1.6.md`(生产 v1.6 保真)与当前 `pipeline/` + `libs/common/` + `eval/` 实现。
> 当前实现 = M1–M3 + audit-ai 升格 + 阶段 V16(PR #4,四类语料 profile 路由 + E1 富集 + E2 接缝 + 案例 L1),全仓 **374 passed / 0 failed**(干净栈 + 本地 BGE-M3 真跑);查询侧另 440 passed。
> 图例:✅ 已实现 · 🟡 部分(接缝/stub/默认关/demo 子集/规则版替代/schema 就位逻辑缺)· ❌ 未实现 · ➖ 边界外(交接其他文档,§22)。
> **GAP 回答"做到哪了"(选下一轮);覆盖是否可确定见 `RTM.md`(原子需求 → §/SC → test,✅=测试证明)。**
> **本轮强制口径**:凡涉及 **LLM 接入**的环节,无论是否已有接缝,一律计入「§Z LLM 接入需开发项清单」并标 **需开发**——见专节。

## 一句话

**入库主干(S0 登记 → S1 解析 → S2 质检 → S3 切块 → S4 元数据 → S5 索引)的契约与确定性骨架生产保真且测试钉死**;硬契约(chunk_id / manifest 11 列 / IR / Milvus schema / PG 核心表)字节级对齐。**两类大缺口**:(1) **生产解析栈全 stub**(DeepDoc/MinerU/PaddleOCR + OCR 扫描件 + xlsx/图片),demo 用 light parser(docx/pdf-text);(2) **LLM 接入 P0 4 触点全落生产链路**(E2 打标 / 案例引用外规 / 违规事由 / L2 业务域,接真模型 + 门控集成测),**剩 P1/P2 触点**(L2 摘要·适用对象、表格/案例摘要、修订说明对齐、T1 出题)未接。其余:§18 逃逸闭环、§22 P-MISC 路由、评测前置 T1/T3/T5/T6、§14 LLM 治理(敏感词/AI 标识)未做(**ref_resolver R4 跨文档本轮 ✅**)。

---

## 1. S0 接入与登记(§3)

| 项 | 状态 | 说明 |
|---|---|---|
| §3.1 manifest 11 必填列校验(V1.6 +sub_type/+effective_date)+ 不匹配整批拒收 | ✅ | `manifest.py:9-12` REQUIRED_COLUMNS;`s0_register.py` 整批拒收 |
| §3.2 SHA-256 精确去重(命中→跳过+报告) | ✅ | `s0_register.py:_find_by_hash` |
| §3.2 疑似重复(title+文号命中 hash 异)→QUARANTINED | ✅ | `s0_register.py:_suspect_duplicate` → 隔离队列 |
| §3.2 ULID logical_id(跨版本稳定)+ version_id;替代→继承 logical_id | ✅ | `s0_register.py:_resolve_version` |
| §3.2 原件 → ObjectStore `raw/{corpus}/{batch}/{version}.{ext}` 写一次 | ✅ | `s0_register.py` put_raw |
| §3.2 documents+doc_versions 写,status=REGISTERED | ✅ | 原子事务 |
| §3.2 magic number 格式探测(非扩展名) | ✅ | `s0_register.py:detect_format` |
| §3.2 白名单 doc/docx/pdf-text/pdf-scan/**xlsx/jpg/png** | 🟡 | `WHITELIST_FORMATS={docx,pdf}` 仅 2 种;**xlsx/jpg/png 缺**(demo 子集) |
| §3.2 白名单外 → QUARANTINED | ✅ | |
| §3.3 批次质量报告 | ✅ | `RegisterReport` + ImportBatch.report |

## 2. S1 解析层(§4)

| 项 | 状态 | 说明 |
|---|---|---|
| §4.2 IR schema(blocks/tables/bbox/page 保真) | 🟡 | `ir.py` 有 index/type/level/text/page/bbox;**缺 block_id / ocr_conf / table_id / anchor_block / cells_md(markdown)** |
| §4.1 docx→DeepDoc office / pdf-text→DeepDoc pdf | 🟡 | `parsing/factory.py` DeepDoc **stub**;demo 用 light(python-docx/pdfplumber) |
| §4.1 pdf-notext/图片 → PaddleOCR(GPU)→版面重建 | ❌ | PaddleOCR **stub**;扫描件直接 E202-DEMO 隔离,无 OCR |
| §4.1 复杂版式失败 → MinerU 重试一次 | ❌ | MinerU **stub**,无兜底重试 |
| §4.1 xlsx → openpyxl 直读 → 表格 IR | 🟡 | light_parser xlsx **解析能力**(T1.5,`test_xlsx_parse`);端到端入库(白名单/s1 路由)留 P2 P-MISC |
| §4.1 文本层判定 <50 字/页 → OCR | ✅ | `light_parser.py` density 判定(走隔离而非 OCR) |
| §4.1 解析失败 → PARSE_FAILED(E203) | ✅ | `s1_parse.py:_fail` |
| §4.3 CPU/GPU 独立队列 | ❌ | 单进程轮询;队列分离留生产 Temporal |
| §4.3 超时 5min/扫描件 15min → PARSE_FAILED | 🟡 | `parse_timeout_sec=300` 常规✅;扫描件 15min 分支无(无 OCR) |
| §4.2 表格 markdown 矩阵 + 合并单元格展开 | 🟡 | 简单行列化;**无 markdown 序列化/合并单元格展开** |
| **ParserAdapter 接缝**(demo=light,生产=DeepDoc/MinerU/PaddleOCR stub,`PIPELINE_PARSER_BACKEND`) | ✅ | 接缝在位,生产实现为 stub |

## 3. S2 解析质检(§5)+ §18 逃逸闭环

| 项 | 状态 | 说明 |
|---|---|---|
| §5.1 指标 1 条款覆盖率≥95% / 2 序号连续 gap=0 / 3 层级合法=0 / 4 页码锚点=100% / 5 空表≤5% / 7 抽取充分≥0.7 | ✅ | `qc/indicators.py` 六指标齐;`qc_thresholds.yaml` |
| §5.1 指标 6 文本质量(乱码≤1% / **ocr_conf≥0.85**) | 🟡 | 乱码✅;**ocr_conf 无**(IR 无该字段、demo 无 OCR) |
| §5.1 任一失败 → QC_FAILED + 失败指标 + 定位证据 | ✅ | `qc/gate.py:to_evidence` |
| §5.2 人工补录队列 3 处置(修正重跑/降级 degraded/退回甲方)+ remediation_records | ✅ | `queue.py` + CLI;`remediation_records` 表 |
| §5.3 人工抽检分层 + 不合格率>5% 批次回退 | 🟡/❌ | profile sampling_rate 配置存但未消费;**自动批次回退无** |
| §5.4 Golden Set 回归 F1≥0.98 作 parser-swap 准入门 | 🟡 | `tests/golden/` 存在 + `test_golden_set.py`(F1=1.0 mini set);**无 0.98 自动 gate** |
| §6.3 QA 对完整率≥95%(等价质检) | ✅ | `qa_chunker.py` + `indicators.qa_pair_completeness` |
| **§18.2① 边缘通过带 [阈值,阈值+ε]→自动升级人工抽检** | 🟡 | marginal 标志已算(`gate.py`,`epsilon=0.02`);**不自动提升为抽检对象** |
| **§18.2② 页眉泄漏 + 句完整性检测(指标 8/9)** | ❌ | 无指标 8/9,无跨页重复短串/句边界检测 |
| **§18.2③ 双解析器仲裁(MinerU 第二路,相似度<0.92→人工)** | ❌ | MinerU stub,无仲裁 |
| **§18.2④ 高危 token 复核(数字/金额/期限/否定词,局部 conf≥0.95)** | ❌ | 无高危 token 二次识别 |
| **§18.3 quality_tickets 表 + 用户纠错/生成侧自检/检索统计/事后稽核** | ❌ | quality_tickets 表 **未建**(pg_models 注释 TODO);四类反馈通道无 |
| **§18.4 REPARSE 工作流 + quality_flagged + 下游 stale 传播** | 🟡 | 生产 REPARSE_PENDING/REPARSING **砍掉**,demo 用 `reprocess` 全重跑(确定性 chunk_id 覆盖安全);**quality_flagged 列无,下游 stale 传播属外围系统** |
| **§18.5 逃逸率指标 + golden set 反哺** | ❌ | 依赖 quality_tickets,未做 |

## 4. S3 结构化与切块(§6)

| 项 | 状态 | 说明 |
|---|---|---|
| §6.1 条款树(章/节/条/款/项/目/附则附件 锚定正则 + 虚拟根) | ✅ | `clause_tree.py:classify_heading` |
| §6.1 中文数字→阿拉伯 clause_path_norm | ✅ | `normalize.py:cn_to_int` |
| §6.1 "第X条之一"插入条(bis/之一/小数 统一归一 `N-K`) | ✅ | `normalize.py:normalize_clause_no` |
| §6.1 internal_refs[] 正则捕获("依照第十五条") | ✅ | `clause_tree.py:find_internal_refs`(保留;§6.7 起停止新写,改 clause_references) |
| §6.2 原子单元=条 / 超长>600 拆款项(条头续)/ 超短<50 不合并 / 父块节级≤2000 仅 PG | ✅ | `chunker.py` |
| §6.2 表格独立块(markdown)+ >30 行按行组重复表头 | ✅ | `chunker.py:_table_segments` |
| **§6.2 表格 LLM 一句摘要前缀** | ❌ | **未实现**(仅 markdown,无 LLM 摘要)→ 见 §Z |
| §6.2 面包屑前缀《标题》(文号,版本日期)>章>条 | 🟡 | 含标题/章/条;**缺文号 + 版本日期补充** |
| §6.2 页码锚点 page_start/end 跨度 | ✅ | `chunker.py:_page_span` |
| §6.3 P-QA 一问一答=1 chunk + 问句加权面包屑 + 边界识别 | ✅ | `qa_chunker.py` |
| §6.4 P-CASE 四要素分段(当事人/事实/依据/决定,**段首模式 + LLM 辅助分段**) | 🟡 | 段首模式规则版✅;**LLM 辅助分段未做**(注"默认关")→ 见 §Z |
| **§6.4 案例全文摘要块 case_summary(LLM ≤150 字)** | 🟡 | **规则截断版在用**;LLM 摘要未做(注"默认关、升级点")→ 见 §Z |
| §6.5 chunk_id 公式字节精确 | ✅ | `chunk_id.py`,`test_chunk_id.py` 钉死 |
| §6.6 图谱抽取窗口解耦(节级窗口/指代预解析注入/三元组锚定校验/样板跳过清单) | ❌ | **0%**——S6 图谱未启,该设计为前置准备 |
| **§6.7 ref_resolver 四类指代(R1–R4)纯规则填充** | ✅ | R1–R3 文档内(Phase 1)+ **R4 跨文档三级查(文号→标题→dict_aliases 别名)+ 四态(resolved/ambiguous/pending_target/unresolved)+ R3/R4 span 去重**(`test_ref_resolver`,T2.4);窗口渲染原语 / pending_target 夜间重试另起 |

## 5. S4 元数据与版本链(§7)+ 案例(§9)

| 项 | 状态 | 说明 |
|---|---|---|
| §7.1 L1 规则抽取(发文字号/日期/机构字典/标题)+ manifest 交叉校验冲突→待人工 | ✅ | `meta/l1_rules.py:cross_check` → META_REVIEW |
| **§7.1 L2 LLM 辅助(业务域多值/主题摘要/适用对象,字典约束)** | 🟡 | **业务域多值 ✅ T2.3**(`meta/l2_llm.py`:LLM + `dict_biz_domains` 服务端裁字典 + profile 分档:P-INT 候选入 META_REVIEW、P-EXT/QA/CASE 直落 + 抽检;manifest 优先/冲突;`l2_enabled` 默认关)。主题摘要/适用对象(L-5)P1 → 见 §Z |
| §7.1 L3 人工确认(密级/状态/版本关系)META_REVIEW 工作台 + 放行 | ✅ | `s4_meta.py`;A/B 模式(`auto_confirm_meta_no_conflict`) |
| §7.2 版本链 doc_versions 关系(revise_replace/abolish_only) | ✅ | `version_chain.py:RelationType` |
| §7.2 merge_replace / split_replace | 🟡 | 枚举/路由到人工队列(UNSUPPORTED),无多对一/一对多自动处理 |
| §7.2 INDEXED 后原子切换(PG superseded + Milvus 标量更新 + doc_versions 记录) | ✅ | `finalize.py`;`test_atomic_switch` |
| §7.2 revision_notes 表 + revision_note_status=missing | 🟡 | 表建(raw_text+entries JSONB);**status=missing 业务逻辑未接** |
| **§7.2 修订条目 ↔ 机器 diff 的 LLM 辅助对齐 + 置信度** | ❌ | **未实现**(手工录入入口亦无工作台代码)→ 见 §Z |
| §9 cases 表 + L1 规则(处罚机构/文号/日期) | ✅ | `cases` 表(迁移 0006);`meta/case_extract.py` |
| **§9 引用外规条款 L2 + 归一对齐 / 违规事由分类 L2** | ✅ | **T2.1/T2.2 落地**(`meta/case_l2.py`):LLM 抽引用外规 → `PgRegLookup` 三级匹配归一;违规事由约束 `dict_violation_types` + 服务端裁字典 + dict_version 快照(默认关 `case_l2_enabled`,非阻断,`test_case_l2`)|
| **§9 处罚对象类型 L2 / 金额 L2 兜底** | 🟡 | 对象类型/金额仅 L1(P1,L-6/L-7)→ 见 §Z |
| §9 ref_unresolved 标记 | ✅ | `case_extract.py`(L1 恒 False)+ `case_l2.py`(L2 对齐 miss → 置位,`test_case_l2`)|
| §9 核心五字段完整率≥90% 质检闸 | ❌ | 无完整率校验组件 |

## 6. S5 向量化与索引(§8)

| 项 | 状态 | 说明 |
|---|---|---|
| §8.1 Embedding 服务(dense+sparse 一次产出;离线/在线钉同模型) | ✅ | `index/embedding_client.py`(本地 BGE-M3 真跑;甲方网关 endpoint 未真接=生产项) |
| §8.1 batch/退避重试 + embed_failed 块级队列 | ✅ | `embedding_client.py` |
| §8.2 Milvus `audit_corpus` 全字段(perm_tag/biz_domain/entity_type ARRAY · issuer_level INT8 · status · effective_date · chunk_type · text · corpus_type partition key) | ✅ | `milvus_schema.py` 全字段齐 |
| §8.2 perm_tag 写入 + 检索前置过滤 | 🟡 | **写入✅,过滤有意不实现**(M1 设计意图,CLAUDE.md) |
| §8.2 entity_type 标量 | ✅ schema / 🟡 富集 | schema 齐;由 E2 产出(默认关→空数组) |
| §8.2 写批 500 + flush 后置 INDEXED + staging 不可见 | ✅ | `corpus_rows.py` / `finalize.py` |
| §8.3 PG chunks 全文 + 父块 + 冷备(dense/sparse bytea) | ✅ | `pg_models.py` chunks(含 dense_vec_cold/sparse_vec_cold) |

## 7. 编排 / 状态机 / 一致性(§11 / §12)

| 项 | 状态 | 说明 |
|---|---|---|
| §11 状态机(demo 子集)+ HUMAN_WAIT / WORKER_ADVANCEABLE + 合法迁移表 | ✅ | `states.py` |
| §11 WorkflowEngine 接缝(demo=Orchestrator,生产=Temporal stub,`PIPELINE_WORKFLOW_BACKEND`) | ✅ | `orchestrator.py` |
| §11 单进程轮询 + pipeline_events 留痕 | ✅ | `pg_io.transition` |
| **§11.2 错误码 E1xx–E8xx 全段** | 🟡 | **仅 demo 子集**:E101/E202/E203/E204/E301(未细分 302–307)/E701/E801/E802;**E102/E103/E201/E4xx/E5xx/E6xx 未定义** |
| §12.1 写序 PG→Milvus→flush→INDEXED + staging 不可见 | ✅ | `finalize.py` |
| §12.2 夜间对账 reconcile(PG vs Milvus count,E701) | ✅ | `eval/reconcile.py` |
| §12.3 全量重建 rebuild(冷备零重编码回灌) | ✅ | `eval/rebuild.py`;`test_rebuild` |
| §12.3 批次回滚 | 🟡 | pg_io 支持;无独立 CLI 显式回滚命令测试 |
| §12 幂等性(确定性 chunk_id) | ✅ | `eval/idempotency.py`;`test_idempotency` |

## 8. 异步富集层 S-E(§19)

| 项 | 状态 | 说明 |
|---|---|---|
| §19.1 E1 义务预打标(道义词正则 + obligation 词表,零 LLM,全量,非阻断) | ✅ | `enrich/e1_obligation.py`;`e1_enabled=true` |
| §19.1 deontic_type + 数值/期限正则预抽取 | ✅ | 同上 |
| **§19.1 期限单位归一化 norm_duration_days + surface_duration + is_business_day + norm_status(月→30/季→90…,CP-007)** | ✅ | `e1_obligation.py:normalize_duration`;复合期限标 unparsed |
| §19.1 obligation_keywords 表 | 🟡 | 表未建,用 `config/obligation.yaml`(M1 内置词表口径,功能等价) |
| **§19.2 E2 条款级打标(LLM:涉及事项/责任部门/适用实体类型 entity_type[],字典约束 + server-side filter)** | 🟡 | **接缝完整**(prompt/dict 约束/输出校验/幂等 clear/非阻断);**`e2_enabled=false` 默认关,无真模型链路** → 见 §Z |
| §19.2 dict_entity_types / dict_departments 约束字典 | ✅ | 表(迁移 0007)+ seeds |
| §19.3 E3 图谱优先级探针 doc_graph_stats.graph_priority_score | ❌ | doc_graph_stats 表未建,score 未算 |
| §19.4 E4 路由特征预留(明确不做) | ➖ | 二期决策,留痕 |

## 9. 评测前置层(§21,T1–T6)

| 项 | 状态 | 说明 |
|---|---|---|
| **§21.1 T1 摄取即出题(LLM 出 QA,2–3% 抽样)** | ❌ | 未实现 → 见 §Z |
| §21.2 T2 批次检索冒烟(hit@50 + 权限语境 + E801/E802)+ 99% 出口准则 | ✅ | `eval/smoke.py`;`finalize` 验收;`test_smoke` |
| §21.3 T3 规模台阶 hit@k(内规题降幅≤5pp) | 🟡 | report 按 corpus 拆分框架在;**跨台阶回归未激活** |
| §21.4 T4 引用锚点回放(page±1 子串/编辑距离)+ 99% 出口准则 | ✅ | `eval/anchor_replay.py`;`test_anchor_replay` |
| §21.5 T5 拒答负样本采集(QUARANTINED/pending_target/样板跳过) | ❌ | 未实现 |
| §21.6 T6 分数分布基线(chunk_type 分位数) | 🟡 | 结构未见代码 |
| §21.7 T7 自检索探针 | ➖ | 按选项 B 移交 CP-007,非 v1.6 范围 |

## 10. 数据模型 / 契约(§10 / §3 / §4.2 / §6.5)

| 项 | 状态 | 说明 |
|---|---|---|
| 核心表 import_batches/documents/doc_versions/chunks/pipeline_events/review_queue/remediation_records/revision_notes/clause_tags/cases | ✅ | `pg_models.py` + 迁移 0001–0008;V1.6 add-only 列齐(chunks +chunk_type/parent_chunk_id/internal_refs/embed_status/entity_type;clause_tags +deontic_type/norm_duration_days/entity_type) |
| clause_references 表 | ✅ | 表建(0008)+ R1–R4 填充(`ref_resolver`,`test_ref_resolver`) |
| dict_issuers / dict_biz_domains / dict_entity_types / dict_departments | ✅ | 表 + seeds |
| **dict_violation_types** | ❌ | 表/模型未建(cases.violation_category 为字符串非 FK)→ 阻塞案例违规事由 L2 |
| **dict_aliases**(制度简称别名,§6.7 R4) | ✅ | 表建(0009)+ seed v0-draft;R4 `PgXRefLookup` 第三级消费(`test_ref_resolver`/`test_seeds_p0`) |
| **dict_scenario_terms**(情景术语桥接) | 🟡 | §23 声明纳入数据模型,**仅声明未建表/未 seed**(查询侧消费) |
| quality_tickets / doc_graph_stats / obligation_keywords | 🟡 | 未建(前二 deferred,后者 config 替代) |
| 评测集仓库表(§21 T1) | ❌ | 未建(T1 未实现) |
| §3.1 manifest 契约 11 列 / §4.2 IR / §6.5 chunk_id | ✅ | 字节级保真;`test_v16_fidelity` / `test_ir` / `test_chunk_id` |
| §8.2 Milvus schema | ✅ | 全字段齐 |

## 11. 一期数据摄取全景承接(§22)

| 项 | 状态 | 说明 |
|---|---|---|
| **§22.2 P-MISC profile(监督共享,段落级切块/禁条款树/指标 1·2·3 禁用/独立 manifest)** | ❌ | `profile_router.py` **仅 4 路(P-INT/EXT/QA/CASE),P-MISC 完全未路由**;manifest 不分 profile;`supervision_share` 分区未路由 |
| §22.3 费用审计 expense_doc 分区(发票 OCR + Excel 直读业务表) | ➖ | 边界声明,交接《费用智能化审计》;无代码 |
| §22.4 审计项目资料 audit_project 分区(project_id 维度) | ➖ | 边界声明,交接《审计报告智能化》;doc_versions 无 project_id |
| §22.5 模板库(不走本管线) | ➖ | 边界声明正确,交接《模板库与模板管理》 |

## 12. 安全与治理(§14)

| 项 | 状态 | 说明 |
|---|---|---|
| §14 密级即门禁(缺密级→QUARANTINED) | ✅ | S0 隔离 |
| §14 perm_tag 写入(检索前置过滤) | 🟡 | 写入✅过滤未实现(与查询侧一致) |
| §14 全链路操作日志(导入/补录/确认/降级/回滚/重建) | 🟡 | pipeline_events + remediation_records 留痕;独立审计日志表(敏感操作)未单列 |
| **§14 所有 L2 经模型网关 + 进出敏感词过滤 + AI 标识/已人工确认** | ❌ | 敏感词过滤无;AI 标识工作台流转无 → 见 §Z |

---

## Z. LLM 接入需开发项清单(本轮强制:全部计为「需开发」)

> 口径:**P0 4 触点全落真 LLM 生产链路(L-1/L-2/L-3/L-4),其余 P1/P2 触点待接**。`llm_client.py` 是真 OpenAI 兼容客户端(httpx,JSON 模式,指数退避,key 走 env 绝不入库),**默认零调用**——仅 `e2_enabled`/`case_l2_enabled`/`l2_enabled` 等开关开启时惰性构造。已接项均"接真模型 + 字典/prompt 落地 + fake 单测 + 门控真模型集成";剩网关/配额对接(CP-005)为共性生产项。

| # | LLM 触点 | 规范§ | 当前状态 | 门控开关 | 代码位置 | 需开发内容 | 优先级 |
|---|---|---|---|---|---|---|---|
| L-1 | **案例引用外规条款抽取 + 归一对齐**(全管线**最高价值**字段) | §9 | ✅ **T2.1 落地**(LLM 抽 → `PgRegLookup` 归一对齐 → `cited_regulations`;miss→`ref_unresolved`) | `case_l2_enabled`(关) | `meta/case_l2.py` | 已接真模型 + 门控集成测(`test_case_l2`);剩网关配额(CP-005)| **P0✅** |
| L-2 | **案例违规事由分类**(检索/比对关键维度) | §9 | ✅ **T2.2 落地**(LLM + `dict_violation_types` 服务端裁字典 + dict_version 快照) | `case_l2_enabled`(关) | `meta/case_l2.py` | 已接真模型 + 门控集成测(`test_case_l2`);字典 v0-draft 待评审 §16-6 | **P0✅** |
| L-3 | **L2 业务域多值打标** | §7.1 | ✅ **T2.3 落地**(LLM + `dict_biz_domains` 裁字典 + profile 分档 + manifest 优先/冲突 → 写 `biz_domains`/`source`) | `l2_enabled`(关) | `meta/l2_llm.py` | 已接真模型 + 门控集成测(`test_l2_llm`/`test_s4_meta`)| **P0✅** |
| L-4 | **E2 条款级打标(事项/部门/实体类型 entity_type[])** | §19.2 | ✅ **Phase 1 接真模型**(接缝完整 + DeepSeek 门控实测) | `e2_enabled`(关) | `enrich/e2_tag.py` | 已接真模型 + 集成测(`test_e2_tag`);剩 ~19 万调用配额(CP-005-①③) | **P0✅** |
| L-5 | L2 主题摘要 / 适用对象 | §7.1 | ❌ 无代码 | `l2_enabled`(关) | — | LLM 摘要工厂(规范语言)+ 适用对象实体抽取(字典约束) | P1 |
| L-6 | 案例处罚对象类型 L2 消歧 | §9 | 🟡 L1 only | 无 | `meta/case_extract.py` | L1 歧义时 LLM 判 法人/自然人/其他 | P1 |
| L-7 | 案例处罚金额 L2 兜底 | §9 | 🟡 L1 only | 无 | `meta/case_extract.py` | L1 失败时 LLM 抽取 + 万元单位校验 | P1 |
| L-8 | 修订说明 ↔ 机器 diff LLM 对齐 + 置信度 | §7.2 | ❌ 无代码 | `l2_enabled`(关) | `meta/version_chain.py` | diff 解析 + 条目级对齐 + 置信度;对齐失败保留原文 | P1 |
| L-9 | **T1 摄取即出题**(合成评估集) | §21.1 | ❌ 无代码 | 无 | `eval/` | 2–3% 抽样 → 轻量模型合成问答对 → 评估集表(需建表) | P1 |
| L-10 | 表格 LLM 一句摘要前缀 | §6.2 | ❌ 仅 markdown | 无 | `chunking/chunker.py` | 表格 → 一句人读摘要前缀(块构造时注入) | P2 |
| L-11 | 案例全文摘要 case_summary(≤150 字) | §6.4 | 🟡 规则截断版 | 无 | `chunking/case_chunker.py` | LLM 摘要替换规则截断(相似案例主命中面) | P2 |
| L-12 | 案例 LLM 辅助分段 | §6.4 | 🟡 规则段首版 | 无 | `chunking/case_chunker.py` | 段首模式失败时 LLM 辅助(规则版当前已够) | P2 |
| L-13 | §14 LLM 治理:进出敏感词过滤 + AI 标识/已人工确认流转 | §14 | ❌ 无代码 | 无 | 横切 | 网关进出过滤 + 工作台 AI 标注 → 人工确认转态 | P2(生产前必需) |
| 基建 | LLM client(OpenAI 兼容,env key,默认零调用) | §8.1/§14 | ✅ 接缝就位 | — | `llm_client.py` | 网关 endpoint/配额对接、token 预算校验(CP-005)、PROMPTS.md 集中化(可选) | — |

> **结论:LLM 维度 13 触点 → P0 4 触点全落生产链路**(L-4 E2 / L-1 案例引用外规 / L-2 违规事由 / L-3 L2 业务域),均「接真模型 + 字典/prompt + fake 单测 + 门控真模型集成」。**P0 LLM 全清**;剩 P1×5 / P2×4 未接。client 基建就位,网关配额(CP-005)仍待。

---

## 迭代 Backlog(按优先级)

### P0 — 生产保真硬缺口 / 最高价值
1. **生产解析栈接入**:DeepDoc(office/pdf)+ PaddleOCR(扫描件)+ MinerU(兜底)真实现替换 stub;白名单补 xlsx/jpg/png;IR 补 ocr_conf/block_id/table_id/cells_md(markdown)。**入库主干的最大缺口**。
2. **LLM P0 4 触点全落**(L-1 引用外规 / L-2 违规事由+dict_violation_types / L-3 L2 业务域 / L-4 E2 接真模型,见 §Z)——P0 LLM 全清,剩 P1/P2。
3. **ref_resolver R4 跨文档**(§6.7):✅ 本轮 R1–R4 全实装(R4 三级查 + 四态 standoff + R3/R4 span 去重,`feat/ref-resolver-r4`,**零迁移**);剩 pending_target 夜间重试 + 语料缺口清单导出另起一轮。

### P1 — 质检纵深 / 评测 / 版本链
4. **§18 逃逸闭环**:quality_tickets 表 + 边缘带自动升级抽检 + 指标 8/9(页眉泄漏/句完整性)+ 高危 token 复核 + 双解析器仲裁。
5. **评测前置补齐**:T1 出题(L-9)/ T3 台阶回归激活 / T5 负样本 / T6 分布基线。
6. **版本链补链**:revision_notes LLM 对齐(L-8)+ status=missing 业务逻辑 + merge/split_replace 自动处理。
7. **案例完整率≥90% 质检闸** + 案例 L2 余项(L-6/L-7)。

### P2 — 治理 / profile 扩展 / 体验
8. **§22 P-MISC profile 路由**(profile_router 第 5 路 + supervision_share 分区 + 独立 manifest)。
9. **§14 LLM 治理**(L-13 敏感词 + AI 标识)+ 独立敏感操作审计日志表。
10. 表格/案例摘要 LLM 升级(L-10/L-11/L-12)+ 面包屑补文号/版本日期。
11. 错误码 E1xx–E6xx 全段细化 + 抽检不合格率自动批次回退 + golden set 0.98 自动 gate。

### 依赖 / 边界外
12. E3 图谱探针(doc_graph_stats)+ §6.6 图谱窗口(S6 启动前置)。
13. dict_scenario_terms 建表 seed(查询侧消费)；§22.3/.4/.5 费用/项目/模板交接其他文档(➖)。

---

## 与待确认事项(§16)的关系

GAP 多项受 v1.6 §16 待确认阻塞,开工前先清:
- **§16-2 密级口径** → perm_tag 过滤(本管线写入已就位)。
- **§16-6 业务域/违规类别字典评审** → L-2/L-3(P0 LLM)的约束空间。
- **§16-7 dict_entity_types 评审** → L-4 E2 实体类型维度。
- **§16-8 期限归一口径**(月→30/季→90 是否被业务接受)→ E1 已实现按此口径,待会签确认。
- **§16-9 监督共享来源/类型枚举** → §22.2 P-MISC manifest 与切块。
- **CP-005-①③ 网关轻量模型/配额** → 所有 LLM 触点(L-1…L-13)的模型选型与成本口径。
