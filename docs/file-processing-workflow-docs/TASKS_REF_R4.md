# Tasks: ref_resolver R4 跨文档指代(§6.7,T2.4)

> SDD 阶段 3(Tasks)。依据 `PLAN_REF_R4.md`(已门控批准)。
> 每任务 TDD:**先写失败测试 → 实现 → 验证**(`incremental-implementation`+`test-driven-development`)。修复迭代只跑波及范围;合并前模型门控全量一次(干净栈)。
> **发现修订**:`seeds/dict_aliases.csv`(4 条 v0-draft)+ `pg_io.seed_dicts` 装载 + `test_seeds_p0` 装载测试在 P0 Foundation 已落地 → T5 据此缩小(详见 T5)。
> 测试全加进既有 `pipeline/tests/test_ref_resolver.py`(同模块 + 基名全仓唯一约束)。

---

## Task 1 — `extract_xrefs` 正则提取 + `XRefCandidate`

**Description:** 纯函数从条文正文(`body_offset` 起、跳面包屑)提取「《标题》(〔YYYY〕N号)?(第X条之N?)?」跨文档引用候选,产 `XRefCandidate`(title / doc_number / clause_raw / span_start / span_end / surface_text)。仅提取,不查表。

**Acceptance criteria:**
- [ ] `《标题》` 非贪婪、不跨下一个 `《`;紧邻可选文号(中文〔〕或方括号 [])、可选「第X条(之N)?」。
- [ ] 同句多引用产多候选,各带独立 span;`surface_text` = 完整匹配原文(≤256)。
- [ ] `body_offset` 前(面包屑)的命中跳过;正文提及书名但无「第X条」仍作文档级候选(`clause_raw=None`),纯叙述无《》不产候选。

**Verification:**
- [ ] `pytest pipeline/tests/test_ref_resolver.py -q -k extract`(先红后绿):有文号/无文号/无条号/同句多引用/相邻书名号/插入条「之N」/面包屑跳过/非引用噪声不误抓。
- [ ] `ruff check pipeline/pipeline/chunking/ref_resolver.py` 绿。

**Dependencies:** None
**Files:** `pipeline/pipeline/chunking/ref_resolver.py`、`pipeline/tests/test_ref_resolver.py`
**Scope:** S

---

## Task 2 — `XRefLookup` Protocol + `XRefHit` + `align_xref`(四态)

**Description:** 定义注入式 lookup 接口与四态对齐纯逻辑。`align_xref(candidate, lookup)` 调 `lookup.resolve(doc_number, title)` 得 `XRefHit`,产四态 `ParsedRef(ref_type="R4")`。条号归一复用 `normalize_clause_no`/`_clause_no`。

**Acceptance criteria:**
- [ ] `XRefHit(status: single|multiple|none, doc_version_id, doc_number, clause_norms)`;`XRefLookup` Protocol `resolve(doc_number, title) -> XRefHit`。
- [ ] 四态:`single`+条号在 `clause_norms` 命中→`resolved`(回填 path);`single`+只引文档不引条→`resolved`(path None);`single`+条号超界/无法归一→`unresolved`(target=doc, path None);`multiple`→`ambiguous`(target None);`none`→`pending_target`(target None)。
- [ ] `ambiguous`/`pending_target` 一律 target 留 None(不臆测);自构造 `ParsedRef`(不走恒传 dvid 的 `_mk`)。

**Verification:**
- [ ] `pytest pipeline/tests/test_ref_resolver.py -q -k align`(先红后绿,注入 fake lookup,**无栈**):6 态逐一断言 `resolution_status` + `target_doc_version_id` + `target_clause_path_norm`。
- [ ] `ruff` 绿。

**Dependencies:** Task 1(`XRefCandidate` 形状)
**Files:** `pipeline/pipeline/chunking/ref_resolver.py`、`pipeline/tests/test_ref_resolver.py`
**Scope:** M

### ✅ Checkpoint A(纯单元,任何环境)
- [ ] `pytest pipeline/tests/test_ref_resolver.py -q` 纯单元(extract+align)全绿,无需栈。
- [ ] `ruff check .` 绿。

---

## Task 3 — `PgXRefLookup(db, self_dvid)` 三级查

**Description:** `XRefLookup` 的 PG 实现:① 文号精确 ② 标题精确 ③ `dict_aliases.alias==标题` → `canonical_doc_number`(非空优先)否则 `canonical_title` 回查 ①/②。均限 `version_status="effective"`、**不限 corpus_type**、**排除 self_dvid**;某级 `.all()` 计数 ≥2 → `status="multiple"`。命中聚合该 doc 全 chunk `clause_path_norm` 入 `clause_norms`。

**Acceptance criteria:**
- [ ] 三级顺序正确,别名命中后用 canonical 回查精确级(覆盖现有 seed「文号空、仅 title」路径)。
- [ ] effective + 非 self_dvid 限定;同标题两 effective doc → `multiple`。
- [ ] 命中 `XRefHit` 含 `doc_version_id` + `clause_norms`;未命中 `status="none"`。

**Verification:**
- [ ] `pytest pipeline/tests/test_ref_resolver.py -q -k pglookup`(连 PG,栈未起 skip):文号命中/标题命中/别名(title 兜底)命中/同标题两 doc→multiple/排除 self/未命中→none。按 batch_id 反 FK 序清理。
- [ ] `ruff` 绿。

**Dependencies:** Task 2(`XRefHit` 契约)
**Files:** `pipeline/pipeline/chunking/ref_resolver.py`、`pipeline/tests/test_ref_resolver.py`
**Scope:** M

---

## Task 4 — `run_resolver` R4 段集成 + 注释更新

**Description:** `run_resolver` 内 R1–R3 后追加 R4 段:`lookup = PgXRefLookup(ctx.db, dvid)`;逐 clause 块 `extract_xrefs`→`align_xref`→收集 rows;与 R1–R3 合并 `s.add_all`。更新 `ParsedRef` 注释(`ref_type` +R4、`resolution_status` +ambiguous/pending_target)+ 模块 docstring(R1–R3→R1–R4)。

**Acceptance criteria:**
- [ ] R4 行正确落 `clause_references`(method=rule);与 R1–R3 合并、按 span 排序写。
- [ ] 集成点 `_safe_refs`/`clear_refs`/`cli.py` 签名**不变**;R4 失败不阻断(非阻断纪律)。
- [ ] 仅 `chunk_type=="clause" and not is_parent` 块产 R4(case/QA 块不产)。

**Verification:**
- [ ] `pytest pipeline/tests/test_ref_resolver.py -q -k run_resolver`(连 PG,skip if down):造别名命中 + ambiguous(同标题两 doc)+ pending_target 场景,四态正确入库;幂等(重跑不翻倍);仅 clause 块。
- [ ] R1–R3 既有 3 集成测 + 10 单测**零回归**。
- [ ] `ruff` 绿。

**Dependencies:** Task 1/2/3
**Files:** `pipeline/pipeline/chunking/ref_resolver.py`、`pipeline/tests/test_ref_resolver.py`
**Scope:** S

---

## Task 5 — `dict_aliases` 种子样例补充(缩小:装载/测试已在 P0 Foundation)

**Description:** seed 文件 + `pg_io.seed_dicts` 装载 + `test_seeds_p0` 装载测试**已就位**(4 条 v0-draft,仅 `canonical_title`)。本轮仅按 R4 集成测试需要补样例 —— 补 ≥1 条带 `canonical_doc_number` 的别名(覆盖「别名→文号精确」第三级路径,现有 4 条只覆盖 title 兜底),`dict_version` 续 v0-draft。

**Acceptance criteria:**
- [ ] `seeds/dict_aliases.csv` 含 ≥1 条 `canonical_doc_number` 非空样例;格式/列与现有一致;标 v0-draft 待评审(§16-6 类比)。
- [ ] T3/T4 集成测试可命中(自给 fixture 或复用 seed,二选一明确)。

**Verification:**
- [ ] `pytest pipeline/tests/test_seeds_p0.py -q -k alias`(连 PG,skip if down):新样例随 `seed_dicts` 装载、`canonical_doc_number` 正确。
- [ ] `ruff` 绿(CSV 不参与 lint)。

**Dependencies:** None(可与 T3 并行;集成测试不强依赖此 seed)
**Files:** `seeds/dict_aliases.csv`、(必要时)`pipeline/tests/test_seeds_p0.py`
**Scope:** XS

### ✅ Checkpoint B(干净栈集成)
- [ ] `demo down -v && demo up`(与 `feat/query-n0` 会话串行)后 `pytest pipeline/tests/test_ref_resolver.py pipeline/tests/test_seeds_p0.py -q` 全绿。
- [ ] R1–R3 + 案例侧 `test_case_ref_align`/`test_case_l2` 零回归。
- [ ] `alembic check` 无漂移(**零迁移**)。

---

## Task 6 — 文档同步 + 全量门控

**Description:** 同步 in-repo devlog 与追踪文档;跑合并前全量门控。

**Acceptance criteria:**
- [ ] `structuring_devlog.md` 加 R4 段(决策/踩坑:四态语义、self 排除、不复用 align_cited 的 why)。
- [ ] `GAP.md` 第 4 节 §6.7「ref_resolver R4」❌→✅;`RTM.md` §6.7 R4 行翻 ✅ 挂本轮测试 id;`devlog.md` 阶段索引加行。

**Verification:**
- [ ] 合并前全仓 `pytest -q` + 模型门控全量(干净栈,无模型时 skip)绿。
- [ ] `ruff check .` 绿;`alembic check` 零漂移。

**Dependencies:** Task 1–5
**Files:** `docs/devlogs/structuring_devlog.md`、`docs/file-processing-workflow-docs/GAP.md`、`docs/file-processing-workflow-docs/RTM.md`、`docs/devlog.md`
**Scope:** S

### ✅ Checkpoint C(交付)
- [ ] SPEC §10 成功标准全达成;`commit → push → PR → 交 Codex 复审`(修复归实现侧)。

---

## 任务依赖与并行小结

```
T1 ──→ T2 ──→ T3 ──→ T4 ──→ T6
              T5(并行,独立)──┘
```
- 单会话按 T1→T6 串行 TDD 最稳。
- **集成栈跑动须与 `feat/query-n0` worktree 串行**(PG/Milvus 全局单例)。
- 全程零迁移目标;一旦发现需 Alembic 迁移 → 停,走 "Ask first"。
