# Tasks: N3 问题分解(复合问句拆子查询 → 并行检索再综合)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-N3.md` + `PLAN-N3.md`(已批准:① Retriever 内 decompose+fan-out
> 接缝;② decompose 默认开;路由按原问判一次;综合=候选并集+单次生成;默认 stub→单查询 byte 等价;LLM 失败 fail-safe→[原问];
> 仅主 retrieve;§0.3 不迭代;V0 未跑→记 🟡)。续在 `feat/query-n1-hyde`(N1 之上)。
> 约定:每任务 ≤5 文件、TDD(先写失败测试)、含验收+验证。**测试基名全仓唯一**:新增 `test_decompose`(未占用)、
> `test_decompose_integration`(未占用);扩 `test_query_config`(已存在)。
> **sparse/HyDE/`embedding_client`/`milvus_io`/`state.py`/graph/生成层零改;enumerate/cases 不接;默认 stub→`decompose_llm` 不建→零网络。**

- [ ] **T1:`config` +`decompose`/`decompose_model`/`decompose_max_sub`(add-only)** — Phase A(可并行)
  - Acceptance:`QueryConfig` +`decompose: bool = True`(§3 节点链默认开,已决②)+ `decompose_model: str | None = None`(None→复用
    `llm_model`)+ `decompose_max_sub: int = 4`(⚠ V0 封顶 fan-out);`_apply_env` +`QUERY_DECOMPOSE`(字符串→bool,对齐 `hyde`/`merge_context`)
    + `QUERY_DECOMPOSE_MODEL` 覆盖。既有默认行为零变化(默认 stub → 单查询)。
  - Verify:`pytest query/tests/test_query_config.py`(`decompose` 默认 True / `decompose_model` 默认 None / `decompose_max_sub` 默认 4;`QUERY_DECOMPOSE=0`→False、`QUERY_DECOMPOSE_MODEL` 设值覆盖)。零栈。
  - Files:`query/query/config.py`、`query/tests/test_query_config.py`(扩)。

- [ ] **T2:`retrieve/decompose.py` 纯函数核(拆分 + 解析 + fail-safe)** — Phase B(可并行,纯函数零栈)
  - Acceptance:`DECOMPOSE_SYSTEM`(复合问句→2–N 子查询,**只拆不作答、不编造发文字号/条款号**;单一→单个)+ `build_decompose_user(query)`
    + `parse_subqueries(resp)->list[str]`(取 `subqueries` 列表,过滤非串/空)+ `decompose_subqueries(query, llm, *, max_sub=4)`
    (拆→`subs[:max_sub] if len>1 else [query]`;抛/空/单跳→`[query]`,fail-safe)。**不产出 `clause_id`**(§7.1);**不迭代**(§0.3,一次性)。
  - Verify:`pytest query/tests/test_decompose.py`(零栈零网络)—— `parse_subqueries` 畸形→[];`decompose_subqueries`:fake llm 返多个→
    多子查询、返单个→`[query]`、抛→`[query]`、返空→`[query]`、返 >max_sub→截断;`build_decompose_user` 含原问;`DECOMPOSE_SYSTEM` 含「不编造」「复合」。
  - Files:`query/query/retrieve/decompose.py`(新)、`query/tests/test_decompose.py`(新)。

- [ ] **T3:`PROMPTS.md` 记 §3.3 问题分解 prompt** — Phase C(可并行,doc)
  - Acceptance:录 `DECOMPOSE_SYSTEM`/`build_decompose_user`(契约约定,代码内联镜像,同 §3.1/§3.4 范式);标注**只拆分、不作答、
    不生成 `clause_id`/发文字号**(§7.1)+ 失败 fail-safe 回落单查询 + **不进 agentic 循环**(§0.3 一次性)+ 默认开(仅 gateway 活)。
  - Verify:人工核对 `PROMPTS.md` 与 `decompose.py` prompt 文本一致。
  - Files:`PROMPTS.md`。

- [ ] **T4:`retrieve/hybrid.py` 抽 `_search_candidates` + retrieve fan-out + `decompose_llm` 接线** — Phase D(依赖 T1+T2)
  - Acceptance:**D1 重构**:抽 `_search_candidates(query, *, include_superseded) -> dict[str, Candidate]`(现 retrieve() 分区检索+
    合并,含 `_dense_for`/`_sparse_for`);`retrieve()` 改 `for sq in self._subqueries_for(query)` 并集 `_search_candidates` → rerank(原问)/topk。
    **D2 接线**:`_build_decompose_llm(qcfg)`(decompose 开+gateway → `make_llm_client(qcfg, model=decompose_model or llm_model)` else None)
    + `__init__` +`decompose_llm=None` + `from_config` 建 + `_subqueries_for(query)`(`decompose_llm None`→`[query]`;else `decompose_subqueries(query, decompose_llm, max_sub=qcfg.decompose_max_sub)`)。
    **`retrieve_enumerate`/`retrieve_cases`/`_sparse_for`/`_dense_for` 不改;单查询时 byte 等价。**
  - Verify:`pytest query/tests/test_decompose.py`(扩,fake embed[记录]/milvus/decompose_llm 构 Retriever,零栈)—— ① `decompose_llm=None`→
    `_subqueries_for` 返 `[query]`、retrieve `_search_candidates` 调 1 次;② 返多子查询→fan-out N 次 + 候选**并集**(不同子查询命中并入、保最高分);
    ③ `from_config` 仅 decompose 开+gateway 建(monkeypatch `make_llm_client` sentinel);④ enumerate/cases `decompose_llm.calls==0`。
    **先跑既有 `test_hyde`/检索单元确认重构零回归。**
  - Files:`query/query/retrieve/hybrid.py`、`query/tests/test_decompose.py`(扩)。

- [ ] **T5:真-LLM 拆分门控集成(gate=gateway+`OPENAI_API_KEY`)** — Phase E 检查点(依赖 T2)
  - Acceptance:`decompose_subqueries(复合问句, 真 llm)` → >1 子查询(各含一子约束);`decompose_subqueries(单跳问句, 真 llm)` →
    `[query]`(单个)。**未设 `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。聚焦拆分层(无需全栈/Milvus)。
  - Verify:`pytest query/tests/test_decompose_integration.py`(gate 满足时绿;缺 key→skip)。证真拆分闭环。**本地无 key→诚实记 🟡。**
  - Files:`query/tests/test_decompose_integration.py`(新建)。

- [ ] **T6:收尾(devlog/GAP/RTM)+ 全仓门** — Phase F 收口
  - Acceptance:`query_devlog.md` 记决策(decompose 默认开 + Retriever fan-out 接缝 + retrieve 重构抽 `_search_candidates` 零回归 +
    候选并集综合 + §0.3 不迭代 + 与 HyDE 组合 + V0 未跑记 🟡)与踩坑;`GAP.md`(N3 ❌→🟡、**查询理解前端 N0/N1/N3 三节点收官**、
    TO-1 推进);**`RTM.md`** N3/N3-noloop 挂 SC+test_id + 覆盖摘要重算(116 基线不变);`docs/devlog.md` 加阶段。
  - Verify:`PYTHONPATH=... .venv/bin/python -m pytest query/tests -q`(全 query 套件;decompose 集成需 gateway+key,**提交前模型门控
    全量跑一次**,无 key 时 skip 不漏回归);`.venv/bin/ruff check .`;DAG 无环。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(config)∥ T2(decompose.py 核心)∥ T3(PROMPTS)→ T4(hybrid 重构+接线,依赖 T1+T2)→ T5(集成,依赖 T2,真 gateway)→ T6(收尾+全仓门)。

## 覆盖 SPEC-N3 §7 成功标准
SC1 复合拆分→T2(`decompose_subqueries`);SC2 fan-out 并集→T4(`retrieve`+`_search_candidates`);SC3 **默认单查询 byte 等价**→T4(`_subqueries_for` None→`[query]`)/既有 `test_hybrid_integration`;SC4 **fail-safe 不阻断**→T2(try/except);SC5 max_sub 封顶→T2(截断);SC6 **真-LLM 拆分闭环**→T5;SC7 **默认开+零网络**→T1(默认 True)/T4(`decompose_llm` 仅 gateway 建);SC8 仅主 retrieve+不臆造→T4(enumerate/cases 不接)+既有 `test_evidence_guards`。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序(T1∥T2∥T3→T4→T5→T6)· [x] 覆盖成功标准(SC1–SC8)· [x] T6 同步 RTM(N3❌→🟡)· [x] 测试基名全仓唯一(新 `test_decompose`/`test_decompose_integration`;扩 `test_query_config`)· [x] sparse/HyDE/embedding_client/milvus_io/state/graph/生成层零改 · [x] retrieve 重构零回归守护(T4 先跑既有检索单元)· [x] §0.3 不迭代 · [x] V0 未跑诚实记 🟡
- [ ] **人工复核批准**
