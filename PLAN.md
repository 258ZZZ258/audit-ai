# 实施计划:文档处理管线 · 本地 Demo（M1 · Phase 2）

> 上游:`SPEC.md`(M1 规格,四个验收点 V1/V2/V4/V5)。
> 本计划只回答*怎么建、什么顺序、有什么风险、何处验证*。任务级拆分(Phase 3)在评审通过后写入 `TASKS.md`。
> 状态:**等待人工评审**——批准后才进 Phase 3(Tasks)。

---

## 1. 组件清单与依赖

按"被依赖程度"由底到顶分层。箭头 = 依赖方向(上层依赖下层)。

```
                         ┌─────────────────────────────────────────────┐
  L6  入口/演示          │ CLI(typer)· 演示脚本第 1–9 步               │
                         └───────────────┬─────────────────────────────┘
                                         │
  L5  编排               │ Orchestrator(单进程轮询 worker)· 状态机迁移 │
                         └───────────────┬─────────────────────────────┘
                                         │ 调用纯函数 stage
  L4  阶段(纯函数)      s0_register  s1_parse  s2_qc  s3_structure  s4_meta  s5_embed_index  finalize
                              │          │        │         │           │            │
            ┌─────────────────┴───┐  ┌───┴────┐ ┌─┴──┐  ┌───┴─────┐ ┌────┴────┐  ┌────┴──────────┐
  L3  领域逻辑(可单测)  manifest校验  ParserAdapter QC指标  clause_tree   L1规则     EmbeddingClient
                       SHA256去重    /light_parser /gate  normalize     version_   milvus_io
                       ULID/格式探测                       chunker        chain      (混合检索/冷备)
                                                          chunk_id
                              │          │        │         │           │            │
  L2  基础设施          ┌─────┴──────────┴────────┴─────────┴───────────┴────────────┴──────┐
                       │ ObjectStore(本地FS) · pg_io(SQLAlchemy) · review_queue 模型       │
                       └──────────────────────────────┬───────────────────────────────────┘
                                                      │
  L1  契约/底座         IR(pydantic)· 状态机枚举 · StageContext/StageResult · config 加载
                       PG schema + Alembic 首批迁移 · Milvus audit_corpus schema · 错误码表
                       ───────────────────────────────────────────────────────────────────
  L0  环境             compose.yaml(pg16 + milvus2.4)· seeds(字典CSV)· fixtures(语料)
```

**关键架构不变量**(全程守住,来自 SPEC 边界):stage 纯函数互不 import、只经 PG 状态 + ObjectStore 通信;状态迁移与 `pipeline_events` 只由 orchestrator 写;一切走 `ParserAdapter`/`EmbeddingClient`/`ObjectStore` 接口;`chunk_id` 公式与 PG 字段名逐字不动。

**页码锚点(S1 内含,不新增状态)**:S1 先用 `soffice` 生成规范渲染件(`rendition/`),结构从 docx XML 抽,页码用 `page_align` 文本对齐从渲染件回填(单调两指针 + rapidfuzz 兜底,未中 → `page=null` → QC4 拦截)。`page_align` 为 L3 纯逻辑、可单测。渲染件写一次、reprocess 复用。详见 SPEC《页码锚点机制》。

## 2. 构建顺序(4 阶段)与验证检查点

每阶段末有一个**可执行的检查点**,过不了不进下一阶段。

### 阶段 A — 底座与环境(L0–L1 + 部分 L2)

建:repo 布局、`config/` 三文件加载器、`ir.py`(IR pydantic 模型)、状态机枚举、`StageContext`/`StageResult`、PG schema + Alembic 首批迁移(`import_batches`/`documents`/`doc_versions`/`chunks`(含 `dense_vec_cold`/`sparse_vec_cold` bytea)/`pipeline_events`/`remediation_records`/`revision_notes`/`clause_tags`/`review_queue`/`dict_*`)、`object_store.py`、`pg_io.py` 基础、`compose.yaml`、seeds 导入、`PROMPTS.md` 占位、README(写明 `HF_HOME` 离线缓存路径)。

> **检查点 A**:`demo up` 拉起 pg+milvus;`alembic upgrade head` 建表成功;`from pipeline.ir import *` 等契约模块可导入;`pytest` 空跑通过;字典 seed 入库。

### 阶段 B — 接入到质检(L4 的 S0–S2 + L5 编排 + queue CLI)

建:`orchestrator.py`(轮询循环 + 状态迁移 + 写 events;人工等待态不轮询)、`s0_register`(manifest 9 列校验、SHA-256 去重、ULID 双 ID、magic number 格式探测、隔离路由)、`s1_parse`(渲染件生成 `soffice`→`rendition/`、`light_parser` 从 docx XML 抽结构、`page_align` 文本对齐回填页码;docx→office、pdf 文本层→pdf、扫描件→`QUARANTINED(E202-DEMO)`、渲染失败→`PARSE_FAILED(E204-DEMO)`、白名单外→`E101-DEMO`)、`s2_qc`(7 指标 + gate + evidence + 边缘带 `qc_marginal`)、`review_queue` 处置流 + `queue list/show/fix/degrade/reject/release` CLI、`status` CLI。**依赖 fixtures 已就绪**(见 §3 并行)。

> **检查点 B**:`demo ingest fixtures/batch01` 后,文档分别落 `QC_PENDING`/`QC_FAILED`/`QUARANTINED`,无悬挂;正常 docx 件页码经渲染件对齐回填、QC 指标4 可评估;`queue show <跳号件>` 打印失败指标 + 页码/条号定位;`queue fix` 后重入 QC。**覆盖 V2 的前半闭环。**

### 阶段 C — 结构化、元数据、向量化(L4 的 S3–S5 + L3 检索)

建:`normalize.py`(中文数字归一化全分支)、`clause_tree.py`(七类节点正则、`第X条之一`、`21bis`、虚拟根、`internal_refs[]`)、`chunker.py`(切块六规则 + 确定性 `chunk_id`)、`s4_meta`(L1 规则抽取 + manifest 交叉校验 + `version_chain` revise_replace/abolish_only)、`embedding_client.py`(本地 BGEM3,dense+sparse 一次产出)、`milvus_io.py`(`audit_corpus` upsert/flush、staging→INDEXED、bytea 冷备写入)、`search` CLI(混合检索 + `status=effective` 默认过滤)、`meta list/confirm` CLI。

> **检查点 C**:正常件全链路到 `INDEXED`;`demo search "<q>"` 返回结果且带四级引用(条款路径/文档+文号/页码/版本+状态);S3 单测全绿(归一化、节点正则、`chunk_id` 确定性、超长拆分续接)。**覆盖 V1 主干。**

### 阶段 D — 版本切换、幂等、报告(L4 finalize + L6 收尾)

建:`version_chain` 的 INDEXED 后**原子切换事务**(PG 新旧 status 互换 → Milvus 旧版 chunk status 标量批量改 `superseded` 不删 → `doc_versions` 写关系)、`batch02_revision` 入库联调、`verify/idempotency.py`、`reprocess` CLI(全量重跑 + 按 `doc_version_id` 清孤儿)、`report` CLI(四项指标 JSON + 控制台,无 T2/T4 键)、`demo up/down` 收尾。

> **检查点 D(总验收)**:V1(全终态无悬挂)、V2(完整闭环 + degrade 路径)、V4(`batch02` 后默认不见旧版、`--include-superseded` 见且标 `superseded`)、V5(`demo verify idempotency` 通过)。演示脚本第 1–9 步端到端跑通;`pytest` + `ruff check` 全绿。

## 3. 可并行 vs 必须串行

| 工作流 | 何时可起 | 关系 |
|---|---|---|
| **fixtures 构造**(batch01 ×12 + batch02 ×2 + manifest) | 阶段 A 一开始即可并行 | **独立流**,但**检查点 B 的前置阻塞**——至少正常件 ×2 + 两件坏样例须先到位才能跑 ingest 联调 |
| **L3 纯逻辑 TDD**(normalize / clause_tree / chunker / chunk_id / page_align) | 阶段 A 完成 `ir.py` 后即可起 | 不依赖 DB/Milvus,**可与阶段 B 并行**先把单测写绿;阶段 C(及 S1 页码)直接装配 |
| **soffice 渲染 + 文本对齐 spike** | 阶段 A 完成后可并行 | **页码现在在 S1 关键路径上**;早期验证 docx→pdf 转换 + 一条对齐链路(命中率/跨页/兜底),降 R5a/R5b 不确定性 |
| **EmbeddingClient + milvus_io 打通(spike)** | 阶段 A 完成后可并行 | 接口隔离,**可与 S0–S3 并行**预研;先解决 BGEM3 sparse→Milvus 稀疏格式转换(见 R2) |
| 主线 A→B→C→D | 串行 | 每阶段检查点为硬门 |

**串行硬依赖**:A 必须最先(契约/建表是一切前提);B 依赖 A + fixtures;C 依赖 A(契约)+ B(状态机/orchestrator 已能驱动);D 依赖 C(需有 INDEXED 件才能演示版本切换与幂等)。

## 4. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| **R1** | 本地 BGEM3 首次需下载 ~2GB,驻场无外网 | 阻塞 S5 / 检查点 C | 预研期先在有网机器拉模型缓存,固化 `HF_HOME` 路径并写入 README;开发机可临时切 endpoint 实现(接口已隔离),但 M1 验收以本地实现为准 |
| **R2** | BGEM3 sparse(`lexical_weights` dict)→ Milvus 2.4 `SPARSE_FLOAT_VECTOR` + hybrid search API 集成成本 | 检查点 C 检索 | 阶段 A 后 spike"写一条 + 混合查一条",转换函数单测固定。**已定兜底**(SPEC 决策2):受阻则退化 dense-only,`report` 标 `retrieval_mode=dense_only`(不静默),sparse 仍入库 + 冷备、schema 不变,M2 启用 hybrid 不改表;V4 不受影响 |
| **R3** | 中文数字归一化 + 条款树正则边界(`第X条之一`/`21bis`/虚拟根) | V2/V3 正确性根基 | **TDD 先行**:阶段 C 用单测覆盖全分支后再装配;坏样例(跳号)的 QC 拦截依赖此处正确 |
| **R4** | `chunk_id` 跨次重跑非确定(dict/set 迭代序、`seq` 排序) | 直接决定 V5 | 确定性单测(同输入两次同输出);`clause_path_norm` 与 `seq` 排序显式定序,禁用无序结构参与 id 计算 |
| **R5** | docx **无原生页码**;SPEC 要求 `page` 必填(QC 指标4=页码锚点 100%、四级引用页码位) | 检查点 B 的 QC4 / 四级引用 | **规范渲染件 + 文本对齐**(见 SPEC《页码锚点机制》):`soffice` 渲染件=页码权威,结构仍从 docx XML 抽,`page_align` 单调两指针回填;失败优雅降级到 QC4 + 补录队列,不新增关卡。残留见 R5a/R5b |
| **R5a** | LibreOffice(`soffice`)是重量级系统依赖,信创内网可用性/合规待验证 | 生产渲染步骤可行性 | demo 本地装 LibreOffice 即可;**列为部署待验证项**(同 Temporal/DeepDoc 的 P0 性质),与张翼飞确认信创口径;渲染经接口封装,生产可换渲染后端 |
| **R5b** | docx 自动编号(列表/条款自动序号)序号不在 run 文本里 → 同时影响 clause_tree 解析与文本对齐 | 真实 docx 的页码命中率 + 条款树 | demo fixtures **条款号写字面文本**(不用 Word 自动编号)规避;真实件该问题使 `page=null` 率上升、被 QC4 显式拦截不静默;自动编号解析作为 W1 触发式建设 |
| **R6** | 版本原子切换事务一致性(PG 与 Milvus 跨库,无分布式事务) | V4 | 定序:先 PG 事务提交(status 互换),再 Milvus 标量批量改(幂等、可重放);切换前置校验新版已 `INDEXED`;失败留在中间态进对账(对账属 M2,M1 至少保证 PG 侧原子) |
| **R7** | orchestrator 人工等待态被误轮询造成忙循环 | 工程质量 | 轮询 SQL 显式排除 `QC_FAILED`/`META_REVIEW`/`QUARANTINED`;无可推进文档时 sleep |
| **R8** | fixtures 交付晚于代码,阻塞检查点 B | 进度 | fixtures 列为阶段 A 起步的并行独立流,先交付"最小可联调集"(正常×2 + 坏样例×2),其余补齐 |

## 5. 与 CC 任务拆分(V0.1 §14)映射

本计划 4 阶段对齐文档建议的两个 CC 任务,便于后续派活:

- **T-A 管线骨架** ≈ 阶段 A + B:S0–S2 + 状态机 + orchestrator + 统一队列 CLI + ObjectStore + Alembic 首批迁移。锁定:状态机枚举、manifest 契约、IR 契约、stage 纯函数签名、add-only。
- **T-B 切块索引与验证** ≈ 阶段 C + D:S3–S5 + EmbeddingClient(本地实现)+ Milvus schema + 版本链切换 + `verify idempotency` + 单测 + fixtures 构造脚本。锁定:`chunk_id` 公式、切块六规则、写入顺序、冷备列。

> 两个 CC 任务沿用强制澄清机制:关键歧义暂停并提 ≥3 问;schema/接口 add-only;禁绕开三接口直连实现。

## 6. 验收点 → 阶段映射矩阵

| 验收点 | 主要落在 | 联调验证检查点 |
|---|---|---|
| V1 端到端到终态 | C(主干)+ B(隔离/失败分支) | 检查点 C(INDEXED)+ D(全终态无悬挂) |
| V2 QC 关卡 + 补录闭环 | B(QC + queue) | 检查点 B(前半)+ D(degrade 路径) |
| V4 版本原子切换 | D | 检查点 D |
| V5 幂等重跑 | D(verify)+ C(`chunk_id` 确定性根基) | 检查点 D + R4 单测 |

---

## 评审说明(本计划的 gate)

请确认:**(a)** 四阶段切分与硬依赖是否认可;**(b)** R5(docx 页码用自造 fixtures 的显式分页符解决)这一工程取舍是否接受;**(c)** R2 中"hybrid 受阻可显式退化 dense-only"作为兜底是否可接受。

批准后我进 **Phase 3(Tasks)**:把每阶段拆成 ≤5 文件、带验收标准与验证命令的离散任务,写入 `TASKS.md`。
