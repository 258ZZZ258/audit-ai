# Spec: §9.2 Kimi 忠实性复核 —— RL-1 真-LLM 闭环

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md **P0 红线**(#2)。RL-1(无裸结论)从"接口+toggle 就位、
> 默认关"(🟡)推进到"真 LLM 复核闭环"(✅)。延续接缝/默认零网络/默认 byte 等价范式。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §9.2(L421)/ §9.1 模型矩阵(L408)/ §6.5 R5 / §8.3 / §0.1-1 红线。
> **关键现状(研究已确认)**:`review_tentative` + `_supported`(fail-closed)+ `judge_multimodel_review` toggle +
> `llm/client.py`(Protocol `chat_json` + stub/gateway factory)+ `pipeline.llm_client`(真 OpenAI 兼容,key 走
> `OPENAI_API_KEY`)**均已实装**(R5 轮)。本切片**只补 RL-1 闭环缺口,不重写接口**。
>
> **已决(2026-06-26,AskUserQuestion):** ① 复核用**独立 `review_model`(Kimi)**,与主答 `llm_model`(Qwen)分离;
> ② 不支持的试探性表述 → **降「待人工核实」**(沿用已实装,不触发重生成);③ 范围 = **仅 R5 判定型**。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **RL-1 真-LLM 闭环**(在既有 `review_tentative` 接口之上接真模型 + 闭环测试):(A)`config` +`review_model`(默认 Kimi,env `QUERY_REVIEW_MODEL`/`OPENAI_REVIEW_MODEL`);(B)`llm/client.py` `make_llm_client(cfg, *, model=None)` **add-only** 模型覆盖 → 复核用 `review_model` 建客户端,**与主答模型分离**(§9.1:主答 Qwen / 复核 Kimi);(C)`r5_judgment.answer_judgment`:`judge_multimodel_review` 开 + gateway 时,用 `review_model` 建**独立复核客户端**传 `review_tentative`,`build_framing` 仍用主答 `llm`;(D)`PROMPTS.md` 记 §9.2 忠实性复核 prompt(契约约定);(E)**真-LLM 闭环集成测试**(gate=gateway+`OPENAI_API_KEY`):复核开 → 不被所引条款支持的试探性表述**降「待人工核实」**、被支持的通过;**未设 key/gateway → skip(绝不联网)**。RL-1 RTM 🟡→✅。 |
| **不做** | **触发重生成**(设计"或触发重生成";本切片只降级,红线安全+简单);**全量双跑 / 其他路由复核**(仅 R5,§9.2 余路由不双跑);**主答模型切换**(主答 `llm_model` 不动);**重写 `review_tentative`/`_supported`/toggle/fail-closed**(已实装,只接真模型);**§9.2 接口下沉 R1 等依据不足边界**(另议);**`framing.strip_bare_conclusion` always-on 后检**(已实装、不动,本切片是其互补的真-LLM 层)。**§15-④** R5 产品形态(甲方张益)/ **§15-①** 网关轻量模型 / 真 Kimi gateway endpoint 可用性(甲方)—— 待确认,非本切片阻塞(本地用 OpenAI 兼容 gateway + env key 跑通即闭环)。 |

## 1. Objective

把 §9.2 多模型复核从"接口就位、默认关、仅形态后检兜底"推进到 **真 LLM(Kimi)忠实性复核闭环**:`judge_multimodel_review`
开 + gateway 时,R5 三段式 ②框定 的试探性表述由**独立复核模型(Kimi)**校验"是否被所引条款支持",不支持 → 降
「待人工核实」—— 在真模型下兜住"无裸结论/无依据结论"红线(RL-1),而非只靠 `strip_bare_conclusion` 形态后检。

成功 = `judge_multimodel_review=True` + `llm_backend=gateway` + `OPENAI_API_KEY` + `review_model` 设 → 真复核模型
对 R5 文本块逐块校验;不支持块降「待人工核实」、支持块通过(集成断言);复核模型**独立于主答**(§9.1);**默认关
byte 等价**(passthrough,不建复核客户端、零网络);**未设 key → 集成 skip**(绝不联网)。RL-1 🟡→✅。

## 2. Tech Stack(增量)

- 复用 `query/`:`judge/review.py`(`review_tentative`/`_supported`,**不改逻辑**)、`judge/r5_judgment.py`(接线点 L104)、
  `llm/client.py`(Protocol + factory)、`config`(加字段)。
- 复用 `pipeline.llm_client`(真 OpenAI 兼容 `chat_json`,key 走 env;**零改动**)。
- 新增:`config` 字段 `review_model`;`make_llm_client` 可选 `model` 参;`r5_judgment` 复核客户端接线;`PROMPTS.md` 条目;
  `query/tests/test_r5_review_integration.py`(真-LLM 闭环,gate)。
- **零新依赖、默认零网络(toggle 关→不建复核客户端)、key 仅 env 绝不入库**。

## 3. Commands

```bash
# 真-LLM 闭环集成(需甲方/本地 OpenAI 兼容 gateway + Kimi 模型):
QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
  QUERY_REVIEW_MODEL=kimi-2.5 \
  .venv/bin/python -m pytest query/tests/test_r5_review_integration.py -q
# 单元(零网络):
.venv/bin/python -m pytest query/tests/test_r5_review.py query/tests/test_query_config.py \
  query/tests/test_llm_client.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/config.py        # + review_model: str = "kimi-2.5"(env QUERY_REVIEW_MODEL / OPENAI_REVIEW_MODEL)
query/query/llm/client.py    # make_llm_client(cfg, *, model=None):model or cfg.llm_model(add-only)
query/query/judge/r5_judgment.py  # 复核开+gateway → make_llm_client(qcfg, model=review_model) 传 review_tentative
query/query/judge/review.py  # 不改(接口/ fail-closed 已实装)
PROMPTS.md                   # + §9.2 忠实性复核 prompt(记录既有 _supported system prompt)
query/tests/
  test_r5_review_integration.py   # 真-LLM 闭环(gate=gateway+OPENAI_API_KEY;缺则 skip):不支持降级/支持通过
  test_r5_review.py / test_query_config.py / test_llm_client.py  # 单元:review_model 配置 + model 覆盖 + 接线
docs/query-agent-docs/SPEC-REVIEW.md / PLAN-REVIEW.md / TASKS-REVIEW.md
```

## 5. Code Style

沿用 factory/接缝 idiom。`make_llm_client` 加可选 `model`(add-only,默认 `cfg.llm_model` → 既有调用零变化):

```python
def make_llm_client(cfg: QueryConfig, *, model: str | None = None) -> LLMClient:
    backend = cfg.llm_backend
    if backend == "stub":
        from query.llm.stub import StubLLMClient
        return StubLLMClient()
    if backend == "gateway":
        from pipeline.llm_client import make_llm_client as _make
        return _make(model or cfg.llm_model)     # 复核传 review_model → 与主答分离
    raise ValueError(f"未知 QUERY_LLM_BACKEND: {backend!r}(stub | gateway)")
```

`r5_judgment` 接线(复核客户端独立于主答;关时不建、零网络):

```python
blocks = build_framing(clauses, query, llm, qcfg)            # 主答 llm(Qwen)
review_llm = make_llm_client(qcfg, model=qcfg.review_model) if qcfg.judge_multimodel_review else llm
blocks = review_tentative(blocks, citations, review_llm, qcfg)   # 复核 llm(Kimi);关→passthrough
```

## 6. Testing Strategy

- **单元(零网络)**:
  - `make_llm_client(cfg, model=...)`:gateway 分支传 `review_model`(monkeypatch `pipeline.make_llm_client` 断言收到 review_model);stub 分支忽略 model;**默认调用(无 model)= `cfg.llm_model`**(向后兼容)。
  - `config`:`review_model` 默认 + env(`QUERY_REVIEW_MODEL`/`OPENAI_REVIEW_MODEL`)覆盖。
  - `r5_judgment` 接线(fake llm + fake review llm):复核开 → review_tentative 收到**复核客户端**(非主答);复核关 → **不建复核客户端**(passthrough,零网络)。复用既有 `test_r5_review`(接口 fail-closed/降级)。
- **集成(gate=gateway+`OPENAI_API_KEY`,缺则 skip,绝不联网)**:`test_r5_review_integration.py` —— 构造 R5 文本块 + citations(条款**不支持**某试探性表述),复核开 + 真 `review_model` → 该块**降「待人工核实」**;构造被支持表述 → **通过**。证 RL-1 真-LLM 闭环。
- **守护**:**复核关默认 byte 等价**(passthrough + 不建客户端 + 零网络);key **仅 env**(测试不写 key);fail-closed(畸形响应→降级)由既有 `test_r5_review` 守。

## 7. Boundaries

- **Always**:`judge_multimodel_review` 默认关 → **passthrough + 不建复核客户端 + 零网络**(byte 等价);key 仅 env `OPENAI_API_KEY` **绝不入库**;`make_llm_client` `model` 参 **add-only**(默认 `llm_model`,既有调用零变化);复核**仅施于 R5**;红线 `strip_bare_conclusion` always-on 后检**不动**(真-LLM 层是其互补)。
- **Ask first**:**`review_model` 默认值**(`kimi-2.5` 为 §9.1 意图占位;真名待甲方网关模型注册表 §9.1/§15-①);集成测试调真 gateway(需甲方/本地 OpenAI 兼容 endpoint + key)。
- **Never**:**联网默认**(toggle 关零网络;集成未设 key → skip);触发重生成 / 主答模型切换 / 改 `review_tentative` fail-closed 语义;把 key 写进代码/配置/测试;让畸形 LLM 响应放过试探性表述(fail-closed 已守)。

## 8. Success Criteria(可测)

1. **模型分离**:`judge_multimodel_review=True`+gateway → 复核客户端用 `review_model`(Kimi)、主答用 `llm_model`(Qwen);`make_llm_client(cfg, model=review_model)` 单测断言传参。
2. **真-LLM 闭环(RL-1)**:集成(真 gateway+key)→ 不被所引条款支持的试探性表述**降「待人工核实」**、被支持的通过(断言);RTM RL-1 🟡→✅、§9.2 🟡→✅。
3. **默认关 byte 等价**:`judge_multimodel_review=False` → review_tentative passthrough、**不建复核客户端**、零网络(单元断言不调 `make_llm_client(model=...)`)。
4. **`make_llm_client` model add-only**:无 `model` 调用 = `cfg.llm_model`(向后兼容,既有 graph/调用零变化)。
5. **离线**:未设 `OPENAI_API_KEY` / 非 gateway → 集成 **skip**(绝不联网);key 仅 env。
6. **fail-closed 保持**:畸形 / 非严格 bool 响应 → 降级(既有 `test_r5_review` 守,不回归)。
7. `config` +`review_model`(默认 + env);全仓全量 + ruff 全绿;DAG 无环(`query → pipeline → common`)。

## 9. Open Questions(已决 3 + 默认待 gate)

| # | 事项 | 处置 |
|---|---|---|
| **复核模型** | 独立 vs 复用 | ✅ **独立 `review_model`(Kimi)**,与主答分离(§9.1)。 |
| **不支持处置** | 降级 vs 重生成 | ✅ **降「待人工核实」**(沿用已实装,不触发重生成)。 |
| **范围** | R5 vs 多路由 | ✅ **仅 R5 判定型**。 |
| Q1 | `review_model` 默认名 | 默认 `kimi-2.5`(§9.1 意图);env 覆盖;真名待甲方网关注册表(§9.1/§15-①)。 |
| Q2 | 闭环测试形态 | 默认**聚焦 `review_tentative` + 真模型**(构造 blocks/citations,无需全栈,仅 key-gate);全 R5 端到端(`answer_judgment`+栈)留增强。 |
| Q3 | 复核客户端建处 | 默认 `r5_judgment` 内按 toggle 懒建(关→不建);避免 graph 签名churn。 |

## 10. 与 §15 / §9.x 的关系

- **§15-④(R5 产品形态,甲方张益 P0)**:本切片落**真-LLM 复核机制**,不改 R5 三段式产品形态(待甲方确认验收口径);
  机制就绪不阻塞。
- **§15-①(网关轻量模型)**:复核用满血 Kimi(非轻量),不依赖 §15-①;主答/轻任务模型分层另议。
- **§9.1 模型矩阵**:主答 Qwen / 复核 Kimi 经甲方 OpenAI 兼容网关;本地用兼容 gateway + env key 验证闭环,生产换甲方 endpoint。
- **§9.2 既定**:生成后校验(非双跑)、仅 R5+边界、不支持降级 —— 本轮落 R5 真闭环,边界其他路由留后续。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§7 Ask-first `review_model` 默认名 + 真 gateway 依赖、§8 SC2 真-LLM 闭环 + SC3 默认关零网络、§9 Q2 闭环测试聚焦 review_tentative)
