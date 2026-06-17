# 迁移清单 — 文档处理管线 demo → audit-ai 生产骨架（Step 0）

> 分支 `migrate/audit-ai-skeleton`（基于 `main`=`3889508`,**不含**未合并的 PR #1 web 改动)。
> 本文件是 **Step 0 盘点产物**,仅盘点未动任何源文件。**待 zy 复核确认后才进 Step 1。**
> 设计依据:`文档处理与语料库构建_技术框架设计_v1.6.md`(§4.1/4.2/6.5/8.2/10/11/19/21)、
> `制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`、`PROMPTS.md`。

---

## A. 仓库现实 vs 任务假设(开工前必读的三处关键错配)

任务的接缝表/阶段表是按 **audit-ai 全系统**(含 RAG 查询/比对智能体)写的,但**本仓只是文档处理管线**。盘点(`grep` 全仓 `src/`+`tests/`)证实:

| 任务假设 | 本仓现实(实测) | 影响 |
|---|---|---|
| 4 个接缝都有 demo 实现 | **只有 2 个**:编排(`orchestrator.py`)、解析(`parsing/adapter.py`+`light_parser.py`)。`MemorySaver`/`Checkpointer`/`NetworkX`/`GraphStore`/`temporal`/`langgraph`/`Nebula`/`PostgresSaver` **全仓零命中** | Checkpointer、GraphStore 两个接缝**没有可搬迁的 demo 代码**→ 见决策 ① |
| 评测组件 T1–T6 | **只实现了 T2**(`verify/smoke.py`)+ **T4**(`verify/anchor_replay.py`)。T1/T3/T5/T6 不存在 | eval 只搬 T2/T4 + 另 4 个非 T 编号组件→ 见决策 ③ |
| 管线阶段 S0–S5、**S0.5**,富集 **E1–E4** | S0–S5 + finalize 齐全;**无 S0.5、无 S6**;富集**只有 E1**(`enrich/e1_obligation.py`),E2/E3/E4 不存在 | 不缺的搬,缺的是约定(CP-009),**不scaffold** |

> 结论:严格遵守硬约束 #4「不铺空包」——对**不存在 demo 代码**的接缝/阶段/组件,本次**不创建**任何包或 stub 文件,只在 CP-009 冻结为约定 + 再集成触发条件。这与任务 Step 3 表里列出的 Checkpointer/GraphStore 接缝直接冲突 → 决策 ①**已定:不创建**。

---

## B. 契约盘点(硬约束 #1:只搬位置,绝不改值)

5 项契约。**2 项是纯契约文件**(可整体 `git mv`),**3 项嵌在机制文件里**(需 surgical 抽取:把符号搬到 `libs/common`,值逐字不变,改 import;不能整文件 mv 否则把机制拖进契约层)。

| 契约 | 设计依据 | 现位置 | 形态 | 搬法 |
|---|---|---|---|---|
| IR schema | §4.2 | `src/pipeline/ir.py`(整文件:`SourceFormat`/`BlockType`/`BBox`/`TableCell`/`Table`/`Block`/`IRDocument`) | **纯契约** | 整体 `git mv` → `libs/common` |
| PG 表模型/字段 | §10 | `src/pipeline/index/pg_models.py`(整文件:13 个 ORM 类 + `AuditMixin`) | **纯契约** | 整体 `git mv` → `libs/common` |
| chunk_id 公式 | §6.5 | `src/pipeline/chunking/chunker.py:46` `compute_chunk_id()` | **嵌入**(chunker 余下是切块机制) | 抽 `compute_chunk_id` → `libs/common`,chunker 改 import |
| Milvus collection schema + 标量字段 | §8.2 | `src/pipeline/index/milvus_io.py:126` `MilvusIO.schema()` + 字段列表 + `DENSE_DIM` | **嵌入**(milvus_io 余下是 upsert/查/冷备 I/O 机制) | 抽 schema 字段定义 → `libs/common`,`MilvusIO.schema()` 引用之 |
| manifest 列契约 | §3.1 | `src/pipeline/stages/s0_register.py:36` `REQUIRED_COLUMNS` | **嵌入**(s0 余下是登记机制) | 抽 `REQUIRED_COLUMNS` → `libs/common`,s0 + web 改 import |

**pin 测试**:`tests/test_chunk_id.py` 已存在 → 随 `compute_chunk_id` 移到 `libs/common/tests`,Step 2 后断言对固定输入产出与迁移前**逐字节相同**。

> 准-契约的灰区(**列出待裁,见决策 ④**):`states.py` 的状态枚举值(REGISTERED…)+ 错误码(E1xx,§11.2)是跨系统持久化字符串,带契约性,但**不在**任务硬约束 #1 列举的 5 项内。我**暂按机制**(随状态机进 `pipeline`)分类,请确认是否同意。

---

## C. 全文件 → 目标位置映射

### C1 → `libs/common`(承重契约层,不依赖任何上层)

| 现文件 | 目标 | 分类 | 备注 |
|---|---|---|---|
| `src/pipeline/ir.py` | `libs/common/ir.py` | 契约 | 整体 mv |
| `src/pipeline/index/pg_models.py` | `libs/common/pg_models.py` | 契约 | 整体 mv;全仓 import 改向 |
| `compute_chunk_id`@`chunking/chunker.py` | `libs/common/chunk_id.py`(新) | 契约 | 符号抽取 |
| Milvus schema@`index/milvus_io.py` | `libs/common/milvus_schema.py`(新) | 契约 | 符号抽取(仅 schema/字段/DENSE_DIM) |
| `REQUIRED_COLUMNS`@`stages/s0_register.py` | `libs/common/manifest.py`(新) | 契约 | 符号抽取 |
| `tests/test_ir.py` | `libs/common/tests/` | 契约测试 | |
| `tests/test_chunk_id.py` | `libs/common/tests/` | 契约 pin | Step 2 验逐字节不变 |

### C2 → `pipeline`(阶段 + 机制 + 支撑;含两个接缝)

| 现文件/目录 | 目标 | 分类 |
|---|---|---|
| `stages/s0_register.py`(去 REQUIRED_COLUMNS)、`s1_parse`、`s2_qc`、`s3_structure`、`s4_meta`、`s5_embed_index`、`finalize` | `pipeline/stages/` | 管线 S0–S5+finalize |
| `chunking/chunker.py`(去 compute_chunk_id)、`clause_tree.py`、`normalize.py` | `pipeline/chunking/` | 管线(切块/条款树) |
| `qc/gate.py`、`qc/indicators.py` | `pipeline/qc/` | 管线(质检 7 指标) |
| `meta/l1_rules.py`、`meta/version_chain.py` | `pipeline/meta/` | 管线(L1 元数据/版本链) |
| `enrich/e1_obligation.py` | `pipeline/enrich/` | 富集 E1(零 LLM) |
| `index/pg_io.py`、`milvus_io.py`(去 schema)、`object_store.py`、`corpus_rows.py`、`embedding_client.py` | `pipeline/index/` | 机制(PG/Milvus I/O、冷备、嵌入) |
| `parsing/adapter.py` | `pipeline/parsing/` | **接缝④已存在**(ParserAdapter ABC) |
| `parsing/light_parser.py` | `pipeline/parsing/` | **接缝④默认实现**(light;生产=DeepDoc) |
| `parsing/rendition.py`、`page_align.py` | `pipeline/parsing/` | 机制(页码锚点:soffice 渲染+双指针对齐) |
| `orchestrator.py` | `pipeline/` | **接缝①默认实现**(单进程 PG 轮询 = StateMachineWorkflow;生产=Temporal) |
| `states.py` | `pipeline/` | 状态机(枚举值见决策 ④) |
| `stage_base.py`、`queue.py`、`cli.py`、`config.py` | `pipeline/` | 支撑(StageContext/统一队列/CLI/配置;config 见决策 ⑤) |
| `web/`(app.py、service.py、static/) | `pipeline/web/` | service/UI 薄壳(不建 services/*,暂留 pipeline,见决策 ⑥) |
| 各 `__init__.py` | 对应包 | — |
| pipeline 单测:`test_chunker`、`test_clause_tree`、`test_normalize`、`test_qc`、`test_s0_register`、`test_s1_parse`、`test_s3_structure`、`test_s4_meta`、`test_s5`、`test_l1`、`test_version_chain`、`test_version_demo`、`test_light_parser`、`test_page_align`、`test_orchestrator`、`test_states`、`test_queue`、`test_pg_io`、`test_object_store`、`test_milvus_io`、`test_config`、`test_cli`、`test_search_meta`、`test_e1_obligation`、`test_golden_set`、`test_obligation_golden`、`test_atomic_switch`、`test_b_mode_ingest`、`test_web_service`、`conftest.py`、`golden/` | `pipeline/tests/` | 见决策 ⑦(测试布局) |

### C3 → `eval`(验证组件:T2/T4 + 4 个非 T 编号组件)

| 现文件 | 目标 | 分类 | 设计依据 |
|---|---|---|---|
| `verify/smoke.py` | `eval/` | **T2** 批次冒烟 | §21.2 |
| `verify/anchor_replay.py` | `eval/` | **T4** 锚点回放 | §21.4 |
| `verify/reconcile.py` | `eval/` | 对账 | §12.2(非 T1–T6) |
| `verify/rebuild.py` | `eval/` | 全量重建 | §12.3(非 T1–T6) |
| `verify/idempotency.py` | `eval/` | 幂等(V5) | 非 T1–T6 |
| `verify/report.py` | `eval/` | 批次质量报告 | §15 看板 |
| eval 测试:`test_smoke`、`test_anchor_replay`、`test_reconcile`、`test_rebuild`、`test_idempotency`、`test_report`、`test_finalize_verify` | `eval/tests/` | | |

> **依赖告警(决策 ②)**:`verify/*` import 了 `pipeline` 内部(`StageContext`、`MilvusIO`、`corpus_rows`、`embedding`)。故 `eval` 必须依赖 `pipeline`(eval→pipeline→common),而非只依赖 `libs/common`。任务依赖声明只说了"两者依赖 common",未禁 eval→pipeline,需你确认这条 DAG。

### C4 → 仓库级杂项(root / 各自归属待定)

| 现文件/目录 | 倾向目标 | 分类 | 决策 |
|---|---|---|---|
| `alembic/`、`alembic.ini` | repo 根(运维工具,import 改向 libs/common 模型) | 杂项 | 决策 ⑧ |
| `compose.yaml` | repo 根 | 杂项(基础设施) | |
| `config/*.toml,*.yaml` | `pipeline/`(值属管线域) | 杂项 | 决策 ⑤ |
| `seeds/*.csv` | 随 config | 杂项(字典种子) | 决策 ⑤ |
| `tools/build_fixtures.py`+csv | repo 根 `tools/` | 杂项(夹具构建) | |
| `pyproject.toml` | 拆为 workspace 根 + 各包 | 杂项 | Step 1 |
| `.gitignore` | repo 根(补 `.codegraph/` 等) | 杂项 | Step 1 |
| `.cursor/rules/doc-pipeline-code-review.mdc` | repo 根保留 | 杂项 | |
| `docs/devlog.md` | `docs/` | 文档 | |
| `README.md`、`CLAUDE.md`、`PROMPTS.md` | repo 根 | 文档 | |
| `SPEC*.md`、`PLAN*.md`、`TASKS*.md` | `docs/` | 文档 | 决策 ⑨(已定:收进 docs/) |
| `文档处理管线_本地Demo_开发文档_v0.1.md`(tracked) | `docs/` | 文档 | 决策 ⑨ |
| `文档处理与语料库构建_技术框架设计_v1.6.md`、`制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`(**均 untracked**) | `docs/`?并入库? | 文档 | 决策 ⑨(是否纳入版本控制) |

### C5 不在版本控制、本次不动(工作树杂物)

`rendered_fusion*/`、`lo_resave/`、`.understand-anything/`、`~$…docx` 临时文件、`.cursor/settings.json`、`AGENTS.md`、`fixtures/`(git-ignored,`tools/build_fixtures.py --all` 重建)、`tests/golden/`(随 pipeline 测)。这些不进迁移。

---

## D. 决策(zy 于 2026-06-17 确认 —— 9 项全部采纳推荐项)

> 下列每项的**加粗建议即最终裁决**。Step 1 起按此执行。①③④ 系对"任务表按全系统写、本仓仅管线"这一错配的归正。

1. **【最关键】无 demo 代码的两个接缝(Checkpointer/MemorySaver、GraphStore/NetworkX)怎么办?**
   本仓零相关代码。按硬约束 #4「不铺空包」,我**建议本次不创建**这两个接缝的任何 Protocol/包/stub,只在 CP-009 冻结为约定 + 再集成触发条件。**或** 你要求即便无实现也先放 Protocol 声明?(我倾向前者——后者就是铺空包)。

2. **eval 依赖 pipeline 是否允许?** verify/* 实import pipeline 内部。建议 DAG = `eval → pipeline → common`。否则要把 `StageContext`/`MilvusIO` 等机制下沉 common(会污染契约层,不建议)。

3. **eval 的搬迁范围?** 只搬 T2(smoke)+T4(anchor_replay),还是把整个 `verify/`(含 reconcile/rebuild/idempotency/report = §12/§15,非 T1–T6)一并搬进 `eval/`?建议**整包搬**(它们是 demo 差异化的"验证组件"一族,内聚)。

4. **`states.py` 状态枚举值 + 错误码算契约吗?** 它们跨系统持久化,带契约性,但不在硬约束 #1 的 5 项内。建议**暂按机制**进 pipeline;若你视其为契约,则枚举/错误码也抽 libs/common。

5. **`config.py` + `config/*` + `seeds/*` 去哪?** 建议进 `pipeline`(值属管线域:QC 阈值/切块参数/profiles)。备选 libs/common(共享无上行依赖)——但会把管线域值塞进契约层,不建议。

6. **`web/` 工作台去哪?** 硬约束禁建 `services/*`,故建议**暂留 `pipeline/web/`**(它是 pipeline 的消费方),待 services/ 实体化时再抽(CP-009 约定)。确认?

7. **测试布局:** 按包共置(`libs/common/tests`、`pipeline/tests`、`eval/tests`)还是保留顶层 `tests/`?建议**共置**(让依赖边界诚实、可被 CI 分别跑)。这是本次工作量较大的一块机械拆分。

8. **`alembic/` 去哪?** 迁移脚本 import pg_models(将入 libs/common)。建议 alembic **留 repo 根**(部署/运维工具),其 import 改向 libs/common。备选随模型进 libs/common。

9. **文档(SPEC/PLAN/TASKS/设计文档)整理:** 是否把散在根的 `SPEC*/PLAN*/TASKS*` 和 v0.1 收进 `docs/`?另:**v1.6/v1.5 两份核心设计文档当前 untracked**,是否本次一并纳入版本控制(`git add`)?

---

## E. 一句话总结(供决策)

本仓是 audit-ai 的**文档处理管线那一块**,不是全系统。**最小脊柱 = `libs/common`(5 项契约,2 纯文件 mv + 3 符号抽取)+ `pipeline`(S0–S5/finalize、富集 E1、机制、2 个真实接缝[编排/解析]、web)+ `eval`(T2/T4 + reconcile/rebuild/idempotency/report)**。任务接缝表里的 Checkpointer/GraphStore、阶段表里的 S0.5/S6、富集 E2–E4、评测 T1/T3/T5/T6 **在本仓均无代码**,按「不铺空包」一律不创建,仅 CP-009 冻结为约定。9 项待裁见 §D。
