# CLAUDE.md

文档处理管线(内规 / 外规 / 监管问答 / 案例 → IR → 质检 → 切块 → 嵌入 → Milvus 索引,PG 为权威)。
单包 demo 已原地升格为 **audit-ai monorepo**;契约现按生产设计 **v1.6 保真**(不再裁为 v1.5 子集)。
**生产保真指令:一律按 v1.6 生产设计评判,不以"这只是 demo / demo 消费者够用"为由放水**——red-line / 契约 /
富集(E1/E2/cases/四类语料)按生产标准实现与验证(QA/案例/E2 已在 PR #4 落地)。

> **本文件只放"始终要遵守的核心"——契约、架构、约定。** 各模块的**开发记忆 / 决策 / 踩坑**已拆到
> `docs/devlogs/*_devlog.md`(见底部「模块开发记忆索引」),**改某模块前按需读对应 devlog**(lazy,不全量进 context)。
> 时间轴阶段索引在 `docs/devlog.md`(已瘦身为索引,细节下沉模块 devlog)。改契约前先读 `docs/file-processing-workflow-docs/SPEC*.md`("裁机制不裁契约":cut mechanisms, never cut contracts)。
>
> **三层记忆分工**(写记录前先问"归哪层"):**git** = WHAT/WHEN/WHO + commit 粒度 why(机械完整,**能从 diff/log 看出来的只归这里**);**in-repo devlog**(`docs/devlog.md` 阶段索引 + `docs/devlogs/*` + `docs/query-agent-docs/query_devlog.md`)= **git 给不了的**——决策 + 为什么(尤其**否决方案**)、跨改动状态综合、非显然踩坑 / 环境怪癖 / 契约约束(随代码入库,给团队 + agent);**agent auto-memory**(`~/.claude/.../memory/`,私有)= 用户偏好、工作风格反馈、跨会话环境怪癖。**判据**:能从 diff/log 直接看出来 → 谁都别写(git 已有);会随代码演进、要给团队看 → devlog;只帮 agent 跨会话 → auto-memory。`/clear` 自动存档 hook 同此口径(空 commit 不写、只记 git 给不了的、宁缺勿凑)。

## 开发协作流程(分工 — 始终遵守)

本项目按"规划/实现 ↔ 审查"分离协作:

- **Claude Code(规划 + 实现)**:负责需求规划、计划分解、任务拆解与代码生成。流程依次用 skills:
  `spec-driven-development`(写规格)→ `planning-and-task-breakdown`(出计划/任务)→
  `incremental-implementation` + `test-driven-development`(逐任务 TDD 落地)。每阶段门控待人工批准再进。
- **Codex(代码审查)**:负责开发生命周期中的代码审查,用 skills `code-review-and-quality` + `security-and-hardening`。
- 故 **Claude Code 默认不自评 / 不代行审查**——交付后交 Codex 审;除非用户明确要求自查。
- **审查修复闭环**:Codex 审查 → 发现写 `.review/findings.json`(按 `.cursor/rules/review-output.mdc`)→
  **由 Claude Code(原作者)逐条修复,或带 `spec_ref` 理由反驳**(审查意见非总对)→ Codex **复审**,
  直至无 critical/warning。**修复归实现侧(Claude),审查者(Codex)不自改**——保审查独立性(改动也须被独立验证);
  纯机械项(格式 / lint)交 `ruff --fix` 等工具,不劳代理。
- **测试职责分工**(按能力分,**不全交审查方**):**Claude** 拥有 TDD(实现/修复先写失败测试)+
  **模型门控/集成测试**(本地真栈 + 真 BGE-M3,Codex/CI 跑不了,只有 Claude 能跑)+ **合并前全仓门跑一次**;
  **Codex/CI** 做独立单元/非栈校验(Codex 复审跑测试 = 对"测试已绿"的**独立核验**,非替代)。全交审查方会破
  TDD、交付未验证码、且集成/红线在修复阶段失验。
- **测试节流**:修复**迭代中只跑改动波及范围**(对应包单元 + 受影响集成);**全仓模型门控全量门留到交 PR /
  合并前跑一次**,避免每次修复都重复长跑。
- SDD 产物落 `docs/<模块>-docs/`(SPEC / PLAN / TASKS / devlog / GAP),如 `docs/query-agent-docs/`。

### 并行 worktree 协作(多开会话时 — 始终遵守)

多个 Claude Code 会话并行(如一侧补管线、另一侧做查询)时,**各用独立 git worktree**。worktree 是同一仓库的
**链接工作树**(非副本:共享 `.git`/分支/对象库,各 checkout 自己分支;主工作树 = `.git` 目录所在那个):
`git worktree add <path> -b <branch> origin/main`;commit 即入共享 repo,`git push` 从 worktree 正常推 → PR;
合并后 `git worktree remove <path>` 清理(分支/commit 留在 repo)。

- **隔离工作树**:绝不在他人正用的工作树里 checkout / 切分支(会回退对方未提交码 + 改其依赖的 schema 文件)。
- **栈是全局单例**:PG/Milvus 一个 compose 项目、所有 worktree 共用同一 DB/Milvus/collection。**模型门集成串行**——
  跑前确认对方空闲 + `demo down -v && demo up` 取干净栈(SHA 去重 + pymilvus 全局别名 teardown 互扰),绝不并发跑集成。
  DB 迁移也全局:并行分支可能把 schema 迁过自己 models 版本(add-only 保证兼容)→ **全仓门留合并时在对齐 code+schema 上跑**。
- **worktree 无 `.venv`**(在主仓根、gitignore):跑测试用 `PYTHONPATH=<worktree>/{libs/common,pipeline,eval,query}`
  复用主 `.venv`(editable 装在主 checkout,PYTHONPATH 让 import 解析到 worktree 码);或 worktree 内自建 venv。
- **审查闭环不变**:commit → push → PR → Codex 审 → 修复闭环(同上)。PR 前想本地让 Codex 审 worktree diff,须
  **先 commit**(未跟踪文件不进 `git diff`,否则 Codex 漏新码),Codex 以 cwd=worktree 审 `origin/main...HEAD`。

## 项目状态

M1–M3(V1–V8 全过)+ Web 工作台 + audit-ai 升格 Step 0–7,均完成。**阶段 V16(2026-06,PR #4)**:生产 v1.6
契约保真 + **四类语料(内规/外规/监管问答/案例)按 `corpus_type` profile 路由入库** + **E2 LLM 条款级打标** +
案例要素抽取(`cases` 表)。全量 **374 passed / 0 failed**(干净栈 + 本地 BGE-M3 真跑)。
详见 `docs/devlog.md` 阶段 V16 + `docs/migration_devlog.md` + `docs/CP-009-仓库与升格规范.md`。
**制度查询智能体(功能1)MVP** 已落地(`query/`:R1 依据查询 + 覆盖感知拒答 + 八路路由骨架,
spec-driven 产出;见 `docs/query-agent-docs/`),全仓 **440 passed / 0 failed**(真 BGE-M3)。

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
- **s3 按 `corpus_type` 路由切块**(`chunking/profile_router`):内规/外规→条款树;监管问答→问答对切分;案例→要素分段
  + `cases` 表(§9 L1 抽取)。富集层 E1(义务,零 LLM)/ E2(实体·部门·事项,LLM,默认关);QC 指标集按 profile 选。
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
- `INDEXED` 后 `finalize`:带 `supersedes` 把旧版置 `superseded`(废止件 `abolished`;PG 原子事务 + Milvus 从冷备改标量不删)
  + 跑 T2/T4 留痕。`version_status` **四态** effective/superseded/abolished/**upcoming**(生效日在未来;`demo activate` 手动上线、延后 supersede)。
- `reprocess <dvid>` 替代生产 REPARSE:全重跑 + 按 dvid 清孤儿(确定性 chunk_id 使重跑覆盖安全)。
- `DEGRADED_INDEXED`(`chunks.degraded=true`):仅全文检索、不参与条款级引用、T4 豁免。

## 硬契约 — 不可改(byte-identical to 生产设计,demo 演进为生产)

- **`chunk_id` 公式**(`libs/common/common/chunk_id.py`):`sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]`。
  幂等之根,一字不改(pin: `libs/common/tests/test_chunk_id.py`)。
- **manifest 契约**(`libs/common/common/manifest.py`):**11 必填列**(V1.6 增 `sub_type` / `effective_date`),导入校验,不匹配整批拒收。
- **PG 字段名/类型/枚举**(`libs/common/common/pg_models.py`,生产 §10):**add-only**(Alembic 强制,绝不改名/删)。
- **Milvus `audit_corpus` schema**(`libs/common/common/milvus_schema.py`,生产 §8.2,V1.6 已补齐全字段):`perm_tag`/
  `biz_domain` **ARRAY** · `issuer_level` **INT8** · `doc_id`/`sub_type`/`effective_date`/`chunk_type`/`text`/`entity_type`
  + partition key(`corpus_type`)。`perm_tag` 写入但**过滤逻辑有意不实现**;`entity_type` 由 E2 富集(默认关时为空)。
- **IR schema**(`libs/common/common/ir.py`,生产 §4.2):blocks/tables/bbox/page 全保真,是解析器与下游的稳定边界。
- **写序与一致性**:PG 先 → Milvus upsert → flush → 置 `INDEXED`。INDEXED 前 chunk `status=staging` 检索不可见。
- **切块六规则 + 条款树正则**(§6.1–6.2)+ 小数编号 / 目录剥离 / 跨法引用过滤:细节见 `docs/devlogs/structuring_devlog.md`。
- **V1.6 新列/表**(add-only,迁移 0005–0007):chunks +`chunk_type`/`parent_chunk_id`/`internal_refs`/`embed_status`/
  `entity_type`;clause_tags +类型列(`deontic_type`/`norm_duration_days`/`entity_type`…);`cases`(案例要素,§9)、
  `dict_entity_types`/`dict_departments`(E2 约束字典)。

## 配置(所有 ⚠ 可调值集中于此,绝不硬编码)

- `config/settings.toml`(连接串、嵌入模式、`[toggles]` L2/E1/**E2** 开关、`[llm] model`、`auto_confirm_meta_no_conflict`)·
  `config/qc_thresholds.yaml`(7 指标 + 边带 ε + 问答对完整率)· `config/profiles.yaml`(P-INT/P-EXT/**P-QA/P-CASE**)·
  `config/obligation.yaml`(E1 词表)· `seeds/dict_entity_types.csv`/`dict_departments.csv`(E2 约束字典,v0-draft 待评审)。
- **LLM 默认全关**(默认路径零 LLM);L2 元数据 / **E2 条款级打标**是开关,开时用 LLM client(OpenAI 兼容 `gpt-5.4-nano`,
  key 走 env `OPENAI_API_KEY` **绝不入库**)、prompt 在根 `PROMPTS.md`。

## CLI(`demo` / `demo-web`)

```
demo up | down                      # 起停 pg+milvus(compose),up 含 alembic upgrade + seed
demo ingest <dir> --manifest <xlsx> # S0 入口,驱动管线
demo status [batch] | report <batch>
demo queue list|show|fix|degrade|reject|release <id>   # 统一人工队列(qc_fix/quarantine/meta_confirm 三类)
demo meta list | confirm <id|--batch>                  # META_REVIEW 人工闸
demo search "<q>" [--include-superseded][--corpus internal|external][--topk N]
demo verify smoke|replay|reconcile|idempotency · demo rebuild · demo reprocess <dvid> · demo activate <dvid>  # upcoming→effective
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

- `.venv/bin/python -m pytest -q`(testpaths = `pipeline/tests`/`libs/common/tests`/`eval/tests`/`query/tests`,共享 fixtures 在 repo 根 `conftest.py`)。
  **测试文件基名须全仓唯一**(pytest prepend 模式 + tests 无 `__init__.py`,撞名致收集报错)。
- `.venv/bin/ruff check .`(E/F/I/UP/B,行宽 100,`known-first-party=[common,pipeline,eval,query]`;CJK 注释易超行→独立行/缩短)。
- 集成测连真栈、栈未起则 skip;各自按 batch_id 反 FK 序清理。迁移 add-only:autogenerate → upgrade → `alembic check` 无漂移;
  `alembic/versions` 纳入 lint(autogenerate 后 `ruff check --fix alembic/versions && ruff format alembic/versions`)。
- **mini golden set**(`pipeline/tests/golden/`):条款树 F1=1.0(demo 集必须完美解析,parser-swap 准入门);E1 义务 golden P=1.0/R=1.0。

## 模块开发记忆索引(lazy:改该模块前读对应 devlog)

| 模块 | 代码位置 | 开发记忆(决策/踩坑) |
|---|---|---|
| 契约 | `libs/common/common/` | `docs/devlogs/contracts_devlog.md` |
| S1 解析 / 页码锚点 | `pipeline/pipeline/parsing/` | `docs/devlogs/parsing_devlog.md` |
| S2 质检 | `pipeline/pipeline/qc/` | `docs/devlogs/qc_devlog.md` |
| S3 结构化(条款树/切块/profile 路由·问答·案例) | `pipeline/pipeline/chunking/` | `docs/devlogs/structuring_devlog.md` |
| S4 元数据 / 版本链 | `pipeline/pipeline/meta/` | `docs/devlogs/metadata_devlog.md` |
| S5 嵌入 / 索引 / 冷备 | `pipeline/pipeline/index/` | `docs/devlogs/index_devlog.md` |
| 编排 / 状态机 / 队列 | `pipeline/pipeline/`(orchestrator/states/queue) | `docs/devlogs/orchestration_devlog.md` |
| E1/E2 富集(+ LLM client) | `pipeline/pipeline/enrich/` · `pipeline/pipeline/llm_client.py` | `docs/devlogs/enrich_devlog.md` |
| 验证套件 | `eval/eval/` | `docs/devlogs/eval_devlog.md` |
| Web 工作台 | `pipeline/pipeline/web/` | `docs/devlogs/web_devlog.md` |
| 制度查询智能体(功能1,MVP) | `query/query/` | `docs/query-agent-docs/query_devlog.md`(+ SPEC/PLAN/TASKS/GAP/RTM) |
| audit-ai 升格 | (全仓) | `docs/migration_devlog.md` + `docs/CP-009-仓库与升格规范.md` |

> 时间轴全叙事(按阶段 A/B/C/D/M2/M3/W/升格):`docs/devlog.md`。规格:`docs/file-processing-workflow-docs/SPEC*.md` / `docs/file-processing-workflow-docs/PLAN*.md` / `docs/file-processing-workflow-docs/TASKS*.md`;
> 上游生产设计:`docs/文档处理与语料库构建_技术框架设计_v1.6.md`、`docs/制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`。
