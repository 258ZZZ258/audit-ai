# Spec: N3 问题分解(复合问句拆子查询 → 并行检索再综合)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md **P2 查询理解前端**(backlog #6,N0/N1 后收官第三块)。
> 把 §3.3 N3 从 ❌ 推进到实装:**显式复合问句**(含多个并列子约束)→ 拆为子查询 → 并行检索 → 候选并集综合;单跳问句直通。
> **续在 `feat/query-n1-hyde` 分支**(N1 之上,N1+N3 后统一交审)。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §3.3 N3(L176)/ §3 节点链(L90)/ §0.3 不进 agentic 循环(L178)/
> §7.1 引用注入污染兜底 / §15-①⑦(L518/L524)。
> **关键现状(研究已确认)**:`retrieve/hybrid.py` `Retriever.retrieve(query)` 内分区检索→合并→rerank→topk;**N1 HyDE**
> 已在 `_dense_for`(dense 接缝)、`_build_hyde_llm`(仅 hyde 开+gateway 建)落地——N3 复用同范式(`_build_decompose_llm`
> + retrieve() fan-out)。`make_llm_client`/`chat_json`/`EmbeddingClient` 均已实装。
>
> **已决(2026-06-29,AskUserQuestion):** ① **注入点 = Retriever 内 decompose+fan-out 接缝**(镜像 N1;retrieve() 内拆子查询
> → 每子查询走现有 dense(含 HyDE)/sparse → 候选并集 → rerank/topk 一次;**不**走图 N3 节点);② **decompose 默认开**
> (`decompose` 默认 `True`,仅复合问句触发,对齐设计 §3 节点链 + N0/N1 默认开范式)。
>
> **本切片承诺的假设(请复核;有异即纠)**:
> 1. **拆子查询影响检索、路由按原问判一次**:route_type 由 `understand()` 对**原问**判定一次(复合「…是否违规」→ R5);
>    decompose 只在 `retrieve()` 内 fan-out 子查询检索,**不重路由、不改 `state.query`**。
> 2. **综合 = 候选并集 + 单次生成**:每子查询检索的候选按 `chunk_id` **并集**(保最高分)→ rerank(对**原问**)→ topk;
>    生成层**零改**(只是候选集覆盖所有子约束更全)。⚠ 子查询间分数尺度不同,**并集求覆盖**为主、最终序由 rerank/分数兜
>    (务实版,精排 V0 调);decompose 的价值是**覆盖完整性**(每子约束都有候选),非精确排序。
> 3. **「默认开」的离线落地**(同 N1):默认 `llm_backend=stub`,decompose 无规则版兜底(复合判定+拆分需 LLM)。`decompose_llm`
>    **仅 decompose 开 + gateway 时建**;**stub/无 key → `decompose_llm=None` → `_subqueries_for` 返 `[query]` → 单查询 →
>    byte 等价**。仅**复合**问句(LLM 拆出 >1 子查询)才 fan-out;单跳/失败/返空 → `[query]` 直通(N1-fail 式 fail-safe)。
> 4. **仅主 `retrieve`(R1/R5)**:`retrieve_enumerate`(R4)/`retrieve_cases`(R3)**不接**(同 §5.4/HyDE 范式)。
> 5. **不进 agentic 循环(§0.3 硬边界)**:decompose **一次性**拆分,**不迭代**(无 plan→retrieve→reason→re-retrieve);
>    子查询并行检索后综合一次。`decompose_max_sub` 上限(默认 4)封顶 fan-out 成本。
> 6. **与 HyDE 组合**:每子查询经 `_search_candidates` 走 `_dense_for`(HyDE)/`_sparse_for`,故 HyDE 逐子查询生效(自然组合)。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **N3 decompose + retrieve fan-out**:(A)新 `retrieve/decompose.py` —— `DECOMPOSE_SYSTEM`/`build_decompose_user`/`parse_subqueries`/`decompose_subqueries(query, llm, *, max_sub)` 纯函数(LLM 拆复合问句为子查询;单跳/失败/返空 → `[query]`;>max_sub 截断);(B)`retrieve/hybrid.py`:抽 `_search_candidates(query)`(现 retrieve() 的分区检索+合并,含 HyDE dense/sparse)+ `retrieve()` 改为 `_subqueries_for(query)` fan-out → 候选并集 → rerank(原问)/topk + `_build_decompose_llm`(**仅 decompose 开+gateway 建**)+ `__init__`/`from_config` +`decompose_llm`;(C)`config` +`decompose: bool = True`(env `QUERY_DECOMPOSE`)+ `decompose_model: str | None = None`(env `QUERY_DECOMPOSE_MODEL`)+ `decompose_max_sub: int = 4`(⚠ V0);(D)`PROMPTS.md` §3.3 decompose prompt;(E)**单元**(纯函数 + fan-out 并集 + 默认单查询 no-op + fail-safe + max_sub)+ **真-LLM 拆分门控集成**(gate=gateway+`OPENAI_API_KEY`,缺则 skip)。N3 RTM ❌→🟡。 |
| **不做** | **重路由 / 子查询各自路由**(路由按原问判一次;子查询仅检索 fan-out);**agentic 迭代 / re-retrieve / 多跳推理**(§0.3 硬边界:一次性拆分);**改写 `state.query` / 图 N3 节点**(已决①:Retriever 内接缝);**N3 进 R3/R4**(仅主 retrieve R1/R5);**子查询级独立答复 + 拼接**(综合 = 候选并集 + 单次生成,非多答拼接);**改 sparse/`embedding_client`/`milvus_io`/`state.py`/graph**(复用,零改);**§13 V0 复合占比 / 拆分质量评估 / 配额折算**(V0 未做,默认值待实测,记 🟡 不 overclaim);**规则版复合判定**(复合判定+拆分归 LLM,无 gateway → 单查询直通)。**§15-①** 网关轻量小模型 / **§15-⑦** 配额(复合额外触发)—— 待甲方确认,非阻塞(stub 默认 no-op;gateway+key 跑通即闭环)。 |

## 1. Objective

把查询理解前端 N3 问题分解从 ❌ 推进到实装:`decompose` 开 + gateway 时,**显式复合问句**(含多个并列子约束)先由 LLM
拆为 2–N 个独立子查询,`retrieve()`(R1/R5)对每子查询并行检索、候选**并集**后综合生成——解决复合问句「单向量检索难同时
命中多个子约束」的召回缺口(§3.3)。**单跳问句直通**(LLM 返单个 → `[query]`,无额外开销)。**不进 agentic 循环**(一次性
拆分,§0.3)。**污染兜底**:子查询是检索改写、不产引用,错误拆分经 §7.1 引用注入兜底、不污染答案。

**成功** = `decompose=True` + `gateway` + key + 复合问句 → `retrieve()` fan-out 子查询、候选并集覆盖各子约束;真 LLM 拆分闭环
(集成断言复合问句拆出 >1 子查询、单跳问句返单个);**默认 stub → `decompose_llm` 不建 → `[query]` 单查询 → byte 等价**;
LLM 失败/返空/单跳 → `[query]`(绝不阻断);**未设 key → 集成 skip**(绝不联网);enumerate/cases/route/state 不受影响。
**V0 未跑 → N3 记 🟡**(复合占比/拆分质量待实测)。

## 2. Tech Stack(增量)

- 复用 `query/`:`retrieve/hybrid.py`(`Retriever` 抽 `_search_candidates` + `retrieve` fan-out + `decompose_llm`)、`retrieve/hyde.py`
  (HyDE,**零改**,逐子查询自然组合)、`llm/client.py`(`make_llm_client`,**零改**)、`config.py`(加 3 字段 + 2 env)、
  `pipeline.index`(embedding/milvus,**零改**)、`pipeline.llm_client`(真 `chat_json`,**零改**)。
- 新增:`retrieve/decompose.py`(纯函数);`config` 字段 `decompose`/`decompose_model`/`decompose_max_sub`;`PROMPTS.md` §3.3
  条目;`query/tests/test_decompose.py` + `test_decompose_integration.py`(真-LLM 门控)。
- **零新依赖;默认开但默认 stub 零网络(`decompose_llm` 不建)、单查询 byte 等价;真 key 仅 env 绝不入库。**

## 3. Commands

```bash
# 单元(零网络):decompose 纯函数 + retrieve fan-out + 默认单查询 no-op + fail-safe + max_sub
.venv/bin/python -m pytest query/tests/test_decompose.py query/tests/test_query_config.py -q
# 真-LLM 拆分门控集成(需 gateway + key;缺 → skip,绝不联网):
QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
  QUERY_DECOMPOSE_MODEL=<轻量模型> \
  .venv/bin/python -m pytest query/tests/test_decompose_integration.py -q
.venv/bin/ruff check .
# worktree 跑测试:PYTHONPATH=<worktree>/{query,pipeline,libs/common,eval} .venv/bin/python -m pytest ...
```

## 4. Project Structure(增量)

```
query/query/retrieve/decompose.py   # 新:DECOMPOSE_SYSTEM/build_decompose_user/parse_subqueries/decompose_subqueries(query, llm, *, max_sub)
query/query/retrieve/hybrid.py      # 抽 _search_candidates(query);retrieve() fan-out 子查询→并集→rerank/topk;_build_decompose_llm;__init__/from_config +decompose_llm
query/query/config.py               # + decompose: bool = True(QUERY_DECOMPOSE)+ decompose_model: str|None=None(QUERY_DECOMPOSE_MODEL)+ decompose_max_sub: int = 4
PROMPTS.md                          # + §3.3 问题分解 prompt(复合→子查询;只拆不作答、不编造)
query/tests/
  test_decompose.py                 # 单元:parse_subqueries / decompose_subqueries(拆/单跳/抛→[query]/max_sub)/ retrieve fan-out 并集 / 默认单查询 no-op
  test_decompose_integration.py     # 真-LLM 拆分(gate=gateway+OPENAI_API_KEY;缺→skip):复合→>1 子查询、单跳→单个
  test_query_config.py              # + decompose/decompose_model/decompose_max_sub 默认 + env 覆盖
docs/query-agent-docs/SPEC-N3.md / PLAN-N3.md / TASKS-N3.md
```

## 5. Code Style

沿用接缝 idiom（纯函数 + 默认 no-op + LLM 失败 fail-safe 回落单查询）。N3 retrieve fan-out：

```python
# retrieve/decompose.py —— 纯函数、零栈可测、LLM 失败/单跳 → [query]
def decompose_subqueries(query: str, llm: LLMClient, *, max_sub: int = 4) -> list[str]:
    try:
        subs = parse_subqueries(llm.chat_json(DECOMPOSE_SYSTEM, build_decompose_user(query)))
    except Exception:  # noqa: BLE001 — fail-safe:任何异常 → 单查询,不阻断检索
        return [query]
    return subs[:max_sub] if len(subs) > 1 else [query]  # 仅复合(>1)fan-out;单跳直通
```

```python
# retrieve/hybrid.py —— retrieve() fan-out:子查询并集 → rerank(原问)/topk;单查询时等价
def retrieve(self, query: str, *, include_superseded: bool = False) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for sq in self._subqueries_for(query):                 # decompose 或 [query]
        for cid, cand in self._search_candidates(sq, include_superseded=include_superseded).items():
            prev = merged.get(cid)
            if prev is None or cand.score > prev.score:     # 并集保最高分(覆盖各子约束)
                merged[cid] = cand
    ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)
    ranked = self._reranker.rerank(query, ranked)           # rerank 对**原问**
    return ranked[: self._qcfg.topk]
```

## 6. N3 语义（§3.3）

| 项 | 设计 |
|---|---|
| 触发 | **仅显式复合问句**(LLM 拆出 >1 子查询);单跳问句 → `[query]` 直通,无额外检索 |
| 拆分 | 口语复合问句 → 2–N 个独立子查询(每聚焦一子约束);`decompose_max_sub` 封顶 |
| 综合 | 各子查询候选**并集**(保最高分)→ rerank(原问)/topk → 单次生成(生成层零改)|
| 失败回落 | LLM 抛/返空/单跳 → `[query]`(N1-fail 式,绝不阻断)|
| 硬边界 | **不进 agentic 循环**(§0.3):一次性拆分,不迭代推理 / 不 re-retrieve |
| 污染兜底 | 错误拆分不污染答案——子查询是检索改写、不产引用;§7.1 引用注入兜底 |
| 默认值 | `decompose=True`(对齐设计);真拆分仅 gateway 生效;默认 stub → 单查询。复合占比/质量待 §13 V0(记 🟡)|

## 7. Success Criteria（SC，挂 RTM）

| SC | 判据 | test_id |
|---|---|---|
| **SC1** 复合拆分 | `decompose_subqueries` 复合问句(fake llm 返 >1）→ 多子查询;单跳(返 ≤1)→ `[query]` | `test_decompose_subqueries` |
| **SC2** fan-out 并集 | `retrieve()` 多子查询 → 各 `_search_candidates` 候选并集(保最高分)→ rerank/topk | `test_retrieve_fans_out_union` |
| **SC3** 默认单查询 byte 等价 | `decompose_llm=None`(关/stub)→ `_subqueries_for` 返 `[query]` → retrieve 等价既有 | `test_subqueries_for_noop` + 既有 `test_hybrid_integration` |
| **SC4** fail-safe 不阻断 | LLM 抛/返空 → `[query]` → 单查询检索(不阻断)| `test_decompose_failsafe` |
| **SC5** max_sub 封顶 | LLM 返 >max_sub → 截断至 `decompose_max_sub` | `test_decompose_max_sub` |
| **SC6** 真-LLM 拆分闭环 | gateway+key → 复合问句拆 >1、单跳返单个 | `test_decompose_integration`（gate）|
| **SC7** 默认开 + 零网络 | `decompose` 默认 `True`;默认 stub → `decompose_llm` 不建、零网络;env 覆盖 | `test_query_config` / `test_decompose`（无网络）|
| **SC8** 仅主 retrieve + 不臆造 | enumerate/cases 不 decompose;子查询不产 `clause_id`(§7.1)| `test_enumerate_cases_no_decompose` / `test_evidence_guards`(既有)|

## 8. Boundaries

- **Always**:decompose 只改检索 fan-out,route/`state.query`/sparse/生成零改;纯函数零栈可测;LLM 失败 fail-safe 回落单查询、
  绝不阻断;默认 stub → `decompose_llm` 不建、零网络、byte 等价;`decompose_max_sub` 封顶;跑改动波及范围测试,合并前全 query 门跑一次。
- **Ask first**:decompose 默认开偏离「默认零 LLM」(**已决②** 批准,默认 stub 实为 no-op);N3 进 R3/R4;改 sparse/HyDE;加新依赖。
- **Never**:子查询重路由 / agentic 迭代 / re-retrieve(§0.3 硬边界);decompose 产 `clause_id`/编造制度名(只拆分,§7.1);
  真 key 入库(仅 env);无 gateway 时联网/阻断(回落单查询);污染 classify/route(不改 `state.query`);V0 未跑 overclaim 拆分收益。

## 9. 红线（RL，byte-identical to 设计）

- **§0.3 不进 agentic 循环**:decompose **一次性**拆分,**不迭代**(无 plan→retrieve→reason→re-retrieve→synthesize);子查询并行
  检索后综合一次。`decompose_max_sub` 封顶。
- **§7.1 引用 ID 注入(污染兜底)**:错误拆分**不污染最终答案**——子查询是检索改写、不产引用,答案只引检索上下文带 `clause_id` 者。
- **不污染 route**:decompose 在 Retriever 内、**不改 `state.query`** → classify/route 仍基于原问(已决①)。

## 10. Open Questions

1. **复合判定 / 拆分质量**:由 LLM 判定+拆分(无规则版);质量、复合占比(设计估 <30%)、配额折算待 §13 V0 实测。本切片默认开 + 记 🟡。
2. **子查询并集排序**:MVP 并集保最高分 + rerank(原问)兜;子查询间分数尺度不同,精确排序待 V0(rerank 开时改善)。decompose 价值
   是覆盖完整性,非排序。
3. **`decompose_model` 真名 / 轻量小模型**:§9.1/§15-① CP-007 轻量调用;默认 None→复用 `llm_model`;env `QUERY_DECOMPOSE_MODEL`。非阻塞。
4. **`decompose_max_sub=4`**:⚠ V0 占位上限(封顶 fan-out 成本);待实测复合问句子约束数分布调。
