# Implementation Plan: ref_resolver R4 跨文档指代(§6.7,T2.4)

> SDD 阶段 2(Plan)。依据 `SPEC_REF_R4.md`(已门控批准)。
> 本计划经人工批准 → `TASKS_REF_R4.md`(任务级验收)→ `incremental-implementation`+`test-driven-development` 逐任务 TDD 落地 → 交 Codex 复审。**本阶段只规划,不写代码。**

## Overview

在既有 `chunking/ref_resolver.py`(R1–R3 已实装)内追加 **R4(跨文档)** 解析:纯函数正则提取条文正文里「《标题》(文号)?第N条」候选 → 注入式 `XRefLookup` 三级匹配(文号→标题→`dict_aliases` 别名,不限 corpus、排除自引、多命中报 ambiguous)→ `align_xref` 产四态 `ParsedRef` → `run_resolver` 合并 R1–R4 写 `clause_references`。**零迁移、不动案例 LLM 链路**。

## Architecture Decisions(承 SPEC §0/§11,门控已确认)

- **D1 专用 `XRefLookup`**:不改 `case_ref_align`/`case_l2`;新 lookup 含 `dict_aliases` 第三级 + ambiguous,与 `RegLookup` **接口形状对齐**但不共享代码。
- **D2 核心对齐 only**:四态正确落库即满足夜间重试/缺口清单的前置;后两者另起一轮。
- **D3 复用底层不复用 `align_cited`**:`align_cited` 只二态、无 span,无法表达四态 standoff。R4 自写 `align_xref`,复用 `normalize_clause_no`/条号归一/超界校验思路。
- **D4 `ParsedRef` 不改 dataclass**:`target_doc_version_id: str | None` 已可承载跨文档 target;R4 `align_xref` **不走 `_mk`**(`_mk` 恒传当前 dvid),自行构造 `ParsedRef`。仅更新注释(`ref_type` +R4、`resolution_status` +ambiguous/pending_target)+ 模块 docstring R1–R3→R1–R4。
- **D5 不限 corpus / 排除 self_dvid / ambiguous 不臆测 / seed v0-draft**(SPEC §11 定案)。

## 依赖图(bottom-up 实现顺序)

```
extract_xrefs (纯函数, 无依赖) ──┐
                                  ├──→ align_xref (依赖 candidate + XRefHit 形状) ──┐
XRefLookup Protocol + XRefHit ───┘                                                  │
                                                                                    ├──→ run_resolver R4 段集成
PgXRefLookup (PG 三级, 依赖 XRefHit 契约) ──────────────────────────────────────────┘
                                                                                    │
seeds/dict_aliases.csv (独立, 生产数据起点; 集成测试自给 fixture 不依赖它) ──────────┘(并行)
```

实现顺序:**纯逻辑先**(extract→align,任何环境可单测)→ **PG 实现** → **集成** → **seed + 文档收口**。

## Task List

### Phase 1:纯逻辑基础(无栈,可单测)

**Task 1 — `extract_xrefs` 正则提取 + `XRefCandidate`**
正则提取条文正文(从 `body_offset` 起、跳面包屑)里的「《标题》(〔YYYY〕N号)?(第X条之N?)?」候选,产 `XRefCandidate(title, doc_number, clause_raw, span_start, span_end, surface_text)`。
- 依赖:None。Size:S(1 文件 + 测试)。
- 测试(先写失败):有文号/无文号/无条号(文档级)/同句多引用/相邻书名号/插入条「之N」/面包屑前缀跳过/正文提及书名但非「第N条」引用不误抓。

**Task 2 — `XRefLookup` Protocol + `XRefHit` + `align_xref`**
定义 lookup 接口(`resolve(doc_number, title) -> XRefHit{status: single|multiple|none, doc_version_id, doc_number, clause_norms}`);`align_xref(candidate, lookup) -> ParsedRef(R4)` 产四态:命中唯一+条号命中/文档级→resolved;多命中→ambiguous(target None);唯一命中但条号超界/无法归一→unresolved;全未命中→pending_target。条号归一复用 `normalize_clause_no`/`_clause_no`。
- 依赖:Task 1(candidate 形状)。Size:M(1 文件 + 测试)。
- 测试(注入 fake lookup,无栈):六态逐一断言 `resolution_status` + `target_doc_version_id` + `target_clause_path_norm`。

**Checkpoint A**:`pytest pipeline/tests/test_ref_resolver.py -q` 纯单元全绿(任何环境,无需栈);`ruff` 绿。

### Phase 2:PG 接入 + 集成

**Task 3 — `PgXRefLookup(db, self_dvid)` 三级查**
PG 实现:① 文号精确 ② 标题精确 ③ `dict_aliases.alias==标题`→canonical 文号/标题回查;均限 effective、**不限 corpus_type**、**排除 self_dvid**;某级 `.all()` 计数≥2 → `status=multiple`(ambiguous)。命中聚合该 doc 全 chunk `clause_path_norm` 入 `XRefHit.clause_norms`。
- 依赖:Task 2(XRefHit 契约)。Size:M(1 文件区段 + 测试)。
- 测试(连 PG,skip if down):文号命中/标题命中/别名命中/同标题两 effective doc→multiple/排除 self/未命中→none。

**Task 4 — `run_resolver` R4 段集成 + 注释更新**
`run_resolver` 内 R1–R3 后追加:`lookup = PgXRefLookup(ctx.db, dvid)`;逐 clause 块 `extract_xrefs`→`align_xref`→收集 rows;与 R1–R3 合并 `s.add_all`。更新 `ParsedRef`/模块 docstring 注释(R1–R3→R1–R4、四态)。集成点 `_safe_refs`/`clear_refs`/`cli.py` 签名不变。
- 依赖:Task 1/2/3。Size:S(1 文件 + 集成测试)。
- 测试(连 PG,skip if down):R4 四态正确落 `clause_references`(造别名命中 + ambiguous + pending_target 场景)+ 幂等(重跑不翻倍)+ 仅 clause 块(case/QA 块不产 R4)。

**Task 5 — `seeds/dict_aliases.csv` v0-draft + seed 装载验证**
补少量常见简称(证券法/公司法等)→ canonical 文号/标题,`dict_version=v0-draft`。确认 seed 装载机制已覆盖 `dict_aliases`(`demo up` 的 seed 步;若 `test_seeds_p0.py` 已覆盖则仅补数据);标注待评审(§16-6 类比)。
- 依赖:None(可与 Task 3 并行;集成测试自给 fixture,不依赖此 seed)。Size:XS–S(数据 + 装载校验)。
- 测试:seed 行可装载、`dict_version` 标注正确(沿用既有 seed 测试模式)。

**Checkpoint B**:干净栈(`demo down -v && demo up`)下 `pytest pipeline/tests/test_ref_resolver.py pipeline/tests/test_seeds_p0.py -q` 全绿;R1–R3 既有 10 单测 + 3 集成测零回归;案例侧 `test_case_ref_align`/`test_case_l2` 零回归。`alembic check` 无漂移(**零迁移**)。

### Phase 3:收口

**Task 6 — 文档同步 + 全量门控**
`structuring_devlog.md` 加 R4 段(决策/踩坑);`GAP.md` 第 4 节 §6.7 R4 行 ❌→✅;`RTM.md` §6.7 行翻 ✅ 挂测试 id;`devlog.md` 阶段索引加行。
- 依赖:Task 1–5。Size:S(纯文档)。
- 验证:合并前全仓 `pytest -q` + 模型门控全量(干净栈,无模型时 skip);`ruff check .` 绿。

**Checkpoint C(交付)**:全部 SPEC §10 成功标准达成;commit→push→PR→交 Codex 复审。

## Risks and Mitigations

| 风险 | 影响 | 缓解 |
|---|---|---|
| 正则误抓/漏抓(书名号嵌套、文号紧邻判定、同句多引用) | 中 | TDD 边界用例先行(Task 1);「《》+可选文号+可选第N条」模式特异;非引用书名(无第N条)不误抓由测试钉死 |
| self_dvid 自引边界(正文写自己全称《X办法》第N条) | 低 | 排除 self 后该级仅 self→视 none;文档自指由 R1「本办法」已捕获;Task 3 测试覆盖排除 self |
| 零迁移假设破裂(实现中发现需索引/列) | 中 | SPEC §3 已核对 schema 充分;一旦需要立即停走 "Ask first"(Boundaries) |
| ambiguous `.all()` 多查性能 | 低 | clause 块数 + 每块引用量有限;不预优化(YAGNI),不加缓存,标注 |
| 集成栈全局单例并发(另有 `feat/query-n0` worktree) | 中 | worktree 隔离;跑集成前与并行会话对齐空闲 + `demo down -v && demo up` 取干净栈,**串行**,绝不并发 |
| 误伤案例侧 `RegLookup` 接口 | 低 | D1 案例侧零改动;`XRefLookup` 独立模块,仅形状对齐不共享代码;Checkpoint B 验案例零回归 |

## Open Questions

无(SPEC §11 三点门控已定案)。

## Parallelization

- **可并行**:Task 1(extract)与 Task 3(PgXRefLookup)无相互依赖;Task 5(seed)独立。
- **须串行**:Task 2 依赖 Task 1 的 candidate 形状;Task 4 依赖 1/2/3。
- 单会话按 Phase 顺序串行 TDD 最稳;并行点仅供参考。**集成栈跑动须与 `feat/query-n0` 会话串行**(全局单例)。
