# Plan: §9.2 Kimi 忠实性复核(RL-1 真-LLM 闭环)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-REVIEW.md`(已批准:独立 `review_model`/降「待人工核实」/仅 R5)。
> **接口/toggle/fail-closed/LLM seam 均已实装(R5 轮)** → 本切片只接真复核模型 + 闭环测试,**零接口重写**。
> **零承重(pipeline)改动**(复用 `pipeline.llm_client`);默认关 → passthrough + 不建客户端 + 零网络。

## 1. 组件与依赖

```
config.py            +review_model: str="kimi-2.5"(env QUERY_REVIEW_MODEL / OPENAI_REVIEW_MODEL)
        ▲
llm/client.py        make_llm_client(cfg, *, model=None):gateway → _make(model or cfg.llm_model)  [add-only]
        ▲                                                 stub → StubLLMClient()(忽略 model)
judge/r5_judgment.py  answer_judgment:
        │              blocks = build_framing(clauses, query, llm, qcfg)         # 主答 llm(Qwen)
        │              review_llm = make_llm_client(qcfg, model=qcfg.review_model)  # 仅 toggle 开时建(Kimi)
        │                           if qcfg.judge_multimodel_review else llm        # 关→不建、零网络
        │              blocks = review_tentative(blocks, citations, review_llm, qcfg)  # 既有接口,不改
        ▲
judge/review.py       review_tentative / _supported(fail-closed)—— **不改**(已实装)
PROMPTS.md           + §9.2 忠实性复核 prompt(记录既有 _supported system prompt,契约约定)
```

**复用**:`pipeline.llm_client`(真 OpenAI 兼容 `chat_json` + env key,**零改动**)、`judge/review.py`(接口/降级/ fail-closed)、
`judge/framing.py`(`strip_bare_conclusion` always-on,不动)、`llm/stub.py`(passthrough)。**零新依赖、默认零网络。**

> **复核客户端独立于主答**:`review_llm` 用 `review_model`(Kimi)、`llm`(主答)用 `llm_model`(Qwen)——同一 gateway 不同模型。
> toggle 关 → 不建 `review_llm`(`review_tentative` 直接 passthrough),**零网络、byte 等价**。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `config` +`review_model`(独立)
- `QueryConfig` +`review_model: str="kimi-2.5"`;`_apply_env` +`QUERY_REVIEW_MODEL`/`OPENAI_REVIEW_MODEL` 覆盖。
- **检查点 A**:`test_query_config.py` —— 默认 `kimi-2.5`;env 覆盖。零栈。

### Phase B — `make_llm_client(cfg, *, model=None)`(独立,可与 A 并行)
- gateway 分支 `_make(model or cfg.llm_model)`;stub 忽略 `model`。**无 `model` 调用 = `cfg.llm_model`**(add-only)。
- **检查点 B**:`test_llm_client.py`(**monkeypatch `pipeline.llm_client.make_llm_client`** 断言收到的 model)—— `model=review_model` → 传 review_model;无 `model` → 传 `cfg.llm_model`;stub 分支不碰 model。零栈零网络。

### Phase C — `r5_judgment` 复核客户端接线(依赖 A+B)
- `answer_judgment`:`review_llm = make_llm_client(qcfg, model=qcfg.review_model) if qcfg.judge_multimodel_review else llm`;`review_tentative(blocks, citations, review_llm, qcfg)`;`build_framing` 仍用 `llm`。
- **检查点 C**:`test_r5_review.py`(fake llm/review-llm,monkeypatch `make_llm_client`)—— 复核**开** → review_tentative 收到 **review_model 客户端**(非主答);复核**关** → **不调 `make_llm_client(model=...)`**(passthrough、零网络)。复用既有 fail-closed/降级用例。零栈。

### Phase D — `PROMPTS.md` 记 §9.2 prompt(独立,doc)
- 录 `_supported` 的忠实性复核 system/user prompt(契约约定;代码内联镜像,同 L2/E2 范式)。
- **检查点 D**:人工核对 prompt 与代码一致。

### Phase E — 真-LLM 闭环集成(依赖 C;gate=gateway+`OPENAI_API_KEY`)
- `test_r5_review_integration.py`:构造 R5 文本块 + citations(条款**不支持**某试探性表述)→ 复核开 + 真 `review_model` → 该块**降「待人工核实」**;构造**被支持**表述 → 通过。**未设 `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。聚焦 `review_tentative` + 真模型(无需全栈)。
- **检查点 E**:集成绿(gate 满足时);RL-1 真闭环成立。

### Phase F — 收尾(devlog/GAP/RTM)+ 全仓门
- `query_devlog.md` 记决策/踩坑;`GAP.md`(§9.2 🟡→✅);**`RTM.md`**(RL-1 🟡→✅、§9.2/R5-review 挂 test_id,覆盖摘要重算);`docs/devlog.md` 阶段;全仓全量 + ruff 全绿、DAG 无环。
- **检查点 F**:全仓非模型门 + (有 gateway 时)复核集成绿;ruff 绿。

## 3. 并行 vs 串行
A(config)∥ B(make_llm_client)∥ D(PROMPTS)→ C(r5 接线,依赖 A+B)→ E(集成,依赖 C,真 gateway)→ F(收尾+全仓门)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **默认关回归** R5/八路 | toggle 关 → `review_llm=llm`(不建复核客户端)+ `review_tentative` passthrough;`test_r5_review` 守 byte 等价 + 零网络 |
| R2 | `make_llm_client` `model` **破既有调用** | **add-only**:无 `model` = `cfg.llm_model`;graph/既有调用零变化;`test_llm_client` 守 |
| R3 | 复核**联网默认** | 仅 toggle 开 + gateway 才建客户端;集成未设 `OPENAI_API_KEY` → skip;关→零网络 |
| R4 | **key 泄漏** | key 仅 env `OPENAI_API_KEY` 绝不入库;测试不写 key(skip 时不调) |
| R5 | 复核**误用主答模型** | 接线用 `qcfg.review_model`;`test_llm_client`/`test_r5_review` 断言复核客户端收 review_model(非 llm_model)|
| R6 | **fail-closed 回归** | `review_tentative`/`_supported` **不改**;既有 `test_r5_review`(畸形→降级)守 |
| R7 | 集成依赖**真 gateway**(甲方/本地)| 聚焦 `review_tentative`(无需全栈,仅 key+gateway);gate skip;生产换甲方 endpoint(§9.1)|
| R8 | toggle 关仍建客户端(无谓网络/key)| 接线 `if judge_multimodel_review` 才建;检查点 C 断言关时不调 `make_llm_client(model=...)` |

## 5. 可追溯(§9.2 → 组件 / 守护)
| §9.2 能力 | 组件 | 守护 |
|---|---|---|
| 真 LLM 忠实性复核(RL-1)| `review_tentative` + 真 `review_llm` | 集成(真 gateway)断言降级/通过 |
| 主答/复核模型分离(§9.1)| `make_llm_client(model=review_model)` | `test_llm_client` 断言传 review_model |
| 不支持 → 降「待人工核实」| `review_tentative`(既有)| `test_r5_review` |
| 默认关 byte 等价 + 零网络 | toggle 关 → 不建客户端 + passthrough | 检查点 C |
| 离线(绝不联网)| 集成 gate `OPENAI_API_KEY` | 缺则 skip |
| fail-closed | `_supported`(既有)| `test_r5_review` |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–F)· [x] 并行 · [x] 风险(含默认关零网络 + key + 模型分离)· [x] 可追溯
- [ ] **人工复核批准**
