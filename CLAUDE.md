# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

**Implementation in progress** (M1). Specs: `SPEC.md` (M1 scope, contracts), `PLAN.md` (4-phase plan), `TASKS.md` (per-task acceptance), upstream `文档处理管线_本地Demo_开发文档_v0.1.md` (V0.1). **The full build narrative — every module, decision, and pitfall — is in `docs/devlog.md`; read it to understand why things are the way they are.** Phase A done (checkpoint A passed); Phase B in progress (s0→s2 chain built). Read the spec before changing contracts — it encodes deliberate cut decisions ("裁机制不裁契约": cut mechanisms, never cut contracts).

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
- **Chunking six rules** and clause-tree regex (Chinese numeral normalization, `第X条之一` inserted clauses, virtual root node, breadcrumb prefix, page anchors) follow §6.1–6.2 exactly. The only deliberate demo difference: table blocks get a breadcrumb-only prefix, no LLM summary.

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

## Verification components (the demo's point)

| Component | What it asserts | Trigger |
|---|---|---|
| T2 smoke | per-doc synthetic query hits @50 with `status=effective` filter present | finalize auto + `verify smoke` |
| T4 anchor replay | each chunk's text exact-matches the source page (±1), breadcrumb stripped; degraded exempt | finalize auto + `verify replay` |
| reconcile | PG chunk count vs Milvus count per doc_version; mismatch → reload from PG (PG wins) | `verify reconcile` |
| rebuild | drop collection → reload from PG `chunks` + bytea cold vectors, zero re-encoding → same top-10 | `demo rebuild` |
| idempotency | re-ingest → chunk_id set unchanged, Milvus `num_entities` unchanged | `verify idempotency` |

Verification components have **no blocking power** over terminal state — they write results to the batch report only (matches production §21.2).

## Testing — mini golden set

- 5–8 fixture docs with hand-annotated full clause trees (JSON ground truth). `pytest` asserts clause-tree structure **F1 = 1.0** (demo set must be perfectly parsed; the production 50-doc set uses ≥0.98).
- Unit tests must cover: all branches of Chinese-numeral normalization, the seven node-type regexes, inserted-clause / virtual-root edge cases, `chunk_id` determinism (same input → same output twice), and over-long clause splitting with clause-head continuation.
- **Parser-swap regression**: after switching light → DeepDoc, the mini golden set must still pass fully. This is the M2 admission gate.

## Tech stack defaults

Python 3.11 · typer · SQLAlchemy 2.x + Alembic · PostgreSQL 16 (Docker) · Milvus 2.4 standalone (Docker) · FlagEmbedding BGEM3 (dense+sparse, CPU ok; first run downloads ~2GB — document the offline cache path, the deployment target has no internet). Deployment is `docker compose` (pg + milvus) with Python on the host.

## Milestones

- **M1 (~5d)**: skeleton + S0–S5 full chain on the light parser + state machine + queue CLI + demo script steps 1–9 → V1/V2/V4/V5 pass
- **M2 (~3d)**: DeepDoc adapter + T2/T4/rebuild/reconcile + mini golden set → V1–V7 pass
- **M3 (optional ~1d)**: E1 obligation tagging + report polish → V8

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
- **Migrations are add-only**, authored by `alembic revision --autogenerate` then verified with `alembic upgrade head` + `alembic check` (no drift).
