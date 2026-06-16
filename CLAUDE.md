# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**M1 完成(检查点 D,V1/V2/V4/V5)+ M2 验证套件完成(检查点 M2,V3/V6/V7)+ M3 E1 义务打标/report 打磨完成(检查点 M3,**V1–V8 全过**;全套 263 passed 含 model-gated,本地 BGE-M3 真跑)。** Specs: `SPEC.md`(M1)/ `SPEC_M2.md`(M2,验证套件主体、DeepDoc 降可选)/ `SPEC_M3.md`(M3,E1+report)、`PLAN*.md`、`TASKS*.md`(per-task 验收),upstream `文档处理管线_本地Demo_开发文档_v0.1.md` (V0.1)。**The full build narrative — every module, decision, and pitfall — is in `docs/devlog.md`; read it to understand why things are the way they are.** Read the spec before changing contracts — it encodes deliberate cut decisions ("裁机制不裁契约": cut mechanisms, never cut contracts). DeepDoc(M2 可选)留独立轮:走查证明真实 PDF 解析痛点在 `clause_tree`(IR 边界下游),与换不换解析器无关。

### 开发进展 (structured per-phase summary; 细节见 `docs/devlog.md`)

| 阶段 | 状态 | 内容 |
|---|---|---|
| **A 底座** | ✅ 检查点 A | config(⚠ 收口)/ ir(契约)/ states(状态机+迁移表)/ pg_models+alembic(add-only)/ compose+`demo up` / ObjectStore / pg_io / milvus_io(audit_corpus schema) |
| **L/P/SP 并行流** | ✅ | L: normalize·clause_tree·chunker(确定性 chunk_id)·page_align;P: fixtures(`build_fixtures.py`);SP1: rendition(soffice→pdf 对齐) |
| **B 接入→质检** | ✅ 检查点 B | s0 登记(manifest 校验/SHA 去重/版本关系)· s1 解析+渲染+页码对齐 · s2 七指标质检 · orchestrator(stage 注入轮询)· review_queue 处置流(dispose)· CLI `ingest`/`status`/`queue` |
| **C 结构化→向量化** | ✅ 检查点 C | s3 切块装配 · s4 元数据 L1+交叉校验 · version_chain · EmbeddingClient(本地 BGEM3)· milvus_io 混合查+冷备 · s5 嵌入索引(staging→effective)· C7 `search` 四级引用 + `meta list/confirm` 放行人工闸(覆盖 V1 主干) |
| **D 切换/幂等/报告** | ✅ 检查点 D(V1/V2/V4/V5) | **D1**: finalize 版本原子切换(自动触发)· corpus_rows 共享层。**D2**: batch02 真实修订对 182→226(**V4**)。**D3**: `verify idempotency`(**V5**)+ `reprocess`。**D4**: `report <batch>`。**D5**(M2 起为真实现)。演示脚本 1–10 步真栈走查通过 |
| **M2 验证套件** | ✅ 检查点 M2(V3/V6/V7) | **T2 冒烟**(`verify/smoke.py`,V7)·**T4 锚点回放**(`anchor_replay.py`,V3,page_end 窗+rapidfuzz+表格/降级豁免)·**对账**(`reconcile.py`,逐 doc count)·**rebuild**(`rebuild.py`,冷备零编码回灌,V6)· mini golden set(`tests/golden/`,**F1=1.0**)· report 加 t2/t4_pass_rate · finalize 自动跑 T2/T4 留痕。**DeepDoc 降可选/留独立轮**(走查证明真实 PDF 痛点在 clause_tree,与解析器无关) |
| **M3 E1+report** | ✅ 检查点 M3(V1–V8 全过) | **E1 义务预打标**(`enrich/e1_obligation.py`,零 LLM 正则 + `config/obligation.yaml` 词表;接 `_structuring` 装配:**clear→s3→tag→s4**,写 `clause_tags`;**V8** golden precision=1.0/recall=1.0 ≥0.90)· **report 全量打磨**(义务覆盖/队列处置/版本链/按语料 P-INT·P-EXT 拆 + JSON 落 `reports/<batch>.json`)· **全套 263 passed**(含 11 model-gated,本地 BGE-M3)· 真 CLI 走查通过(report 义务覆盖 42.9% + search 四级引用)。**续#1**:`search` hit 回查 `clause_tags` 出 `[义务]` 标(不动 Milvus schema)。**续#2**:matcher 泛化可配 `bare_chars`(应/须)+ X须(无须/毋须)排除 → recall 1.0 |

**当前链路**:`ingest`→s1→s2→STRUCTURING(`e1_enabled` 时 **clear→s3→tag→s4**:E1 义务打标随切块写 `clause_tags`,异常不阻断终态)→META_REVIEW(全件 meta_confirm 人工闸)→`meta confirm`(approve)→EMBEDDING→INDEXING→INDEXED→**finalize**(带 supersedes 时自动把旧版置 superseded:PG `supersede_version` 原子事务 + Milvus 从冷备改标量不删);`search` 混合查(默认 effective,`--include-superseded` 见旧版/`--corpus`/`--topk`)出四级引用;degrade 重入索引终于 DEGRADED_INDEXED。**待修小项**:s0 隔离件不写 review_queue(`queue list` 不可见)。

**真模型/向量化运行前提**:BGE-M3 经 modelscope 拉到本地(hf-mirror 在该网络 308 跳回 HF、直连慢),设 `PIPELINE_EMBEDDING_MODEL=<本地目录>` + `HF_HUB_OFFLINE=1`;未设时 embed/s5 集成测试自动 skip(绝不联网下载)。

Run tests/tools via the project venv: `.venv/bin/python -m pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/demo up`. The stack (pg16 + milvus2.4) comes up via `demo up`; integration tests skip when it's down.

The spec positions this demo as a local, minimal-runnable subset of an upstream production design ("生产设计 V1.5", not in this repo). Section references like §6.2 / §18.2 / §21 point into that production doc.

## What this system does

A document-processing pipeline (S0–S5) that ingests regulatory/policy documents (内规 internal rules as docx, 外规 external rules as pdf), parses them to a unified IR, runs quality gates, builds a clause tree, chunks, embeds, and indexes into Milvus with PostgreSQL as the authority. The demo's differentiated value is its verification components (anchor replay, idempotency, rebuild) and a unified human-review queue.

## Architecture (intended)

```
CLI (typer)  →  Orchestrator (single-process polling worker)  →  stages/ s0..s5 (pure functions)
PostgreSQL 16 (authority)  |  Milvus 2.4 (projection)  |  local FS ObjectStore (originals + IR)
```

- **Orchestrator** is a single-process worker that loops: `SELECT` advanceable docs `BY pipeline_status` → call the matching stage pure function → conditionally transition state → write `pipeline_events`. Human-wait states (`QC_FAILED` / `META_REVIEW` / `QUARANTINED`) are **not** polled; they wait for a CLI command to advance them. This PG-polling design is the demo stand-in for the production Temporal workflow + Signal model.
- **Stages are pure functions** with a uniform signature `(ctx, doc_version_id) -> StageResult`. They communicate **only** through PG state and ObjectStore artifacts — stage modules must not import each other. This isolation is the precondition for the production migration to Temporal activities. Do not break it.
- **IR (Intermediate Representation)** is the stable boundary between parsers and everything downstream. It is a pydantic model (`src/pipeline/ir.py`) carrying blocks/tables/bbox/page, full-fidelity to production §4.2. Swapping the parser (light → DeepDoc) must not touch any downstream code — that swap is itself an architectural test (M2 milestone gate).
- **Adapters** abstract the swappable parts: `ParserAdapter` (light = python-docx + pdfplumber; DeepDoc vendored from RAGFlow), `EmbeddingClient` (local FlagEmbedding BGEM3 vs OpenAI-compatible endpoint), `ObjectStore` (local FS, but key layout mirrors MinIO: `raw/{corpus_type}/{batch_id}/{doc_version_id}.{ext}`, `ir/{doc_version_id}.json`). Never bypass these abstractions to call an implementation directly.

## State machine (demo subset)

```
REGISTERED → PARSING → QC_PENDING → STRUCTURING → META_REVIEW → EMBEDDING → INDEXING → INDEXED
              ↓            ↓ (fail)                  (CLI confirm gate)
         PARSE_FAILED   QC_FAILED → (queue fix) → QC_PENDING (re-enter)
                                  → (queue degrade) → DEGRADED_INDEXED
                                  → (queue reject) → REJECTED
QUARANTINED (hash dup-suspect / missing security level / outside format whitelist / scanned image)
```

- `reprocess <doc_version_id>` replaces the production REPARSE states: full re-run + orphan cleanup by `doc_version_id` range. Deterministic chunk_id makes full re-runs safe (same ID overwrites).
- `DEGRADED_INDEXED` (`chunks.degraded=true`): full-text searchable only, excluded from clause-level references, exempt from T4 anchor replay (and explicitly labeled).
- Every transition writes `pipeline_events` (timestamp, actor [system / CLI username], from/to state, error code). Error codes follow the production E1xx–E8xx scheme; demo-specific ones use a `-DEMO` suffix (e.g. `E202-DEMO` = OCR not enabled, `E101-DEMO` = outside whitelist).

## Hard contracts — do not change these

These are kept byte-identical to the production design so demo code evolves into production code:

- **`chunk_id` formula**: `sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]`. This is the root of idempotency. One character changed breaks V5.
- **manifest contract**: 9 required columns, validated on import; mismatch rejects the whole batch.
- **PG field names / types / enums** match production §10, **add-only** evolution (enforced by Alembic migrations — never rename or drop). Tables not yet built are kept as commented DDL in the schema file.
- **Milvus `audit_corpus` collection** uses the full production schema including scalar fields `perm_tag`, `biz_domain`, `issuer_level` and the partition key (HNSW params at defaults). Note: `perm_tag` is written through the whole chain but filtering logic is intentionally **not** implemented (field reserved, logic deferred).
- **Write order & consistency**: PG first → Milvus upsert → flush → set `INDEXED`. Before `INDEXED`, chunk `status=staging` is invisible to search. This shields half-built state.
- **Chunking six rules** and clause-tree regex (Chinese numeral normalization, `第X条之一` inserted clauses, virtual root node, breadcrumb prefix, page anchors) follow §6.1–6.2 exactly. The only deliberate demo difference: table blocks get a breadcrumb-only prefix, no LLM summary. `clause_tree` also supports **decimal numbering** (交易所规则体例 `2.17`/`3.1.2`, number kept as full decimal for `_key` tuple ordering), strips **TOC entries** (≥4 dotted-leader chars), and rejects **cross-reference fragments** (`第X条` followed by enumeration punctuation, or `N.M.K 条` decimal refs) so inline citations aren't mis-read as headings — these are clause_tree (IR-boundary downstream) concerns, independent of the parser.

## All tunable numbers live in config

Every value marked ⚠ in the spec (QC thresholds, edge-band ε, token ranges, batch sizes, timeouts) **must be read from config, never hardcoded**:
- `config/settings.toml` — connection strings, embedding mode (local/endpoint), L2/E1 toggles
- `config/qc_thresholds.yaml` — the 7 QC indicators + edge band ε
- `config/profiles.yaml` — P-INT / P-EXT profile differences

LLM usage is **off by default** — the demo makes zero LLM calls in its default path. L2 metadata assist is a config toggle; when on it uses the existing LLM factory with prompts centralized in root `PROMPTS.md`.

## CLI commands (typer)

The single binary is `demo`:

```
demo up | down                         # bring up / tear down pg + milvus (compose)
demo ingest <dir> --manifest <xlsx>    # S0 entry; drives the pipeline
demo status [batch]
demo queue list | show | fix | degrade | reject | release <id>   # unified human-review queue
demo meta list | confirm <id | --batch>                          # META_REVIEW gate
demo search "<q>" [--include-superseded] [--corpus internal|external] [--topk N]
demo verify smoke | replay | reconcile | idempotency
demo rebuild                           # drop Milvus collection, re-load from PG + bytea cold backup
demo reprocess <doc_version_id>
demo report <batch>
```

The unified review queue (`review_queue` table) is the **single** entry point for all human actions — it carries three `queue_type`s (qc_fix / quarantine / meta_confirm) in one model. This consolidation (production implied 7 separate workbench UIs) is a core demo decision: production only adds a web shell over this domain model.

## Verification components (the demo's point) — ✅ M2 实现(`verify/`)

| Component | What it asserts | Trigger | M2 as-built 细节 |
|---|---|---|---|
| T2 smoke (V7) | per-doc synthetic query hits @`t2_hit_at` with `status=effective` filter present | finalize auto + `verify smoke` | 合成查询=标题+首条款前 `t2_head_chars` 字;`SearchResult.expr` 断言过滤位(E801/E802);**排除 superseded 件**(默认检索不可见) |
| T4 anchor replay (V3) | each chunk's text matches source page, breadcrumb stripped; degraded exempt | finalize auto + `verify replay` | 窗 `[page_start-W..page_end+W]`(复用 `rendition.page_texts`)精确子串/`rapidfuzz≥t4_fuzzy_threshold`;**is_table+degraded 豁免** |
| reconcile | PG chunk count vs Milvus `count(dvid)`(非虚高 num_entities); mismatch → E701 + reload from PG | `verify reconcile` | 冷备 `rows_from_cold` 重灌 |
| rebuild (V6) | drop collection → reload from PG `chunks` + bytea cold vectors, zero re-encoding → same top-10 | `demo rebuild` | 纯 insert,count 干净;`rows_from_cold(status=None)` 按存储 status 还原 |
| idempotency (V5) | re-ingest → chunk_id set unchanged, Milvus `num_entities` unchanged | `verify idempotency` | s0 SHA 去重 + duplicate_ingest 留痕 |

Verification components have **no blocking power** over terminal state — they write results to the batch report only (production §21.2). **finalize 在 INDEXED 时跑 T2/T4 并留痕 `pipeline_events.detail['verify']`(§9);`report` 只聚合读取**(不在 report 加载模型——否则无模型时卡住)。`verify` ⚠ 值在 `config [verify]`。

**CLI 推进可靠性契约**:`meta confirm` / `reprocess` / `queue *` 推进中途 stage 异常**不静默 exit 0**——`_advance_one` 回带 error,未达预期终态(INDEXED/…)即非零退出(`_approve_doc` 返成功 bool;meta confirm 聚合)。

## Testing — mini golden set

- 5–8 fixture docs with hand-annotated full clause trees (JSON ground truth). `pytest` asserts clause-tree structure **F1 = 1.0** (demo set must be perfectly parsed; the production 50-doc set uses ≥0.98).
- Unit tests must cover: all branches of Chinese-numeral normalization, the seven node-type regexes, inserted-clause / virtual-root edge cases, `chunk_id` determinism (same input → same output twice), and over-long clause splitting with clause-head continuation.
- **Parser-swap regression**: after switching light → DeepDoc, the mini golden set must still pass fully. This is the M2 admission gate.

## Tech stack defaults

Python 3.11 · typer · SQLAlchemy 2.x + Alembic · PostgreSQL 16 (Docker) · Milvus 2.4 standalone (Docker) · FlagEmbedding BGEM3 (dense+sparse, CPU ok; first run downloads ~2GB — document the offline cache path, the deployment target has no internet). Deployment is `docker compose` (pg + milvus) with Python on the host.

## Milestones

- **M1 ✅**: skeleton + S0–S5 full chain on the light parser + state machine + queue CLI + demo steps 1–10 → V1/V2/V4/V5 pass(检查点 D)
- **M2 ✅ 验证套件**(`SPEC_M2.md`): T2/T4/reconcile/rebuild + mini golden set(F1=1.0)→ V3/V6/V7 pass(检查点 M2)。**DeepDoc 降可选/留独立轮**——走查证明真实 PDF 痛点在 `clause_tree`(IR 边界下游),与解析器无关;接入时门=parser-swap 后 golden set 仍 F1=1.0
- **M3 ✅ 检查点 M3**(`SPEC_M3.md`): E1 义务预打标(零 LLM 正则 + `config/obligation.yaml` 词表,接 `_structuring`)+ report 全量打磨 → **V8 达成**(golden P=1.0/R=0.955)。**全套 263 passed(含 11 model-gated,本地 BGE-M3)· V1–V8 全过 · 真 CLI 端到端走查通过**(demo report 义务覆盖/版本链/按语料 + search 四级引用)。bare `须` 数据驱动不入词表(详见 M3 踩坑)。DeepDoc 仍留独立轮。

If DeepDoc vendoring exceeds 1 day, M2 falls back to the light parser for the demo — the IR boundary guarantees this fallback affects no other acceptance point.

## Implementation conventions & pitfalls (learned during the build)

**Environment (non-obvious, easy to re-trip):**
- **Python 3.11 only.** The machine default is 3.14, which has no grpcio/torch wheels → pymilvus/FlagEmbedding won't install. Use `.venv` built from brew `python@3.11`.
- **`setuptools<81`** is pinned: pymilvus 2.4 imports `pkg_resources`, removed in setuptools ≥81. Without the pin, `import pymilvus` fails.
- **LibreOffice** provides `soffice` for the docx→PDF rendition. `rendition.soffice_bin()` resolves it via env `PIPELINE_SOFFICE` > PATH > mac `.app` — set `PIPELINE_SOFFICE` in 信创 deploys.
- **FlagEmbedding (torch)** is the `[embed]` extra, not installed by default; pymilvus emits a benign `pkg_resources` DeprecationWarning.

**Page anchoring — the one real architectural mechanism (see SPEC《页码锚点机制》):** docx has no native page numbers, so page is NOT guessed from the docx. s1 renders a canonical PDF (soffice), parses structure from docx XML, and backfills page via `page_align` — a monotonic two-pointer exact match against the rendition's per-page text (rapidfuzz fallback; miss → `page=None`, caught by QC indicator 4). The rendition is written once (`reprocess` reuses it). pdf inputs use native pages, no rendition.

**Orchestration:** the worker is stage-injection (`Orchestrator(pg, ctx, stages: dict[state→stage])`). It only polls `WORKER_ADVANCEABLE_STATES` that have a registered stage, so human-wait states are structurally never polled. Stages are pure `(ctx, dvid) -> StageResult`; the orchestrator owns the transition + `pipeline_events` (via `pg_io.transition`, which guards with `can_transition`) and enqueues `StageResult.queue`.

**Conventions that bit us:**
- **SQLAlchemy insert order:** no ORM relationships are declared, so FK-dependent inserts in one session are NOT auto-ordered — call `s.flush()` after the parent (e.g. Document before DocVersion, DocVersion before PipelineEvent).
- **ULID prefixes collide:** a ULID's leading chars are the timestamp; `str(ULID())[:8]` truncation collides within the same millisecond. Use the full ULID for unique ids in loops/tests.
- **QC marginal band degenerates** for indicators whose threshold sits at the achievable extreme (page-anchor =100%) or within ε of it (text-garbled 0.01<ε 0.02) — those two have the edge band disabled.
- **chunker `token_count` measures content only** (excludes breadcrumb + 条头续接), so "≤ target_token_max" is a clean invariant. Single oversized paragraphs split at 项（N）/句末；。 boundaries, char-hard-split as last resort (marked `oversize`). `target_token_min` drives same-条 tail coalescing.
- **Integration tests** connect to the live stack and `pytest.skip` when PG/Milvus/soffice are down; each cleans up its rows by `batch_id` in FK-safe order. **fixtures/ is git-ignored** (rebuilt by `tools/build_fixtures.py --all`).
- **Migrations are add-only**, authored by `alembic revision --autogenerate` then verified with `alembic upgrade head` + `alembic check` (no drift). `alembic/versions` is in ruff's lint scope (no longer excluded), so after autogenerate run `ruff check --fix alembic/versions && ruff format alembic/versions` before commit — the template's import order + long `op.add_column` lines violate I001/E501 but are 100% auto-fixable, and the fixes are pure formatting (DDL unchanged).

**M2 踩坑(易再踩):**
- **提交前必跑模型门控套件**:无模型全量会 **skip** 它们(`test_search_meta`/`version_demo`/`reprocess`/`smoke`/`s5`),漏掉这类回归——本会话靠它抓到 2 个。命令:`PIPELINE_EMBEDDING_MODEL=<本地目录> HF_HUB_OFFLINE=1 .venv/bin/python -m pytest -q`(全套含模型 ~12min)。
- **模型门控集成测试假定干净栈**:手动 demo 走查残留数据致 SHA 去重撞车(ingest 返回空 dvids → 解包失败)。跑测试前 `demo down -v` 或清库;自造可 ingest 件用 conftest `unique_docx`(嵌 ULID 保 SHA 唯一);需真实修订对的(`test_version_demo` 用 182/226)只能靠干净栈。
- **report 别现场加载模型**:初版 report 现场跑 smoke → 无模型时触发 HF 下载/卡住。改为 finalize 留痕、report 聚合读取(见验证组件段)。
- **T2 冒烟须排除 superseded 件**:旧版默认检索不可见,测它必 E801 误报 → `_indexed_dvids(effective_only=True)`;T4 回放不排除(旧版锚点不变)。
- **clause_tree decimal/cross-ref 是 IR 边界下游**:小数编号(`2.17`/`3.1.2`,`_key` 变长元组排序)、跨法引用过滤(`第X条` 后跟枚举标点 / `N.M.K 条`)、目录剥离(≥4 点引导符)都在 clause_tree,**换 DeepDoc 不解决**。

**M3 踩坑(易再踩):**
- **E1 写 `clause_tags` → 凡删 chunk 的路径要先删 tag**:`clause_tags.chunk_id` 是 chunk 的 FK 子。生产/reprocess 走 `_structuring` 的 **`clear`-先于-s3**(在 `replace_chunks` 删 chunk 前清旧 `is_obligation` 行)已安全;但**测试 teardown 删 chunk 前须先删 clause_tags**——本会话据此修了 `anchor_replay`/`idempotency`/`smoke`/`version_demo` 四个 teardown(FK 子先删)。**决策 A 取 `clear`-先于-s3 而非 `ON DELETE CASCADE`**(零迁移)。
- **义务词表数据驱动、前缀排除是关键**:歧义只在**前缀**——matcher 用可配置 `bare_chars`(应/须)+ `exclusions` 做前缀排除,**统一作用于 `应当`/`须经` 这类 marker**(修 `对应当`/`无须经` 子串误命中)。X应=相应/对应(应在监管语料 98% 表义务);**X须=无须/毋须 必排**(否定义务,不排会把 `无须审批` 误标)。**后缀**(应用/应急/应收)近乎不现(探针:690 个「应」中 应当 637),**不加后缀排除**以免造假阴。续#2 加 bare `须` 后 golden **recall 0.955→1.0**(`无须` 负例锁 X须 排除)。
- **golden 真值须人工独立判,非 matcher 输出**(否则自证):`tests/golden/obligation/obligation_truth.json`(义务/禁止规范句=正;目的/适用范围/定义/施行日期/审批权限分配=负),含 `相应` 负例锁「去掉前缀排除」回归、多 marker 正例锁「去掉某词」回归。
- **report 别加载模型(承 M2)**:M3 四项全**纯 PG 聚合**;义务覆盖 `e1_enabled` 关→`None`(不臆造 0%);`reports/<batch>.json` 落文件入 `.gitignore`。
