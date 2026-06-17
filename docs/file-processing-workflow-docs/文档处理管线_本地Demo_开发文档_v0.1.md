# 文档处理管线 · 本地 Demo 开发文档（V0.1）

> 上游文档：《文档处理与语料库构建_技术框架设计_v1.5》（下称"生产设计"）
> 定位：生产设计 S0–S5 主干的**本地最小可运行实现**，在真实样例文件上验证管线骨架、状态机、四级锚点、版本链与幂等性
> 裁剪原则：**裁机制、不裁契约**——IR schema、PG 表结构与字段名、Milvus collection schema、chunk_id 公式、manifest 列契约与生产设计完全一致；被裁掉的机制逐项登记回迁触发条件（§1.3），demo 代码可平滑演进为生产代码，而非一次性原型
> 文档性质声明：沿用既有约定，【标准】= 行业成熟实践；⚠ = 合成启发式/工程默认值（demo 中全部收口到 config，可调）

---

## 0. Demo 目标

### 0.1 要证明什么（验收点）

| # | 验证点 | 对应生产设计 | 验收方式 |
|---|---|---|---|
| V1 | S0–S5 端到端跑通 | §1 | batch01 全部文档到达终态（INDEXED / 降级 / 隔离），无悬挂状态 |
| V2 | 质检硬关卡 + 补录闭环 | §5 | 坏样例被拦截并给出失败指标与定位证据 → CLI 修复 IR → 重入 QC → INDEXED；降级入库路径可走通 |
| V3 | 四级锚点（条款→文档→页码→版本）可回放 | §6 + §21 T4 | demo 集锚点回放通过率 100%（degraded 文档除外） |
| V4 | 版本替代原子切换 | §7.3 | batch02 新版入库后，默认检索不命中旧版；`--include-superseded` 可见且带 superseded 标注 |
| V5 | 幂等重跑 | §6.5 | 同批次重复 ingest 两次：PG chunk 数不变、无重复 chunk_id、Milvus 实体数稳定 |
| V6 | PG 权威 + Milvus 可重建 | §12 | drop collection → `demo rebuild` → 同一查询 top10 结果一致（无需重新编码，向量从 PG 冷备回灌） |
| V7 | 批次检索冒烟 | §21 T2 | 批次冒烟通过率 100%（demo 集），断言含 status 过滤位 |
| V8（可选开关） | E1 义务条款预打标 | §19.1 | 抽 20 条 is_obligation 标记人工核对，准确率 ≥90% ⚠ |

### 0.2 不证明什么（防止 demo 目标漂移）

- **不证明真实语料的解析质量与阈值取值**——那是语料评估 V0 的职责。demo 阈值全部为 config 默认值 ⚠，不据 demo 结果对甲方承诺任何指标
- 不证明吞吐、并发与摄取排期（生产设计 §13 不在 demo 范围）
- 不证明权限：perm_tag 按 manifest 密级映射写入全链路（PG + Milvus 标量），但**过滤逻辑不执行**——与制度查询智能体既有默认一致（字段预留、逻辑未实现）
- 不含 OCR、知识图谱（S6）、富集 E2–E4、评测 T1/T3/T5/T6、敏感词、AI 标识、SSO（见 §1.3 移除清单）

---

## 1. 裁剪对照表（本文档的核心决策）

裁剪依据：机制是否锚定在"验收条款/红线"或"已测量的失败"上。只锚定"推测失败模式"的机制降为**触发式建设**，不进 demo 与一期首批 CC 任务。

### 1.1 保留——契约级，与生产设计逐字一致

| 项 | 生产设计出处 | 说明 |
|---|---|---|
| manifest 列契约（9 必填列） | §3.1 | Excel 读取，校验规则同生产；这是导入入口的对甲方契约，demo 即开始固化 |
| 统一中间表示 IR（blocks/tables/bbox/page） | §4.2 | 全字段保留。IR 是解析器与下游的稳定边界，是解析器可替换的前提（§6.2） |
| 文档级状态机 + pipeline_events 全量留痕 | §1.1 | 枚举取子集（去掉 REPARSE 系），事件表结构不变 |
| chunk_id 确定性公式 | §6.5 | `sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]`，幂等性的根基，一字不改 |
| 条款树正则 + 中文数字归一化 + clause_path_norm | §6.1 | 含"第X条之一"、虚拟根节点等边界处理 |
| 切块规则全套（原子=条、超长拆/超短不合并、父块仅 PG、面包屑前缀、页码锚点） | §6.2 | 唯一例外：表格块的 LLM 摘要前缀降级为仅面包屑（§1.2） |
| internal_refs[] 正则捕获 | §6.1 | 廉价前置信号，保留；clause_references/ref_resolver 不建（§1.3） |
| PG 数据模型字段名与 add-only 原则 | §10 | 建表子集（§5），字段名/类型/枚举与生产一致，直接可导出《数据字段字典》种子 |
| Milvus collection `audit_corpus` 全 schema | §8.2 | 含 perm_tag、biz_domain、issuer_level 等全部标量字段与 partition key；HNSW 参数同默认 ⚠ |
| 版本链 revise_replace / abolish_only + INDEXED 后原子切换事务 | §7.2–7.3 | 旧版本向量保留不删、status 标量批量更新，与生产同 |
| 写入顺序与一致性模型（PG 先行 → Milvus upsert → flush → INDEXED） | §12.1 | staging 状态屏蔽半成品，同生产 |
| 向量 PG bytea 冷备 + rebuild | §12.3 | 服务 V6 验收点，演示"Milvus 不承担数据安全责任"这一架构原则 |
| T2 批次检索冒烟 / T4 锚点自动回放 | §21.2 / §21.4 | 两个最便宜、最高 ROI 的验证组件，demo 期即固化为代码资产 |
| E1 义务预打标（正则，零 LLM） | §19.1 | config 开关，默认开；为后续比对智能体 demo 预热 |
| 对账命令 | §12.2 | 由夜间任务降为手动 CLI 命令，逻辑同生产 |

### 1.2 简化——机制降级、契约不变（demo 完成后按原设计回迁）

| 项 | 生产机制 | Demo 实现 | 回迁路径 |
|---|---|---|---|
| 编排 | Temporal workflow + Signal 人工关卡 | **PG 状态机驱动的单进程 worker 轮询**；人工关卡 = 文档停在等待态，CLI 命令推进状态（等价于发 signal） | 各 stage 实现为无副作用纯函数（输入 doc_version_id + 状态，输出新状态 + 产物落盘），生产期逐函数包装为 Temporal activity，编排层替换不动业务代码。注：Temporal 在信创内网的部署可行性本身待验证（已列 P0），demo 的 PG 轮询方案同时是生产降级预案的预演 |
| 补录工作台 | Web 工作台、IR 并排视图 | **统一 CLI 审核队列**（一个队列模型承载 QC 补录 / 隔离裁决 / 元数据确认三类，type 字段区分），`queue show` 输出失败指标 + 定位证据 + IR 片段，人工直接编辑 IR JSON 后 `queue fix` 重入 | 队列模型与处置动作枚举（fix/degrade/reject/approve）即生产统一工作台的领域模型，生产期只加 Web 壳。呼应既定结论：7 个人工环节合并为 1 个工作台 |
| 元数据 L3 人工确认 | META_REVIEW 工作台逐件确认 | `meta confirm` CLI（支持单件与批量），确认动作写 pipeline_events | 同上，进统一工作台 |
| 元数据 L2（LLM 辅助业务域/摘要） | 14B/网关轻模型 + 字典约束 | **默认关闭**（config 开关）。开启时走既有 LLM 工厂，prompt 入根目录 PROMPTS.md（既定约定）；关闭时业务域取 manifest 声明值 | 生产期切网关 endpoint（CP-005-①），代码不变 |
| 表格块摘要前缀 | LLM 生成一句摘要 ⚠ | 仅面包屑前缀，无 LLM 摘要 | 触发条件：V0 实验轨 A/B 显示表格召回不足时开启 |
| 修订说明结构化 | 条目切分 + LLM 对齐 diff + 置信度 | 仅存全文（revision_notes.raw_text）+ 人工录入条目（CLI），不做 LLM 对齐 | 变更查询智能体开发启动时回迁 |
| merge_replace / split_replace | 多对一、一对多版本关系 | 枚举值保留，逻辑不实现（命中 → 队列报"demo 不支持，转人工"） | 生产 W1 前实现 |
| 批次质量报告 / 看板 | 看板 12+ 指标 | `demo report <batch>` 输出 JSON + 控制台摘要（解析成功率、QC 一次通过率、各终态计数、T2/T4 通过率、锚点填充率） | 看板读同一份 JSON 结构，生产期加可视化 |
| Golden set 回归 | 50 件人工标注 + F1≥0.98 门禁 | **mini golden set = pytest fixtures**：5–8 件样例文档的人工标注条款树（JSON），`pytest` 即回归；解析配置变更必须先过测试 ⚠ | W1 扩充至 50 件，机制不变 |
| 边缘通过带 | §18.2-1，自动升级人工抽检 | 保留为 `qc_marginal=true` 标记（任一指标落 [阈值, 阈值+ε]），仅写入批次报告，不建独立抽检流 | 生产期接入抽检配额逻辑 |
| 解析兜底 | MinerU 重试一次 | 关闭。单解析通道，失败即 PARSE_FAILED 进队列 | W1 前接入 |
| OCR 分支 | PaddleOCR GPU 池 | 关闭。扫描件（字符密度 <50 字/页 ⚠）→ QUARANTINED，错误码 E202-DEMO"OCR 未启用"，**作为隔离路径的演示样例使用** | 扫描件占比由 V0 实测后决定 W1 接入规模 |
| 对象存储 | MinIO | 本地文件系统，目录结构与 MinIO key 布局一致（`raw/{corpus_type}/{batch_id}/{doc_version_id}.{ext}`、`ir/{doc_version_id}.json`），经 ObjectStore 接口抽象 | 生产期实现 MinIO adapter，路径不变 |

### 1.3 移除——不进 demo，登记回迁触发条件

| 项 | 生产设计出处 | 回迁触发条件 |
|---|---|---|
| §18.2-3 双解析器仲裁、§18.2-4 高危 token 复核 | §18.2 | W1 实测确认类型 A/B 逃逸 ≥3 例，或 V0 实测扫描件占比 >20% ⚠ |
| §18.3–18.5 质量工单 / REPARSE 工作流 / 失效传播 / 逃逸率指标 | §18 | demo 以 `reprocess <doc_version_id>` 命令覆盖（确定性 chunk_id 使全量重跑天然安全：同 ID 覆盖 + 按 doc_version_id 范围清孤儿）；工单与传播机制在试运行前建设 |
| §18.2-2 页眉泄漏 / 句完整性指标（指标 8/9） | §18.2 | W1 抽检发现类型 A/D 样本后规则化 |
| 富集 E2（LLM 事项/部门打标）、E3（图谱探针）、E4 | §19.2–19.4 | E2：比对智能体开发启动 + 字典经张老师评审；E3：图谱 POC 通过；E4 维持"仅留 schema"原决策 |
| 评测 T1（出题增殖）/ T3（规模台阶）/ T5（负样本）/ T6（分数分布） | §21 | T3 仅在正式 W1–W3 分批入库窗口存在，demo 无规模台阶；T1/T5/T6 随正式 W0 启动 |
| S6 图谱抽取 + §6.6/6.7 ref_resolver（clause_references 表） | §6.6–6.7 | 图谱 POC 启动时建设；internal_refs[] 正则已在 demo 保留作前置信号 |
| P-QA / P-CASE 处理档案 | §2 / §6.3–6.4 / §9 | demo 语料仅内规 + 外规（P-INT / P-EXT）。P-QA 切分器为简单正则可随时加；P-CASE（要素抽取、cases 表）在 W3 前建设 |
| 敏感词过滤 / AI 内容标识 / SSO / Casbin 执行逻辑 | §14 | 生产横切项，依赖甲方网关与认证环境，本地 demo 无对接条件 |
| 解析/OCR/嵌入三池信号量限流、continue-as-new | §11.1 | demo 单 worker 无此问题；随 Temporal 回迁 |
| 夜间定时任务（对账） | §12.2 | demo 为手动命令；生产期加调度 |

---

## 2. 技术栈与默认决策 ⚠（均可在 config 调整）

| 项 | Demo 默认 | 说明 |
|---|---|---|
| 语言/运行时 | Python 3.11 | 与既有制度查询智能体 demo 一致 |
| CLI | typer | 命令清单见 §10 |
| ORM / 迁移 | SQLAlchemy 2.x + Alembic | add-only 由迁移脚本约束 |
| PG | PostgreSQL 16（Docker） | |
| 向量库 | Milvus 2.4 standalone（Docker，自带 etcd/minio 与业务对象存储无关） | 既定默认 |
| Embedding | **EmbeddingClient 接口**，两个实现：① 本地 FlagEmbedding BGEM3FlagModel（CPU 即可，demo 量级 ~千级 chunk）② OpenAI 兼容 endpoint（env 配置，对齐生产 CP-005 网关口径） | dense+sparse 一次产出【标准】；本地模型首次需外网下载 ~2GB，文档需写明离线缓存路径用法（驻场环境无外网） |
| 解析 | **ParserAdapter 接口**，两个实现：① light 解析器（python-docx + pdfplumber）→ IR；② DeepDoc adapter（vendored 自 RAGFlow 仓库 deepdoc 模块 ⚠，无独立 PyPI 包，集成成本待实测） | **M1 里程碑用 light 解析器跑通全骨架，M2 替换 DeepDoc**。IR 是稳定边界，替换解析器不动下游——这同时验证了"解析器可替换"这一架构属性 |
| LLM（仅 L2 开启时） | 既有 LLM 工厂（Kimi/OpenAI/DeepSeek） | prompt 集中于根目录 PROMPTS.md（既定约定）；demo 默认零 LLM 调用 |
| 部署 | docker compose（pg + milvus）+ 宿主机跑 Python | 与制度查询智能体 demo 同栈，可共用 compose |

---

## 3. Demo 架构

```
┌─────────────────────────────────────────────────────────┐
│ CLI (typer)                                              │
│  ingest / status / queue / meta / search / verify /      │
│  rebuild / reconcile / reprocess / report                │
├─────────────────────────────────────────────────────────┤
│ Orchestrator（单进程 worker）                             │
│  循环：SELECT 可推进文档 BY pipeline_status               │
│        → 调用对应 stage 纯函数 → 条件迁移状态 → 写 events  │
│  人工等待态（QC_FAILED/META_REVIEW/QUARANTINED）不轮询，    │
│  等 CLI 推进                                              │
├──────────┬──────────────────────────────────────────────┤
│ stages/  │ s0_register → s1_parse → s2_qc → s3_structure │
│ (纯函数) │ → s4_meta → s5_embed_index → finalize          │
├──────────┴──────────────────────────────────────────────┤
│ verify/  smoke(T2) · anchor_replay(T4) · reconcile ·     │
│          rebuild · idempotency_check                     │
├─────────────────────────────────────────────────────────┤
│ PG 16（权威）│ Milvus 2.4（投影）│ 本地FS ObjectStore（原件+IR）│
└─────────────────────────────────────────────────────────┘
```

## 4. 状态机（Demo 版，生产枚举的子集）

```
REGISTERED → PARSING → QC_PENDING ─┬→ STRUCTURING → META_REVIEW ─┬→ EMBEDDING → INDEXING → INDEXED
     │           │                 │   (自动)        (CLI确认放行)  │
     │           ▼                 ▼                              ▼
     │      PARSE_FAILED      QC_FAILED ──(queue fix)──→ QC_PENDING(重入)
     │      (→统一队列)        (→统一队列) ──(queue degrade)──→ DEGRADED_INDEXED
     ▼                                  ──(queue reject)───→ REJECTED
 QUARANTINED（hash疑似重复 / 密级缺失 / 格式白名单外 / 扫描件）
   ──(queue 裁决: release重入 / reject)
```

- 去掉的生产状态：REPARSE_PENDING / REPARSING（由 `reprocess` 命令直接覆盖：全管线重跑 + 按 doc_version_id 清孤儿）
- DEGRADED_INDEXED：等价生产"降级入库"，chunks.degraded=true，仅全文检索可见、不参与条款级引用、T4 回放豁免并显式标注
- 每次迁移写 `pipeline_events`（时间、操作者[system/CLI用户名]、前后状态、错误码）——契约同生产 §11.2 错误码体系，demo 实现 E1xx/E2xx/E3xx/E4xx/E5xx/E6xx/E7xx/E8xx 中实际触达的子集

## 5. 数据模型（PG，建表子集，字段名与生产 §10 一致）

**建表**：`import_batches`、`documents`、`doc_versions`、`chunks`（含 dense_vec_cold/sparse_vec_cold bytea 冷备列 ⚠）、`pipeline_events`、`remediation_records`、`revision_notes`（简化：raw_text + 人工条目）、`clause_tags`（E1）、`review_queue`（demo 新增，统一审核队列：queue_type[qc_fix/quarantine/meta_confirm]、doc_version_id、原因、证据 JSON、处置、处置人、时间——此表即生产统一工作台的领域模型种子）、字典种子表 `dict_issuers` / `dict_biz_domains`（CSV seed 导入）。

**不建**（schema 文件中以注释保留 DDL，add-only 演进）：`cases`、`clause_references`、`quality_tickets`、`doc_graph_stats`、`obligation_keywords`（E1 demo 用内置正则 + 配置词表，词典表随比对智能体建设）。

所有表带 created_at/by、updated_at/by。Alembic 迁移即生产迁移的第一批版本。

## 6. 各阶段实现规格

### S0 接入与登记（s0_register）

与生产 §3 一致的部分：manifest 9 必填列校验（不匹配整批拒收）、SHA-256 精确去重（命中 → 批次报告标注关联 doc_id）、疑似重复（标题+文号命中但 hash 不同）→ QUARANTINED 进队列、ULID 双 ID（logical/version，替代声明时 logical_id 继承）、原件落 ObjectStore 只写一次、magic number 格式探测不信任扩展名。

Demo 简化：发文字号正则、文件命名规范检查 → 仅告警入批次报告不阻断（同生产）；机构字典未命中 → 写"待确认"标记不阻断 ⚠（生产为待确认队列）。

### S1 解析（s1_parse）

- 路由（demo）：docx → ParserAdapter(office)；pdf 有文本层 → ParserAdapter(pdf)；pdf 无文本层（<50 字符/页 ⚠）→ QUARANTINED(E202-DEMO)；xlsx/图片 → QUARANTINED(E101-DEMO 白名单外，demo 范围仅 docx/pdf)
- 输出统一 IR JSON 落 `ir/{doc_version_id}.json`，全字段同生产 §4.2（light 解析器无 bbox 时 bbox 置 null、page 必填——page 是 T4 回放的最低要求，light 解析器必须保证 page 正确）
- 超时：单文档 5 min ⚠ → PARSE_FAILED(E203)

### S2 质检硬关卡（s2_qc）

生产 7 指标的 demo 实现（阈值入 `config/qc_thresholds.yaml`，全部 ⚠）：

| # | 指标 | Demo 实现 | 默认阈值 ⚠ |
|---|---|---|---|
| 1 | 条款覆盖率 | 结构化"第X条"数 ÷ 全文正则扫描数 | ≥95% |
| 2 | 条号连续性 | 缺口数（允许"第X条 删除"占位） | =0 |
| 3 | 层级合法性 | 章→节→条倒挂块数 | =0 |
| 4 | 页码锚点完整率 | 有 page 的 block 占比 | =100% |
| 5 | 表格一致性 | 行×列 vs 单元格数；空表占比 | 空表 ≤5% |
| 6 | 文本质量 | 非 CJK 乱码占比（OCR 项 N/A） | ≤1% |
| 7 | 抽取充分性 | 字符数 ÷ (页数 × 中位密度) | ≥0.7 |

- 任一不达标 → QC_FAILED，evidence JSON 写明失败指标 + 定位（页码/条号区间），进统一队列
- 边缘通过带：落 [阈值, 阈值+ε]（ε 入 config）→ `qc_marginal=true` 仅标记入报告
- 三处置（CLI）：`fix`（人工编辑 IR JSON 后重入 QC）/ `degrade`（DEGRADED_INDEXED）/ `reject`（退回，记录原因——对应生产"退回甲方"）

### S3 结构化与切块（s3_structure）

完全按生产 §6.1–6.2、§6.5 实现（保留清单见 §1.1）：条款树七类节点正则、中文数字归一化、`21bis/21.1b` 插入条、虚拟根节点、internal_refs[] 捕获；切块六规则（300–600 token 目标、超长按款拆+条头续接、超短独立、父块=节级仅 PG ≤2000 token、表格独立块按行组拆+重复表头、面包屑前缀、页码跨度锚点）；确定性 chunk_id。

Demo 唯一差异：表格块无 LLM 摘要前缀（§1.2）。

### S4 元数据与版本链（s4_meta）

- L1 规则抽取：发文字号/日期/机构（字典匹配）/标题，**与 manifest 交叉校验，不一致 → 冲突标记进统一队列**（同生产）
- L2：默认关闭（§1.2）
- L3：文档停在 META_REVIEW，`meta confirm` 放行（P-INT 逐件、P-EXT demo 量小也逐件 ⚠）
- 版本链：revise_replace / abolish_only；INDEXED 后原子切换事务三步同生产 §7.3（PG 新旧 status 互换 → Milvus 旧版 chunk status 标量批量改 superseded 不删除 → doc_versions 写关系）。下游通知（比对队列/打标队列）打日志占位，不实现消费方

### S5 向量化与索引（s5_embed_index）

- EmbeddingClient：batch=64、max_length=1024 ⚠、指数退避 ×3、块级失败队列不阻塞同文档其他块（文档级 INDEXING 前检查全部块就绪）——同生产 §8.1
- Milvus 写入：批量 upsert（500/批 ⚠）→ flush 成功 → PG 置 INDEXED；INDEXED 前 chunk status=staging 对检索不可见——同生产 §8.2
- dense/sparse 向量同步落 PG bytea 冷备（服务 rebuild）
- finalize：触发 T2 冒烟 + T4 回放（见 §9），结果入批次报告（**不阻断终态**——评测组件无阻断权，同生产 §21.2）

---

## 7. 统一 CLI 审核队列（人工环节唯一入口）

设计意图：生产设计隐含 7 个人工环节 = 7 个工作台 UI，已评审认定为排期暗坑；demo 起即用**一个队列模型**承载全部人工处置，生产期只加 Web 壳。

| queue_type | 来源 | 可用处置 |
|---|---|---|
| qc_fix | QC_FAILED / PARSE_FAILED | fix（编辑 IR 重入）/ degrade / reject |
| quarantine | S0 隔离（疑似重复/密级缺失/扫描件/白名单外） | release（人工裁决后重入指定状态）/ reject |
| meta_confirm | META_REVIEW + L1/manifest 冲突 | approve（可附字段修正）/ reject |

每次处置写 `remediation_records` + `pipeline_events`（操作人 = CLI `--user` 参数，默认取系统用户名）。`queue show <id>` 输出：失败指标、定位证据、IR 相关片段路径、原文页码提示——等价生产"IR 与原文并排视图"的命令行版。

## 8. 配置与工程约定

```
audit-doc-pipeline-demo/
├── compose.yaml                  # pg16 + milvus2.4（可与制度查询demo共用）
├── config/
│   ├── settings.toml             # 连接串、embedding模式(local/endpoint)、L2/E1开关
│   ├── qc_thresholds.yaml        # §6-S2 七指标阈值 + 边缘带ε（全部⚠）
│   └── profiles.yaml             # P-INT / P-EXT 档案差异（抽检率字段保留不消费）
├── seeds/                        # dict_issuers.csv / dict_biz_domains.csv
├── fixtures/                     # 样例语料（§11）+ manifest.xlsx
│   ├── batch01/
│   └── batch02_revision/
├── PROMPTS.md                    # 既定约定；demo默认零LLM，文件存在并声明"L2开启时启用"
├── alembic/                      # 迁移即生产迁移第一批版本（add-only）
├── src/pipeline/
│   ├── cli.py / orchestrator.py
│   ├── stages/ s0..s5（纯函数，签名统一：(ctx, doc_version_id) -> StageResult）
│   ├── ir.py（pydantic模型=IR契约）
│   ├── parsing/ adapter.py + light_parser.py + deepdoc_parser.py
│   ├── chunking/ clause_tree.py + normalize.py + chunker.py
│   ├── qc/ indicators.py + gate.py
│   ├── meta/ l1_rules.py + version_chain.py
│   ├── enrich/ e1_obligation.py
│   ├── index/ embedding_client.py + milvus_io.py + pg_io.py + object_store.py
│   └── verify/ smoke.py + anchor_replay.py + reconcile.py + rebuild.py
└── tests/                        # mini golden set（§12）
```

约定：schema 变更 add-only；stage 纯函数禁止互相 import（只通过 PG 状态与 ObjectStore 产物通信，这是 Temporal 回迁的前提）；所有 ⚠ 数值禁止硬编码，必须从 config 读。

## 9. 验证组件（demo 的差异化价值所在）

| 组件 | 实现 | 触发 |
|---|---|---|
| T2 冒烟 | 每文档 1 条合成查询 = 标题 + 首条款前 30 字 ⚠，断言 hit@50 且携带 status=effective 过滤；失败记 E801/E802 入报告，不回退批次 | finalize 自动 + `verify smoke` 手动 |
| T4 锚点回放 | 逐 chunk：按 page_start 取原件该页（±1 页）文本 → 剥离面包屑后精确匹配定位；degraded 豁免 | finalize 自动 + `verify replay` 手动 |
| 对账 | 逐 doc_version 比对 PG chunk 数 vs Milvus count，不平 → E701 + 以 PG 为准重灌 | `verify reconcile` |
| rebuild | drop collection → 从 PG chunks + bytea 冷备全量重灌（零编码） | `demo rebuild` |
| 幂等检查 | 重复 ingest 后断言：chunk_id 集合不变、Milvus num_entities 不变、pipeline_events 有第二次运行记录 | `verify idempotency`（封装 V5 验收） |

## 10. CLI 命令清单与演示脚本

命令：`demo up|down` · `demo ingest <dir> --manifest <xlsx>` · `demo status [batch]` · `demo queue list|show|fix|degrade|reject|release <id>` · `demo meta list|confirm <id|--batch>` · `demo search "<q>" [--include-superseded] [--corpus internal|external] [--topk N]` · `demo verify smoke|replay|reconcile|idempotency` · `demo rebuild` · `demo reprocess <doc_version_id>` · `demo report <batch>`

**标准演示脚本（≈15 分钟，对内/对张翼飞演示用）**：

1. `demo up` → 建库建集合
2. `demo ingest fixtures/batch01` → 控制台滚动状态迁移；预期 10 件 INDEXED 在途、1 件 QC_FAILED、1 件 QUARANTINED
3. `demo queue list` / `queue show` → 展示失败指标与定位证据（"第7条后缺第8条，第3页"）
4. `demo queue fix <id>`（演示编辑 IR 修复跳号）→ 重入 → INDEXED；`queue reject` 隔离件（扫描件，演示退回路径）
5. `demo meta confirm --batch` → 放行全部 META_REVIEW
6. `demo report batch01` → T2/T4 100%、锚点填充率、各状态计数
7. `demo search "费用报销 审批权限"` → 结果带四级引用（条款路径/文档+文号/页码/版本+状态）
8. `demo ingest fixtures/batch02_revision`（manifest 含"替代"声明）→ `demo search` 同一问题：默认只见新版；`--include-superseded` 旧版可见且标 superseded —— **版本链核心演示**
9. `demo verify idempotency`（重跑 batch01）→ 零重复
10. `demo rebuild` → 重建后同一查询结果一致 → 收尾讲"PG 权威、Milvus 可重建"

## 11. 样例语料集规格（fixtures）

| 批次 | 件数 | 构成 | 覆盖的验证面 |
|---|---|---|---|
| batch01 | 12 | 内规 docx ×6（标准章节条 ×3、含大表格跨行组 ×1、含超长条款 ×1、无章直条短通知 ×1）；外规 pdf 文本层 ×4（部门规章 ×2、自律规则 ×1、含"第X条之一" ×1）；坏样例 ×2（扫描 pdf ×1 → 隔离演示、人工制造条号跳号 docx ×1 → QC 拦截演示） | 条款树边界、表格切块、超长拆分、虚拟根、插入条、QC、隔离 |
| batch02_revision | 2 | batch01 某内规的新版本 docx ×1（manifest 声明替代）+ 修订说明全文 ×1（CLI 录入 revision_notes） | 版本链、原子切换、默认过滤 |

语料来源：优先用脱敏真实制度（如已可得）；不可得则用公开监管规则 + 自拟内规模板构造 ⚠。坏样例必须人工构造以保证失败模式确定可复现。

## 12. 测试（mini golden set）

- 5–8 件 fixtures 文档人工标注完整条款树（JSON ground truth），pytest 断言条款树结构 F1 = 1.0（demo 集应全对；生产 50 件集才用 ≥0.98 ⚠ 门槛）
- 单元测试必覆盖：中文数字归一化全分支、七类节点正则、插入条/虚拟根边界、chunk_id 确定性（同输入两次调用同输出）、超长条拆分的条头续接
- 解析器替换回归：light → DeepDoc 切换后 mini golden set 必须仍全过——这是 M2 里程碑的准入门槛

## 13. 里程碑 ⚠

| 里程碑 | 内容 | 出口 |
|---|---|---|
| M1（~5 工作日） | 骨架 + S0–S5 全链路（light 解析器）+ 状态机 + CLI 队列 + 演示脚本 1–9 步可跑 | V1/V2/V4/V5 通过 |
| M2（~3 工作日） | DeepDoc adapter 接入 + T2/T4/rebuild/对账 + mini golden set | 全部 V1–V7 通过，演示脚本完整 |
| M3（可选，~1 日） | E1 打标 + report 完善 + 录屏 | V8 |

DeepDoc vendoring 若超 1 日仍未跑通 ⚠：M2 降级为继续用 light 解析器交付演示，DeepDoc 接入单列任务——IR 边界保证此降级不影响其他验收点。

## 14. CC 任务拆分与强制澄清

建议拆 2 个 CC 任务（demo 体量不需要生产建议的 3 个）：

- **T-A 管线骨架**：S0–S2 + 状态机 + orchestrator + 统一队列 CLI + ObjectStore + Alembic 首批迁移。锁定决策：状态机枚举、manifest 契约、IR 契约、stage 纯函数签名、add-only
- **T-B 切块索引与验证**：S3–S5 + EmbeddingClient 双实现 + Milvus schema + 版本链切换 + verify 四组件 + mini golden set + fixtures 构造脚本。锁定决策：chunk_id 公式、切块六规则、写入顺序、冷备列

两个任务提示词均沿用既定强制澄清机制：存在关键歧义时暂停并提出 ≥3 个问题再动手；schema/接口 add-only；禁止绕开 ParserAdapter/EmbeddingClient/ObjectStore 抽象直连实现。

## 15. 待确认事项（demo 范围内）

| # | 事项 | 影响 | 默认处理 |
|---|---|---|---|
| 1 | demo 语料能否拿到脱敏真实制度样例（哪怕 5–10 件） | fixtures 真实性、对张翼飞演示说服力 | 默认公开规则 + 自拟模板 ⚠ |
| 2 | 本地 embedding 跑 FlagEmbedding 还是直接配可用 API endpoint | 首次模型下载 2GB 外网依赖 | 默认本地，endpoint 留 env |
| 3 | demo 是否需要与制度查询智能体 demo 共库（同一 Milvus collection 供其检索） | collection 命名与分区规划 | 默认共用 `audit_corpus`，制度查询 demo 直接受益于本管线产出 |
| 4 | DeepDoc vendoring 的许可证与信创合规口径 | M2 与生产解析选型 | 默认按既定选型推进，合规口径与张翼飞确认 |

## 16. 性质声明

- 【标准/成熟实践】：确定性 ID 幂等写入、PG 权威 + 投影可重建、状态机 + 事件留痕、IR 稳定边界与适配器模式、结构面包屑上下文化切块、训练-服务编码一致性（demo 的 EmbeddingClient 钉死单实现单版本）
- 【合成启发式 ⚠】：全部阈值默认值（七指标、边缘带 ε、token 区间、批量参数）、里程碑工期、light 解析器降级策略、T2 合成查询构造法、demo 语料构成
- 本文档的裁剪决策（§1）属工程判断，建议与张翼飞过一遍 §1.3 移除清单的回迁触发条件后再生成 CC 任务提示词
- demo 不对甲方演示、不对甲方陈述任何指标；对甲方口径仍以生产设计 V1.5 + 语料评估 V0 实测为准

## 17. 变更记录

| 版本 | 内容 |
|---|---|
| V0.1 | 初版：基于生产设计 V1.5 + 过度设计评审结论（裁机制不裁契约、统一审核队列、Temporal 降级为 PG 轮询、T2/T4 保留、§18.2/§19 E2-E3/§21 T1·T3·T5·T6/S6 移除并登记触发条件） |
