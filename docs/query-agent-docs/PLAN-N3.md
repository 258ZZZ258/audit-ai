# Plan: N3 问题分解(复合问句拆子查询 → 并行检索再综合)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-N3.md`(已批准:① Retriever 内 decompose+fan-out 接缝;
> ② decompose 默认开;路由按原问判一次;综合=候选并集+单次生成;默认 stub→单查询 byte 等价;LLM 失败 fail-safe→[原问];
> 仅主 retrieve;§0.3 不迭代;V0 未跑→记 🟡)。续在 `feat/query-n1-hyde`(N1 之上)。
> **sparse/HyDE/`embedding_client`/`milvus_io`/`state.py`/graph/生成层零改**;**enumerate/cases 不接**;**与 N1 HyDE 自然组合**
> (每子查询经 `_search_candidates` 走 `_dense_for`)。

## 1. 组件与依赖

```
config.py            +decompose: bool = True(env QUERY_DECOMPOSE)+ decompose_model: str|None=None
        ▲            (env QUERY_DECOMPOSE_MODEL)+ decompose_max_sub: int = 4(⚠ V0 封顶)
        │
retrieve/decompose.py  DECOMPOSE_SYSTEM / build_decompose_user / parse_subqueries     [新,纯函数零栈]
        │              decompose_subqueries(query, llm, *, max_sub) -> list[str]:
        │                try: subs = parse_subqueries(llm.chat_json(...))
        │                except: return [query]                          # fail-safe → 单查询
        │                return subs[:max_sub] if len(subs) > 1 else [query]  # 仅复合 fan-out
        ▲
retrieve/hybrid.py   _build_decompose_llm(qcfg): decompose 开+gateway → make_llm_client else None
        │            __init__(... , decompose_llm=None): self._decompose_llm = decompose_llm
        │            from_config: ... decompose_llm=_build_decompose_llm(qcfg)
        │            _search_candidates(query) -> dict[chunk_id, Candidate]   # 抽自现 retrieve(含 HyDE/sparse)
        │            _subqueries_for(query): decompose_llm None → [query]; else decompose_subqueries
        │            retrieve(): for sq in _subqueries_for: 并集 _search_candidates → rerank(原问)/topk
        │                        # retrieve_enumerate / retrieve_cases 不动(仅主 retrieve)
        ▲
PROMPTS.md           + §3.3 问题分解 prompt(复合→子查询;只拆不作答、不编造字号/条号)
```

**复用**:`make_llm_client`(**零改**)、`pipeline.llm_client`(**零改**)、`retrieve/hyde.py`(HyDE,**零改**,逐子查询组合)、
`_sparse_for`/`_dense_for`(**零改**,`_search_candidates` 内调用)、`EmbeddingClient`/`MilvusIO`(**零改**)。**零新依赖、默认零网络、单查询 byte 等价。**

> **decompose_llm 仅 decompose 开+gateway 建**(镜像 §9.2/N0/N1);关 **或** stub → `None` → `_subqueries_for` 返 `[query]` →
> retrieve **单查询等价既有**。「默认开」仅在配 gateway 时活;仅**复合**问句(LLM 拆 >1)才 fan-out。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `config` +`decompose`/`decompose_model`/`decompose_max_sub`(独立)
- `QueryConfig` +`decompose: bool = True` + `decompose_model: str | None = None` + `decompose_max_sub: int = 4`;`_apply_env`
  +`QUERY_DECOMPOSE`(字符串→bool,对齐 `hyde`/`merge_context`)+ `QUERY_DECOMPOSE_MODEL` 覆盖。既有默认行为零变化(默认 stub → 单查询)。
- **检查点 A**:`test_query_config.py` —— `decompose` 默认 `True`、`decompose_model` 默认 `None`、`decompose_max_sub` 默认 `4`;env 覆盖。零栈。

### Phase B — `retrieve/decompose.py` 纯函数(独立,核心,可与 A 并行)
- `DECOMPOSE_SYSTEM`(复合问句→2–N 子查询,**只拆不作答、不编造字号/条号**;单一→单个)+ `build_decompose_user(query)` +
  `parse_subqueries(resp)->list[str]`(取 `subqueries` 列表,过滤非串/空)+ `decompose_subqueries(query, llm, *, max_sub)`
  (拆→`subs[:max_sub] if >1 else [query]`;抛/空/单跳→`[query]`)。
- **检查点 B**:`test_decompose.py`(零栈零网络)—— `parse_subqueries` 畸形→[];`decompose_subqueries`:fake llm 返多个→多子查询、
  返单个→`[query]`、抛→`[query]`、返空→`[query]`、返 >max_sub→截断;`build_decompose_user` 含原问;`DECOMPOSE_SYSTEM` 含「不编造」「只拆」「复合」。

### Phase C — `PROMPTS.md` 记 §3.3 decompose prompt(独立,doc)
- 录 `DECOMPOSE_SYSTEM`/`build_decompose_user`(契约约定,代码内联镜像,同 §3.1/§3.4 范式);标注**只拆分、不作答、不生成
  `clause_id`/发文字号**(§7.1)+ 失败 fail-safe 回落单查询 + 不进 agentic 循环(§0.3)+ 默认开(仅 gateway 活)。
- **检查点 C**:人工核对 `PROMPTS.md` 与 `decompose.py` prompt 文本一致。

### Phase D — `retrieve/hybrid.py` 抽 `_search_candidates` + retrieve fan-out + `decompose_llm` 接线(依赖 A+B)
- **D1 重构(零行为变更)**:抽 `_search_candidates(query, *, include_superseded) -> dict[str, Candidate]`(现 retrieve() 的分区
  检索+合并,含 `_dense_for`/`_sparse_for`);`retrieve()` 改为 `for sq in self._subqueries_for(query)` 并集 `_search_candidates`
  → rerank(原问)/topk。**单查询时 byte 等价**(`_subqueries_for` 默认 `[query]`)。
- **D2 接线**:`_build_decompose_llm` + `__init__` +`decompose_llm=None` + `from_config` 建 + `_subqueries_for(query)`
  (`decompose_llm None`→`[query]`;else `decompose_subqueries(query, decompose_llm, max_sub=...)`)。
- **检查点 D**:`test_decompose.py`(扩,fake embed/milvus/decompose_llm 构 Retriever,零栈)—— ① `decompose_llm=None` → `_subqueries_for`
  返 `[query]`、retrieve 单查询(`_search_candidates` 调 1 次);② decompose_llm 返多子查询 → retrieve fan-out(`_search_candidates`
  调 N 次)+ 候选**并集**(不同子查询命中并入,保最高分);③ `from_config` 仅 decompose 开+gateway 建 `decompose_llm`(monkeypatch);
  ④ enumerate/cases 不 decompose(`decompose_llm.calls==0`)。**先跑既有 `test_hyde`/检索单元确认重构零回归。**

### Phase E — 真-LLM 拆分门控集成(依赖 B;gate=gateway+`OPENAI_API_KEY`)
- `test_decompose_integration.py`:`decompose_subqueries(复合问句, 真 llm)` → >1 子查询(各含一子约束);`decompose_subqueries(单跳, 真 llm)`
  → `[query]`(单个)。**未设 `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。聚焦拆分层(无需全栈)。
- **检查点 E**:集成绿(gate 满足时);真拆分闭环成立。**本地无 key → 诚实记 🟡**,待真 gateway 跑绿 + V0 标定。

### Phase F — 收尾(devlog/GAP/RTM)+ 全仓门
- `query_devlog.md` 记决策/踩坑;`GAP.md`(N3 ❌→🟡、TO-1 推进、查询理解前端三节点收官);**`RTM.md`**(N3 挂 SC+test_id,
  覆盖摘要重算,116 基线不变);`docs/devlog.md` 加阶段。
- **检查点 F**:全 query 套件(非模型门)+ ruff 全绿 + DAG 无环;**提交前模型门控全量跑一次**(无 key 时 decompose 集成 skip,不漏回归)。

## 3. 并行 vs 串行
A(config)∥ B(decompose.py 核心)∥ C(PROMPTS)→ D(hybrid 重构+接线,依赖 A+B)→ E(集成,依赖 B,真 gateway)→ F(收尾+全仓门)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **retrieve 重构回归**(抽 `_search_candidates` 改行为)| 单查询 `_subqueries_for` 返 `[query]` → 并集=单份 → 与原 retrieve **byte 等价**;`test_subqueries_for_noop` + 既有 `test_hybrid_integration`/`test_hyde` 守;D 先跑既有检索单元 |
| R2 | **decompose 默认开偏离「默认零 LLM」** | 已决②批准;默认 stub → `decompose_llm` 不建 → `[query]` 零网络;仅 gateway+复合活;`test_decompose` 断言 stub 路径不调网络 |
| R3 | **真 LLM 失败/超时阻断检索** | `decompose_subqueries` try/except→`[query]` → 单查询检索,**绝不阻断**;`test_decompose_failsafe` 守 |
| R4 | **fan-out 成本爆炸**(N 子查询 ×2 分区 ×HyDE)| `decompose_max_sub`(默认 4)封顶;仅复合(<30%)触发;`test_decompose_max_sub` 守截断 |
| R5 | **进 agentic 循环**(§0.3 红线)| 一次性拆分、**无迭代/re-retrieve**;decompose 仅产子查询列表,retrieve 一轮并集;无回环代码 |
| R6 | **错误拆分污染答案** | 子查询是检索改写、**不产 `clause_id`**;§7.1 引用注入兜底;`test_evidence_guards` 既有不破 |
| R7 | **污染 route**(子查询误重路由)| decompose 在 Retriever 内、**不改 `state.query`**;route 按原问判一次(已决①);graph/state 零改 |
| R8 | **decompose 误入 R3/R4** | 仅 `retrieve()` fan-out;`retrieve_enumerate`/`retrieve_cases` 零改;`test_enumerate_cases_no_decompose` 守 |
| R9 | **子查询分数尺度不可比** | 并集求**覆盖**为主(各子约束有候选);最终序 max-score + rerank(原问)兜;务实版,精排 V0(SPEC Open Q #2)|
| R10 | **key 泄漏 / V0 overclaim** | key 仅 env 绝不入库,集成无 key→skip;V0 未跑 → 诚实记 🟡(复合占比/拆分质量待实测)|

## 5. 可追溯(SPEC §7 SC → 组件 / 守护)
| SC | 组件 | 守护 |
|---|---|---|
| SC1 复合拆分 | `decompose_subqueries` | `test_decompose_subqueries` |
| SC2 fan-out 并集 | `retrieve` + `_search_candidates` | `test_retrieve_fans_out_union` |
| SC3 默认单查询 byte 等价 | `_subqueries_for`(None→`[query]`)| `test_subqueries_for_noop` + 既有 `test_hybrid_integration` |
| SC4 fail-safe 不阻断 | `decompose_subqueries` try/except | `test_decompose_failsafe` |
| SC5 max_sub 封顶 | `decompose_subqueries` 截断 | `test_decompose_max_sub` |
| SC6 真-LLM 拆分闭环 | `decompose_subqueries` + 真 `decompose_llm` | `test_decompose_integration`(gate)|
| SC7 默认开 + 零网络 | `config` 默认 True + `decompose_llm` 仅 gateway 建 | `test_query_config` / `test_decompose`(无网络)|
| SC8 仅主 retrieve + 不臆造 | `retrieve` fan-out;enumerate/cases 不动 + 不产 `clause_id` | `test_enumerate_cases_no_decompose` / `test_evidence_guards`(既有)|

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–F)· [x] 并行 · [x] 风险(含重构零回归 + 默认零网络 + fail-safe + §0.3 不迭代 + 仅主 retrieve)· [x] 可追溯(SC1–SC8)
- [ ] **人工复核批准**
