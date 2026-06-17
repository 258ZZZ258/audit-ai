# CLAUDE.md

文档处理管线(内规 docx / 外规 pdf → IR → 质检 → 切块 → 嵌入 → Milvus 索引,PG 为权威)。
本仓正从单包 demo 原地升格为 **audit-ai monorepo**(分支 `migrate/audit-ai-skeleton`)。

> **本文件只放"始终要遵守的核心"——契约、架构、约定。** 各模块的**开发记忆 / 决策 / 踩坑**已拆到
> 各包内 `*_devlog.md`(见底部「模块开发记忆索引」),**改某模块前按需读对应 devlog**(lazy,不全量进 context)。
> 时间轴全叙事在 `docs/devlog.md`。改契约前先读 `SPEC*.md`("裁机制不裁契约":cut mechanisms, never cut contracts)。

## 项目状态

M1(检查点 D,V1/V2/V4/V5)+ M2 验证套件(检查点 M2,V3/V6/V7)+ M3 E1 义务打标 + report(检查点 M3,V1–V8 全过)
+ Web 工作台,均完成。**audit-ai 升格 Step 0–7 完成**(全量 **282 passed / 0 failed**,本地 BGE-M3 真跑;
契约 byte 守恒、接缝就位、依赖无环):见 `docs/migration_devlog.md` + `docs/CP-009-仓库与升格规范.md`(草稿)。

## 架构(audit-ai monorepo)

```
libs/common  (audit-common)  契约承重层,不依赖任何上层
   ▲
pipeline     (audit-pipeline) S0–S5/finalize · 机制 · 编排/解析接缝 · web    → common
   ▲
eval         (audit-eval)     验证组件(T2/T4/reconcile/rebuild/idempotency/report) → pipeline → common
```

- **import 名**:`common` / `pipeline`(不变)/ `eval`;各成员 `pipeline/pipeline/`、`libs/common/common/`、`eval/eval/`。
- **依赖 DAG 无环**:`pipeline` **不得在 import 期依赖 `eval`**——cli/web/finalize 调 eval 一律**函数级懒导入**。
- **PG 权威 / Milvus 投影 / 单进程轮询 worker**:Orchestrator 轮询可推进态 → 调 stage 纯函数 `(ctx, dvid)->StageResult`
  → 条件迁移 + 写 `pipeline_events`。人工等待态(QC_FAILED/META_REVIEW/QUARANTINED)不轮询,等 CLI 命令推进。
- **stage 是纯函数,只经 PG 状态 + ObjectStore 通信,互不 import**(生产迁 Temporal activity 的前提)。
- **两个可替换接缝**(Protocol/ABC + demo 默认 + 读配置 factory + 生产 stub):编排 `WorkflowEngine`(demo=Orchestrator;
  生产=Temporal stub,`PIPELINE_WORKFLOW_BACKEND`)、解析 `ParserAdapter`(demo=light;生产=DeepDoc/MinerU/PaddleOCR stub,
  `PIPELINE_PARSER_BACKEND`)。Checkpointer/GraphStore **未建**(本仓无 demo 代码,仅 CP-009 约定)。
- 配置/数据/运维**置 repo 根**:`config/`、`seeds/`、`alembic/`、`compose.yaml`(config 不能进 pipeline——
  flat 布局下 `pipeline/config` 会命名空间遮蔽 `pipeline.config` 模块;见 `docs/migration_devlog.md`)。

## 状态机(demo 子集)

```
REGISTERED → PARSING → QC_PENDING → STRUCTURING → META_REVIEW → EMBEDDING → INDEXING → INDEXED
              ↓            ↓(fail)                 (CLI confirm 闸)
         PARSE_FAILED   QC_FAILED ─(queue fix)→ QC_PENDING / ─(degrade)→ DEGRADED_INDEXED / ─(reject)→ REJECTED
QUARANTINED(hash 疑重 / 缺密级 / 白名单外格式 / 扫描件)
```

- 每次迁移写 `pipeline_events`(时间/actor[system 或 CLI 用户]/前后态/错误码 E1xx–E8xx,demo 专属带 `-DEMO`)。
- `INDEXED` 后 `finalize`:带 `supersedes` 自动把旧版置 `superseded`(PG 原子事务 + Milvus 从冷备改标量不删)+ 跑 T2/T4 留痕。
- `reprocess <dvid>` 替代生产 REPARSE:全重跑 + 按 dvid 清孤儿(确定性 chunk_id 使重跑覆盖安全)。
- `DEGRADED_INDEXED`(`chunks.degraded=true`):仅全文检索、不参与条款级引用、T4 豁免。

## 硬契约 — 不可改(byte-identical to 生产设计,demo 演进为生产)

- **`chunk_id` 公式**(`libs/common/common/chunk_id.py`):`sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]`。
  幂等之根,一字不改(pin: `libs/common/tests/test_chunk_id.py`)。
- **manifest 契约**(`libs/common/common/manifest.py`):9 必填列,导入校验,不匹配整批拒收。
- **PG 字段名/类型/枚举**(`libs/common/common/pg_models.py`,生产 §10):**add-only**(Alembic 强制,绝不改名/删)。
- **Milvus `audit_corpus` schema**(`libs/common/common/milvus_schema.py`,生产 §4.1/§8.2):全字段含 `perm_tag`/`biz_domain`/
  `issuer_level` + partition key。`perm_tag` 全链写入但**过滤逻辑有意不实现**(字段预留)。
- **IR schema**(`libs/common/common/ir.py`,生产 §4.2):blocks/tables/bbox/page 全保真,是解析器与下游的稳定边界。
- **写序与一致性**:PG 先 → Milvus upsert → flush → 置 `INDEXED`。INDEXED 前 chunk `status=staging` 检索不可见。
- **切块六规则 + 条款树正则**(§6.1–6.2)+ 小数编号 / 目录剥离 / 跨法引用过滤:细节见 `structuring_devlog.md`。

## 配置(所有 ⚠ 可调值集中于此,绝不硬编码)

- `config/settings.toml`(连接串、嵌入模式、L2/E1 开关、`auto_confirm_meta_no_conflict`)· `config/qc_thresholds.yaml`(7 指标 + 边带 ε)
  · `config/profiles.yaml`(P-INT/P-EXT)· `config/obligation.yaml`(E1 词表)。
- **LLM 默认全关**(默认路径零 LLM 调用);L2 元数据辅助是开关,开时用 LLM 工厂、prompt 在根 `PROMPTS.md`。

## CLI(`demo` / `demo-web`)

```
demo up | down                      # 起停 pg+milvus(compose),up 含 alembic upgrade + seed
demo ingest <dir> --manifest <xlsx> # S0 入口,驱动管线
demo status [batch] | report <batch>
demo queue list|show|fix|degrade|reject|release <id>   # 统一人工队列(qc_fix/quarantine/meta_confirm 三类)
demo meta list | confirm <id|--batch>                  # META_REVIEW 人工闸
demo search "<q>" [--include-superseded][--corpus internal|external][--topk N]
demo verify smoke|replay|reconcile|idempotency · demo rebuild · demo reprocess <dvid>
demo-web --host 127.0.0.1 --port 8765   # Web 工作台(thin shell over 域函数)
```

- **CLI 推进可靠性契约**:`meta confirm`/`reprocess`/`queue *` 推进中途 stage 异常**不静默 exit 0**——`_advance_one` 回带
  error、未达终态即非零退出。

## 验证组件(demo 差异化卖点,`eval/`)

T2 冒烟(V7)· T4 锚点回放(V3)· reconcile(PG↔Milvus 对账)· rebuild(V6,冷备零编码回灌)· idempotency(V5)· report。
**对终态无阻断权**(只写报告);finalize 在 INDEXED 跑 T2/T4 留痕,report 只聚合读取(不加载模型)。细节见 `eval_devlog.md`。

## 环境(非显然,易再踩)

- **Python 3.11 only**(机器默认 3.14 无 grpcio/torch wheel);`.venv` 由 brew `python@3.11` 建。**`setuptools<81`** 已钉
  (pymilvus 2.4 需 `pkg_resources`)。开发安装:`pip install -e libs/common && -e pipeline && -e eval && -e ".[dev]"`。
- **LibreOffice `soffice`** 供 docx→PDF 渲染(页码锚点);env `PIPELINE_SOFFICE` > PATH > mac .app。`[embed]` extra(torch)非默认装。
- **真模型/向量化**:BGE-M3 经 modelscope 拉到本地(hf-mirror 在该网络 308 跳回 HF、直连慢),设
  `PIPELINE_EMBEDDING_MODEL=<本地目录>` + `HF_HUB_OFFLINE=1`;未设时 embed/s5 集成测试自动 skip(绝不联网下载)。
- **模型门控套件假定干净栈**(SHA 去重):跑前 `demo down -v && demo up` 或清库,否则手动走查残留致去重撞车。
  **提交前必跑模型门控全量**(无模型时它们 skip,漏回归)。Milvus standalone 偶发中途卡死:`ps -o etime,cputime` CPU≪墙钟即卡,
  `demo down -v && demo up`。

## 测试约定

- `.venv/bin/python -m pytest -q`(testpaths = `pipeline/tests`/`libs/common/tests`/`eval/tests`,共享 fixtures 在 repo 根 `conftest.py`)。
- `.venv/bin/ruff check .`(E/F/I/UP/B,行宽 100,`known-first-party=[common,pipeline,eval]`;CJK 注释易超行→独立行/缩短)。
- 集成测连真栈、栈未起则 skip;各自按 batch_id 反 FK 序清理。迁移 add-only:autogenerate → upgrade → `alembic check` 无漂移;
  `alembic/versions` 纳入 lint(autogenerate 后 `ruff check --fix alembic/versions && ruff format alembic/versions`)。
- **mini golden set**(`pipeline/tests/golden/`):条款树 F1=1.0(demo 集必须完美解析,parser-swap 准入门);E1 义务 golden P=1.0/R=1.0。

## 模块开发记忆索引(lazy:改该模块前读对应 devlog)

| 模块 | 代码位置 | 开发记忆(决策/踩坑) |
|---|---|---|
| 契约 | `libs/common/common/` | `libs/common/contracts_devlog.md` |
| S1 解析 / 页码锚点 | `pipeline/pipeline/parsing/` | `pipeline/pipeline/parsing/parsing_devlog.md` |
| S2 质检 | `pipeline/pipeline/qc/` | `pipeline/pipeline/qc/qc_devlog.md` |
| S3 结构化(条款树/切块) | `pipeline/pipeline/chunking/` | `pipeline/pipeline/chunking/structuring_devlog.md` |
| S4 元数据 / 版本链 | `pipeline/pipeline/meta/` | `pipeline/pipeline/meta/metadata_devlog.md` |
| S5 嵌入 / 索引 / 冷备 | `pipeline/pipeline/index/` | `pipeline/pipeline/index/index_devlog.md` |
| 编排 / 状态机 / 队列 | `pipeline/pipeline/`(orchestrator/states/queue) | `pipeline/pipeline/orchestration_devlog.md` |
| E1 富集 | `pipeline/pipeline/enrich/` | `pipeline/pipeline/enrich/enrich_devlog.md` |
| 验证套件 | `eval/eval/` | `eval/eval_devlog.md` |
| Web 工作台 | `pipeline/pipeline/web/` | `pipeline/pipeline/web/web_devlog.md` |
| audit-ai 升格 | (全仓) | `docs/migration_devlog.md` + `docs/CP-009-仓库与升格规范.md` |

> 时间轴全叙事(按阶段 A/B/C/D/M2/M3/W/升格):`docs/devlog.md`。规格:`SPEC*.md` / `PLAN*.md` / `TASKS*.md`;
> 上游生产设计:`docs/文档处理与语料库构建_技术框架设计_v1.6.md`、`docs/制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`。
