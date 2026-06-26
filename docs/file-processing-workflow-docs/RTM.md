# RTM: 文档处理管线 v1.6 需求可追溯矩阵(覆盖证明)

> 基线 2026-06-25。对照 `docs/文档处理与语料库构建_技术框架设计_v1.6.md`(生产 v1.6 保真)。
> **GAP.md 回答"做到哪了"(按 § 的进度盘点);RTM 回答"是否可确定覆盖了 v1.6"——把每条需求挂到 v1.6 § + 测试。**
> 二者并存:迭代时先看 GAP 选下一轮,收口时更新 RTM 验证覆盖。

## 怎么读

- **分母**:从 v1.6 §0–§22 逐条抽出的 **138 条原子需求**。这是"100% 覆盖"的基准集——❌ 行让缺口**显式可见**,而非"没列就看不见"。
- **状态**:`✅` 实装且有测试证据 · `🟡` 部分(demo 子集/接缝/默认关/规则版替代/schema 就位逻辑缺/架构满足无专测)· `❌` 未实装 · `➖` 边界外(§22 交接其他文档 / 二期决策)。
- **证据**:`✅` 必须挂 **v1.6 §** + **test 文件**——✅ 是测试证明,不是断言。**架构满足但无专测的需求记 🟡**(待补回归测),不破例。
- **LLM 列**:`🤖` 标记该需求涉及 **LLM 接入**——本轮强制全部计入「需开发项」,无论是否已有接缝(详见 GAP §Z)。
- **§16**:该需求受 v1.6 §16 待确认项阻塞(图例见末尾)。

## 覆盖摘要(可量化)

| | 数 | 占比 | 说明 |
|---|---|---|---|
| ✅ 实装+测试 | **79** | 57% | 入库主干契约 · S0 登记 · S3 条款树/切块/QA · S2 七指标(含指标6 ocr_conf)· S4 L1/版本链 · S5 索引/冷备 · E1 富集 · **Phase 0/1:IR markdown/E2 真模型/ref_resolver R1–R3** · **Phase 2:案例 L2 引用外规对齐(S4-12)/违规事由分类(S4-11)** · T2/T4 · 编排/一致性/重建 |
| 🟡 部分 | **36** | 26% | 生产解析栈 stub · **xlsx parser-only(端到端 P2)** · IR 缺 block_id/table_id · 面包屑缺文号 · 案例对象类型/金额 L1-only · **L2 业务域 ✅·主题摘要/适用对象 P1** · T3/T6 框架 · perm_tag 写不过滤 · 错误码子集 · **ref_resolver R4/dict_aliases 消费留 T2.4** · §18 边缘带/REPARSE |
| ❌ 未实装 | **18** | 13% | OCR/MinerU · L2 主题摘要/适用对象(P1)· 修订说明对齐 · §18 指标8/9/仲裁/高危token/quality_tickets · §6.6 图谱窗口 · T1/T5 · P-MISC 路由 · §14 敏感词 |
| ➖ 边界外 | **5** | 4% | E4 路由(二期)· T7(CP-007)· §22.3/.4/.5 费用/项目/模板交接 |
| **合计** | **138** | | |

- **硬契约(byte-identical 生产设计)全绿**:chunk_id 公式 ✅ · manifest 11 列 ✅ · IR ✅ · Milvus audit_corpus 全字段 ✅ · PG add-only 列(chunks/clause_tags V1.6 列)✅ · 状态机/写序/幂等 ✅。
- **两类系统性缺口**:① **生产解析栈全 stub**(DeepDoc/PaddleOCR/MinerU + OCR/xlsx/图片)→ S1 多行 🟡/❌;② **LLM 接入零生产链路**(13 触点)→ 见专节。
- **🤖 LLM 行 13 条**,全部 ❌ 或 🟡(接缝/默认关)——本轮强制计为需开发(GAP §Z)。

---

## 矩阵(按 v1.6 § 分组)

### §0 设计目标与硬约束 / 红线
| Req | 需求 | 状态 | 证据(v1.6 § / test) | 🤖 | §16 |
|---|---|---|---|---|---|
| O-1 | 未过质检文档不得入库(硬关卡) | ✅ | §0-1/§5;`test_qc`/`test_orchestrator` | | |
| O-2 | chunk 四级可回溯(条款→文档→页码→版本) | ✅ | §0-2/§6;`test_anchor_replay`/`test_s5` | | |
| O-3 | 数据流单向只读,无源系统回写 | 🟡 | §0-3;架构(无回写路径),无专测 | | |
| O-4 | 权限/密级/操作日志全程留痕 | 🟡 | §0-4/§14;`pipeline_events`/`remediation_records`✅,独立审计表/敏感词❌ | | ② |
| O-5 | 支持 Word/PDF/Excel/图片/扫描件 | 🟡 | §0-5/§4;仅 docx/pdf-text(`test_s1_parse`),xlsx/图片/扫描件❌ | | |
| O-6 | 长任务异步 + 状态可见 | ✅ | §0-6/§11;`test_orchestrator`/`test_states` | | |
| O-7 | PG 权威 / Milvus 可随时全量重建 | ✅ | §0-7/§12;`test_rebuild`/`test_reconcile` | | |
| O-8 | Schema add-only,复用工厂/抽象 | ✅ | §0-8/§10;`alembic`/`test_v16_fidelity` | | |

### §3 S0 接入与登记
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| S0-1 | manifest 11 必填列(V1.6 +sub_type/+effective_date)+ 不匹配整批拒收 | ✅ | §3.1;`test_v16_fidelity`/`test_s0_register` | | |
| S0-2 | SHA-256 精确去重(命中→跳过+报告) | ✅ | §3.2;`test_s0_register` | | |
| S0-3 | 疑似重复(title+文号命中 hash 异)→QUARANTINED | ✅ | §3.2;`test_s0_register` | | |
| S0-4 | ULID logical_id(跨版本稳定)+ version_id;替代→继承 | ✅ | §3.2;`test_s0_register` | | |
| S0-5 | 原件 → ObjectStore raw/… 写一次 | ✅ | §3.2;`test_object_store`/`test_s0_register` | | |
| S0-6 | documents+doc_versions 写,status=REGISTERED | ✅ | §3.2;`test_s0_register` | | |
| S0-7 | magic number 格式探测(非扩展名) | ✅ | §3.2;`test_s0_register` | | |
| S0-8 | 白名单 doc/docx/pdf-text/pdf-scan/xlsx/jpg/png | 🟡 | §3.2;`WHITELIST={docx,pdf}` 仅 2 种(`test_s0_register`) | | |
| S0-9 | 白名单外 → QUARANTINED | ✅ | §3.2;`test_s0_register` | | |
| S0-10 | 批次质量报告 | ✅ | §3.3;`test_s0_register`/`test_report` | | |

### §4 S1 解析层
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| S1-1 | docx/pdf-text → DeepDoc 通道 | 🟡 | §4.1;DeepDoc **stub**,demo light(`test_light_parser`) | | |
| S1-2 | pdf-notext/图片 → PaddleOCR(GPU)→版面重建 | ❌ | §4.1;PaddleOCR stub,扫描件隔离 | | ① |
| S1-3 | 复杂版式失败 → MinerU 重试一次 | ❌ | §4.1;MinerU stub | | |
| S1-4 | xlsx → openpyxl 直读 → 表格 IR | 🟡 | §4.1;light_parser xlsx 解析能力(`test_xlsx_parse`);白名单/端到端入库(纯表格 S3 不适用)留 P2 P-MISC | | |
| S1-5 | 文本层判定 <50 字/页 → OCR | ✅ | §4.1;`test_light_parser` | | |
| S1-6 | 解析失败 → PARSE_FAILED(E203) | ✅ | §4.1/§11.2;`test_s1_parse` | | |
| S1-7 | IR schema(blocks/tables/bbox/page) | 🟡 | §4.2;缺 ocr_conf/block_id/table_id/cells_md(`test_ir`) | | |
| S1-8 | 表格 markdown 矩阵 + 合并单元格展开 | ✅ | §4.2;`Table.to_markdown`/`expanded_rows`(`test_table_markdown`)+ chunker 接入 | | |
| S1-9 | CPU/GPU 独立 task queue | ❌ | §4.3;单进程轮询 | | |
| S1-10 | 超时 5min/扫描件 15min → PARSE_FAILED | 🟡 | §4.3;常规 300s✅,扫描件 15min 分支无 | | |
| S1-11 | ParserAdapter 接缝 + factory + 配置 backend | ✅ | §11(接缝);`test_s1_parse` | | |

### §5 S2 质检 + §18 逃逸闭环
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| S2-1 | 指标1 条款覆盖率≥95% | ✅ | §5.1;`test_qc` | | |
| S2-2 | 指标2 条款序号连续性 gap=0 | ✅ | §5.1;`test_qc` | | |
| S2-3 | 指标3 标题层级合法性=0 | ✅ | §5.1;`test_qc` | | |
| S2-4 | 指标4 页码锚点完整率=100% | ✅ | §5.1;`test_qc` | | |
| S2-5 | 指标5 表格还原(空表≤5%) | ✅ | §5.1;`test_qc` | | |
| S2-6 | 指标6 文本质量(乱码≤1% + **ocr_conf≥0.85**) | ✅ | §5.1;乱码✅ + ocr_conf 均值校验(`test_qc` 指标6,有值才参与) | | |
| S2-7 | 指标7 抽取充分性≥0.7 | ✅ | §5.1;`test_qc` | | |
| S2-8 | 任一失败 → QC_FAILED + 失败指标 + 定位证据 | ✅ | §5.1;`test_qc`/`test_orchestrator` | | |
| S2-9 | 补录队列 3 处置 + remediation_records | ✅ | §5.2;`test_queue` | | |
| S2-10 | 人工抽检分层 + 不合格率>5% 批次回退 | 🟡 | §5.3;sampling_rate 配置未消费,回退无 | | |
| S2-11 | Golden Set 回归 F1≥0.98 parser-swap 准入门 | 🟡 | §5.4;`test_golden_set`(mini F1=1.0),无 0.98 自动 gate | | |
| S2-12 | QA 对完整率≥95%(等价质检) | ✅ | §6.3;`test_qa_chunker` | | |
| §18-1 | 边缘通过带 [阈值,阈值+ε]→自动升级抽检 | 🟡 | §18.2①;marginal 标志已算(`test_qc`),不自动升级 | | |
| §18-2 | 页眉泄漏 + 句完整性检测(指标 8/9) | ❌ | §18.2② | | |
| §18-3 | 双解析器仲裁(MinerU 第二路) | ❌ | §18.2③ | | |
| §18-4 | 高危 token 复核(数字/期限/否定词,conf≥0.95) | ❌ | §18.2④ | | |
| §18-5 | quality_tickets 表 + 四类运行期反馈通道 | ❌ | §18.3 | | |
| §18-6 | REPARSE 工作流 + quality_flagged + 下游 stale | 🟡 | §18.4;demo `reprocess` 全重跑替代(`test_cli`),REPARSE 态/flag 无 | | |
| §18-7 | 逃逸率指标 + golden set 反哺 | ❌ | §18.5 | | |

### §6 S3 结构化与切块
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| S3-1 | 条款树(章/节/条/款/项/目/附则附件 + 虚拟根) | ✅ | §6.1;`test_clause_tree` | | |
| S3-2 | 中文数字→阿拉伯 clause_path_norm | ✅ | §6.1;`test_normalize` | | |
| S3-3 | "第X条之一"插入条统一归一 | ✅ | §6.1;`test_normalize` | | |
| S3-4 | internal_refs[] 正则捕获 | ✅ | §6.1;`test_clause_tree` | | |
| S3-5 | 原子单元=条 / 超长拆 / 超短不合并 / 父块节级仅 PG | ✅ | §6.2;`test_chunker` | | |
| S3-6 | 表格独立块(markdown)+ >30 行按行组拆 | ✅ | §6.2;`test_chunker` | | |
| S3-7 | 表格 **LLM 一句摘要前缀** | ❌ | §6.2;仅 markdown,无 LLM | 🤖 | ① |
| S3-8 | 面包屑前缀《标题》(文号,版本日期)>章>条 | 🟡 | §6.2;缺文号+版本日期(`test_chunker`) | | |
| S3-9 | 页码锚点 page_start/end 跨度 | ✅ | §6.2;`test_chunker` | | |
| S3-10 | P-QA 一问一答=1 chunk + 问句加权 + 边界识别 | ✅ | §6.3;`test_qa_chunker` | | |
| S3-11 | P-CASE 四要素分段(段首模式 + **LLM 辅助**) | 🟡 | §6.4;规则段首版(`test_case_chunker`),LLM 辅助❌ | 🤖 | ① |
| S3-12 | P-CASE **case_summary(LLM ≤150 字)** | 🟡 | §6.4;规则截断版(`test_case_chunker`),LLM❌ | 🤖 | ① |
| S3-13 | chunk_id 公式字节精确 | ✅ | §6.5;`test_chunk_id`(钉死) | | |
| S3-14 | §6.6 图谱抽取窗口解耦(节级窗口/锚定校验/样板跳过) | ❌ | §6.6;S6 未启 | | |
| S3-15 | §6.7 ref_resolver 四类指代(R1–R4)纯规则填充 | 🟡 | §6.7;R1–R3 实装+写库+CASCADE(`test_ref_resolver`,T1.3);R4 跨文档留 T2.4 | | |
| S3-16 | profile 路由 P-INT/P-EXT/P-QA/P-CASE | ✅ | §2/§6;`test_profile_router` | | |

### §7 S4 元数据与版本链 / §9 案例
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| S4-1 | L1 规则抽取 + manifest 交叉校验冲突→待人工 | ✅ | §7.1;`test_l1`/`test_s4_meta` | | |
| S4-2 | **L2 LLM 辅助(业务域/主题摘要/适用对象,字典约束)** | 🟡 | §7.1;**业务域多值 ✅**(T2.3,`l2_llm`+profile 分档,`test_l2_llm`/`test_s4_meta`);主题摘要/适用对象(L-5)P1 | 🤖 | ⑥ |
| S4-3 | L3 人工确认(密级/状态/版本)META_REVIEW + 放行 | ✅ | §7.1;`test_s4_meta`/`test_b_mode_ingest` | | ② |
| S4-4 | 版本链 revise_replace / abolish_only + 触发动作 | ✅ | §7.2;`test_version_chain` | | |
| S4-5 | merge_replace / split_replace(多对一/一对多) | 🟡 | §7.2;枚举/路人工,无自动处理 | | |
| S4-6 | INDEXED 后原子切换(PG superseded + Milvus 标量 + 记录) | ✅ | §7.2;`test_atomic_switch` | | |
| S4-7 | revision_notes 表 + revision_note_status=missing | 🟡 | §7.2;表建,status 业务逻辑未接 | | ③ |
| S4-8 | **修订条目 ↔ diff LLM 对齐 + 置信度** | ❌ | §7.2;无代码 | 🤖 | ③ |
| S4-9 | cases L1(处罚机构/文号/日期) | ✅ | §9;`test_case_extract` | | |
| S4-10 | cases 处罚对象类型 **L2** | 🟡 | §9;L1 only(`test_case_extract`),LLM❌ | 🤖 | |
| S4-11 | cases **违规事由分类 L2**(dict_violation_types) | ✅ | §9;LLM + 服务端裁字典 + dict_version 快照(`test_case_l2`,默认关/非阻断) | 🤖 | ⑥ |
| S4-12 | cases **引用外规条款 L2 + 归一对齐**(最高价值) | ✅ | §9;LLM 抽取 → PgRegLookup 三级匹配归一(`test_case_l2`:单元+真栈+门控真模型) | 🤖 | ⑤ |
| S4-13 | cases 处罚金额 **L2 兜底** | 🟡 | §9;L1 only(`test_case_extract`) | 🤖 | |
| S4-14 | ref_unresolved 标记(对齐失败不阻塞) | ✅ | §9;`test_case_extract`(L1 恒 False)+ `test_case_l2`(L2 对齐 miss 置位) | | |
| S4-15 | 案例核心五字段完整率≥90% 质检闸 | ❌ | §9;无校验组件 | | ⑥ |

### §8 S5 向量化与索引
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| S5-1 | Embedding dense+sparse 一次产出 | ✅ | §8.1;`test_embedding_client`/`test_s5` | | |
| S5-2 | batch + 退避重试 + embed_failed 块级队列 | ✅ | §8.1;`test_embedding_client` | | |
| S5-3 | Milvus audit_corpus 全字段 schema | ✅ | §8.2;`test_milvus_io` | | |
| S5-4 | perm_tag 写入 + 检索前置过滤 | 🟡 | §8.2;写入✅,过滤有意不实现 | | ② |
| S5-5 | entity_type 标量(E2 产出) | 🟡 | §8.2;schema✅(`test_milvus_search_expr`),富集默认关 | 🤖 | ⑦ |
| S5-6 | 写批 500 + flush 后置 INDEXED + staging 不可见 | ✅ | §8.2;`test_s5`/`test_finalize_verify` | | |
| S5-7 | PG chunks 全文 + 父块 + 冷备(dense/sparse bytea) | ✅ | §8.3;`test_pg_io`/`test_rebuild` | | |

### §19 异步富集层 S-E
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| E1-1 | E1 义务预打标(道义词正则 + 词表,零 LLM,非阻断) | ✅ | §19.1;`test_e1_obligation`/`test_obligation_golden` | | |
| E1-2 | deontic_type + 数值/期限/比例正则预抽取 | ✅ | §19.1;`test_e1_obligation` | | |
| E1-3 | 期限单位归一化 norm_duration_days + surface + is_business_day(CP-007) | ✅ | §19.1;`test_e1_obligation` | | ⑧ |
| E2-1 | **E2 条款级打标(LLM:事项/部门/实体类型,字典约束 + 输出校验)** | ✅ | §19.2;真模型门控集成测(`test_e2_tag`,DeepSeek 实测验证字典约束对真模型生效) | 🤖 | ⑦ |
| E2-2 | dict_entity_types / dict_departments 约束字典 | ✅ | §19.2;表(0007)+ seeds(`test_e2_tag`) | | ⑦ |
| E3 | 图谱优先级探针 doc_graph_stats.graph_priority_score | ❌ | §19.3;表未建 | | |
| E4 | 路由特征预留(明确不做) | ➖ | §19.4;二期决策 | | |

### §21 评测前置层
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| T1 | 摄取即出题(**LLM 出 QA**,2–3% 抽样) | ❌ | §21.1;未实现 | 🤖 | ① |
| T2 | 批次检索冒烟(hit@50 + 权限语境 + E801/E802) | ✅ | §21.2;`test_smoke`/`test_finalize_verify` | | |
| T3 | 规模台阶 hit@k(内规题降幅≤5pp) | 🟡 | §21.3;report 按 corpus 拆分(`test_report`),回归未激活 | | |
| T4 | 引用锚点回放(page±1 子串/编辑距离) | ✅ | §21.4;`test_anchor_replay`/`test_finalize_verify` | | |
| T5 | 拒答负样本采集(QUARANTINED/pending_target/样板跳过) | ❌ | §21.5;未实现 | | |
| T6 | 分数分布基线(chunk_type 分位数) | 🟡 | §21.6;结构未见代码 | | |
| T7 | 自检索探针 | ➖ | §21.7;选项 B 移交 CP-007 | | |

### §11 编排 / §12 一致性
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| ORCH-1 | 状态机(demo 子集)+ HUMAN_WAIT/WORKER_ADVANCEABLE + 合法迁移表 | ✅ | §11/§1.1;`test_states` | | |
| ORCH-2 | WorkflowEngine 接缝(demo=Orchestrator,生产=Temporal stub) | ✅ | §11;`test_orchestrator` | | |
| ORCH-3 | 单进程轮询 + pipeline_events 留痕 | ✅ | §11;`test_orchestrator`/`test_pg_io` | | |
| ORCH-4 | 错误码 E1xx–E8xx 全段 | 🟡 | §11.2;demo 子集(`test_states`),E102/103/201/E4xx–E6xx 缺 | | |
| CON-1 | 写序 PG→Milvus→flush→INDEXED + staging 不可见 | ✅ | §12.1;`test_finalize_verify` | | |
| CON-2 | 夜间对账 reconcile(count 比对,E701) | ✅ | §12.2;`test_reconcile` | | |
| CON-3 | 全量重建 rebuild(冷备零重编码) | ✅ | §12.3;`test_rebuild` | | |
| CON-4 | 批次回滚(软删 PG + Milvus PK delete) | 🟡 | §12.3;pg_io 支持,无独立命令专测 | | |
| CON-5 | 幂等性(确定性 chunk_id 重跑覆盖) | ✅ | §12.1;`test_idempotency` | | |

### §10 数据模型 / 契约
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| DM-1 | 核心表 + V1.6 add-only 列(chunks/clause_tags/cases) | ✅ | §10;`alembic 0001–0011`/`test_v16_fidelity` | | |
| DM-2 | clause_references 表 | ✅ | §10/§6.7;表建+R1–R3 填充(`test_ref_resolver`)+FK CASCADE(迁移 0010) | | |
| DM-3 | dict_violation_types | 🟡 | §10;表建+v0-draft seed(迁移 0009)+ **L2 消费已接**(T2.2,`test_case_l2`);字典 v0-draft 待评审 §16-6 | | ⑥ |
| DM-4 | dict_aliases(制度简称别名) | 🟡 | §6.7/§10;表建+seed(迁移 0009,`test_seeds_p0`);R4 消费留 T2.4 | | |
| DM-5 | dict_scenario_terms(情景术语桥接) | 🟡 | §23;仅声明未建表/seed | | ⑥ |
| DM-6 | quality_tickets / doc_graph_stats / obligation_keywords | 🟡 | §18/§19;前二未建,后者 config 替代 | | |
| DM-7 | 评测集仓库表(T1) | ❌ | §21.1;未建 | | |
| DM-8 | manifest 契约 11 列 | ✅ | §3.1;`test_v16_fidelity` | | |
| DM-9 | IR 契约保真 | ✅ | §4.2;`test_ir` | | |
| DM-10 | Milvus audit_corpus schema | ✅ | §8.2;`test_milvus_io` | | |

### §22 一期数据摄取全景承接
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| MISC-1 | P-MISC profile 路由(段落级/禁条款树/指标1·2·3 禁用/独立 manifest/supervision_share 分区) | ❌ | §22.2;profile_router 仅 4 路 | | ⑨ |
| MISC-2 | 费用审计 expense_doc(发票 OCR + Excel 直读业务表) | ➖ | §22.3;交接《费用智能化审计》 | | |
| MISC-3 | 审计项目资料 audit_project(project_id 维度) | ➖ | §22.4;交接《审计报告智能化》 | | |
| MISC-4 | 模板库(不走本管线) | ➖ | §22.5;交接《模板库与模板管理》 | | |

### §14 安全与权限 / §15 验收对齐
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| SEC-1 | 密级即门禁(缺密级→QUARANTINED) | ✅ | §14;`test_s0_register` | | ② |
| SEC-2 | perm_tag 检索前置过滤(禁后裁剪) | 🟡 | §14;写入✅过滤❌ | | ② |
| SEC-3 | 全链路操作日志(导入/补录/确认/降级/回滚/重建) | 🟡 | §14;pipeline_events/remediation✅,独立审计表未单列 | | |
| SEC-4 | **L2 经网关 + 进出敏感词过滤 + AI 标识/已人工确认** | ❌ | §14;无代码 | 🤖 | |
| ACC-1 | 数据验收(样例可导入/解析/调用) | ✅ | §15;`test_b_mode_ingest`(端到端入库) | | |
| ACC-2 | 依据验收(四级锚点填充率) | ✅ | §15;`test_anchor_replay` | | |
| ACC-3 | 权限验收(perm_tag + 操作日志) | 🟡 | §15;写入✅过滤/审计部分 | | ② |
| ACC-4 | 安全验收(pipeline_events 全量 + 备份口径) | 🟡 | §15;留痕✅,备份口径文档侧 | | |
| ACC-5 | 质量看板核心指标(解析率/QC一次过/对账/T2/T4/锚点填充) | ✅ | §15;`test_report` | | |
| ACC-6 | 看板 T1 累积量 / T3 台阶曲线 / embedding 失败率汇总 | 🟡 | §15;T3 框架,T1/embed 失败率未汇总 | | |

### 配置(§ 全文集中可调值)
| Req | 需求 | 状态 | 证据 | 🤖 | §16 |
|---|---|---|---|---|---|
| CFG-1 | settings.toml [toggles]/[llm]/[chunk]/[verify] | ✅ | §;`test_config` | | |
| CFG-2 | profiles.yaml P-INT/P-EXT/P-QA/P-CASE | ✅ | §2;`test_config`(无 P-MISC) | | |
| CFG-3 | qc_thresholds.yaml(7 指标 + ε + QA 完整率) | ✅ | §5.1;`test_config`/`test_qc_profile` | | |
| CFG-4 | obligation.yaml(E1 词表) | ✅ | §19.1;`test_e1_obligation` | | |
| CFG-5 | seeds dict_*(issuers/biz_domains/entity_types/departments) | ✅ | §10;seeds(dict_scenario_terms 未 seed) | | |

---

## 缺口清单(按 GAP backlog 优先级)

- **P0 生产保真硬缺口(剩余)**:生产解析栈(S1-1/2/3 DeepDoc/OCR/MinerU + S1-7 IR block_id/table_id)· **LLM P0 4 触点全落**(S4-12 引用外规 / S4-11 违规事由+DM-3 / S4-2 业务域 / E2-1 接真模型)· ref_resolver R4 跨文档(S3-15 R4 + DM-4 dict_aliases 消费,T2.4)· 白名单 jpg/png 路由(S0-8/S1-1·2,T2.5)。
- **P1 质检纵深/评测/版本链**:§18 逃逸(§18-1…§18-7 + DM-6 quality_tickets)· 评测 T1/T3/T5/T6(+DM-7)· 版本链(S4-8 LLM 对齐 / S4-7 / S4-5)· 案例完整率闸(S4-15)+ 案例 L2 余项(S4-10/S4-13)。
- **P2 治理/profile/体验**:P-MISC 路由(MISC-1)· §14 LLM 治理(SEC-4)· 表格/案例摘要 LLM(S3-7/S3-11/S3-12)· 面包屑补全(S3-8)· 错误码全段(ORCH-4)· 抽检回退/golden gate(S2-10/S2-11)。
- **边界外/二期**:E3/§6.6 图谱(E3/S3-14)· dict_scenario_terms(DM-5)· §22.3/.4/.5(MISC-2/3/4)· E4/T7(➖)。

## 🤖 LLM 接入需开发项(RTM 交叉索引,全部计入需开发)

| RTM Req | GAP § | 触点 | 状态 | 优先级 |
|---|---|---|---|---|
| S4-12 | L-1 | 案例引用外规条款抽取+对齐(最高价值) | ✅ 真栈+门控(`test_case_l2`) | P0 |
| S4-11 | L-2 | 案例违规事由分类(+dict_violation_types) | ✅ 真栈+门控(`test_case_l2`) | P0 |
| S4-2 | L-3 | L2 业务域多值打标 | ✅ 真栈+profile 分档(`test_l2_llm`/`test_s4_meta`) | P0 |
| E2-1 | L-4 | E2 条款级打标(接真模型) | ✅ 门控真模型(`test_e2_tag`) | P0 |
| S4-2 | L-5 | L2 主题摘要 / 适用对象 | ❌ | P1 |
| S4-10 | L-6 | 案例对象类型 L2 消歧 | 🟡 L1 | P1 |
| S4-13 | L-7 | 案例金额 L2 兜底 | 🟡 L1 | P1 |
| S4-8 | L-8 | 修订说明 diff LLM 对齐 | ❌ | P1 |
| T1 | L-9 | T1 摄取即出题 | ❌ | P1 |
| S3-7 | L-10 | 表格 LLM 摘要前缀 | ❌ | P2 |
| S3-12 | L-11 | 案例 case_summary LLM | 🟡 规则 | P2 |
| S3-11 | L-12 | 案例 LLM 辅助分段 | 🟡 规则 | P2 |
| SEC-4 | L-13 | §14 敏感词过滤 + AI 标识 | ❌ | P2 |

> `llm_client.py` 基建就位(真 OpenAI 兼容,默认零调用)。**P0 LLM 4 触点全落生产链路**:L-4 E2(Phase 1)、L-1 案例引用外规 / L-2 违规事由 / L-3 L2 业务域(Phase 2);均「接真模型 + 字典/prompt 落地 + fake 单测 + 门控真模型集成」。剩 P1×5 / P2×4 共 9 触点待接(网关配额对接 CP-005 仍待)。

## §16 待确认图例(阻塞标记)

① 生产解析栈/网关轻量模型(OCR 资源、解析器、LLM 出题模型)· ② 密级口径与 perm_tag 映射 · ③ 内规修订说明提供范围 · ④ 案例自然人姓名脱敏 · ⑤ 外规来源渠道与 manifest 填写分工 · ⑥ 业务域/违规类别字典初版评审 · ⑦ dict_entity_types 评审(E2 实体类型)· ⑧ 期限归一口径(月→30/季→90 是否被业务接受)· ⑨ 监督共享来源/类型枚举(P-MISC)。

> 多数 §16 项是生产确认待办;LLM 触点统一受 CP-005-①③(网关轻量模型/配额)阻塞。

## 维护规则(每轮 SDD 收口强制 reconcile)

1. 实装一条需求 → 该行改 ✅ **并挂 test 文件**(无测试只能记 🟡)。
2. LLM 触点接真模型链路 → 去 🤖 行的"需开发"标记,挂集成测试。
3. 新轮 SPEC 的"不做"项 → 对应 RTM 行保持 ❌/🟡,不偷改。
4. 每轮 TASKS 收尾同时更新 GAP **和** RTM,并核对 ✅ 行确有通过测试。
5. §16 项 confirmed 落地 → 去该行 §16 标记。
