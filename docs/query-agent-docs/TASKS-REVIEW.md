# Tasks: §9.2 Kimi 忠实性复核(RL-1 真-LLM 闭环)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-REVIEW.md` + `PLAN-REVIEW.md`(已批准:独立 `review_model`/降「待人工核实」/仅 R5)。
> 约定:每任务 ≤5 文件、TDD、含验收+验证。**测试基名全仓唯一**:扩 `test_query_config`/`test_llm_stub`(已含 `make_llm_client` 测)/`test_r5_review`;新增 `test_r5_review_integration`(未占用)。
> **接口/toggle/fail-closed 已实装,本切片只接真复核模型 + 闭环测试;零 pipeline 改动;默认关 → 不建客户端 + passthrough + 零网络。** 集成 gate = **gateway + `OPENAI_API_KEY`**。

- [ ] **T1:`config` +`review_model`(add-only)** — Phase A(可并行)
  - Acceptance:`QueryConfig` +`review_model: str = "kimi-2.5"`(§9.1 复核 Kimi 意图占位);`_apply_env` +`QUERY_REVIEW_MODEL` / `OPENAI_REVIEW_MODEL` 覆盖。默认关行为零变化。
  - Verify:`pytest query/tests/test_query_config.py`(默认 `kimi-2.5`;env 覆盖)。零栈。
  - Files:`query/query/config.py`、`query/tests/test_query_config.py`(扩)。

- [ ] **T2:`make_llm_client(cfg, *, model=None)` 模型覆盖(add-only)** — Phase B(可并行)
  - Acceptance:`make_llm_client` +可选 `model`;gateway 分支 `_make(model or cfg.llm_model)`;stub 分支忽略 `model`。**无 `model` 调用 = `cfg.llm_model`**(既有 graph/调用零变化)。
  - Verify:`pytest query/tests/test_llm_stub.py`(**monkeypatch `pipeline.llm_client.make_llm_client`**:`model=review_model`→传 review_model、无 `model`→传 `cfg.llm_model`;stub 分支不碰 model)。零栈零网络。
  - Files:`query/query/llm/client.py`、`query/tests/test_llm_stub.py`(扩)。

- [ ] **T3:`r5_judgment` 复核客户端接线(模型分离 + 关时不建)** — Phase C(依赖 T1+T2)
  - Acceptance:`answer_judgment`:`review_llm = make_llm_client(qcfg, model=qcfg.review_model) if qcfg.judge_multimodel_review else llm`;`review_tentative(blocks, citations, review_llm, qcfg)`;`build_framing` 仍用主答 `llm`。**`review.py`/`_supported` 不改。**
  - Verify:`pytest query/tests/test_r5_review.py`(monkeypatch `make_llm_client`:复核**开**→review_tentative 收到 **review_model 客户端**;复核**关**→**不调 `make_llm_client(model=...)`**、passthrough、零网络;既有 fail-closed/降级用例不回归)。零栈。
  - Files:`query/query/judge/r5_judgment.py`、`query/tests/test_r5_review.py`(扩)。

- [ ] **T4:`PROMPTS.md` 记 §9.2 忠实性复核 prompt** — Phase D(可并行,doc)
  - Acceptance:录 `_supported` 的 system/user prompt(契约约定,代码内联镜像,同 L2/E2 范式);标注 fail-closed(严格 bool)+ 默认关。
  - Verify:人工核对 `PROMPTS.md` 与 `review.py` `_supported` prompt 文本一致。
  - Files:`PROMPTS.md`。

- [ ] **T5:真-LLM 闭环集成(gate=gateway+`OPENAI_API_KEY`)** — Phase E 检查点(依赖 T3)
  - Acceptance:构造 R5 文本块 + citations(条款**不支持**某试探性表述)→ 复核开 + 真 `review_model` → 该块**降「待人工核实」**;构造**被支持**表述 → **通过**。**未设 `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。聚焦 `review_tentative` + 真模型(无需全栈)。
  - Verify:`pytest query/tests/test_r5_review_integration.py`(gate 满足时绿;缺 key→skip)。证 RL-1 真闭环。
  - Files:`query/tests/test_r5_review_integration.py`(新建)。

- [ ] **T6:收尾(devlog/GAP/RTM)+ 全仓门** — Phase F 收口
  - Acceptance:`query_devlog.md` 记决策(独立 review_model、关时不建客户端零网络、聚焦 review_tentative 闭环)与踩坑;`GAP.md`(§9.2 🟡→✅);**`RTM.md`** RL-1 🟡→✅ + §9.2/R5-review 挂 test_id + 覆盖摘要重算;`docs/devlog.md` 加阶段。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;复核集成需 gateway+key,**提交前模型门控全量**);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(config)∥ T2(make_llm_client)∥ T4(PROMPTS)→ T3(r5 接线,依赖 T1+T2)→ T5(集成,依赖 T3,真 gateway)→ T6(收尾+全仓门)。

## 覆盖 SPEC-REVIEW §8 成功标准
SC1 模型分离→T2(传参)/T3(接线);SC2 **真-LLM 闭环 RL-1**→T5;SC3 **默认关 byte 等价+零网络**→T3(关→不建+passthrough);SC4 `make_llm_client` model add-only→T2;SC5 离线 skip→T5;SC6 fail-closed 保持→T3(既有 `test_r5_review` 不回归);SC7 config+全仓门→T1/T6。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC7)· [x] T6 同步 RTM(RL-1🟡→✅)· [x] 测试基名全仓唯一(扩 `test_query_config`/`test_llm_stub`/`test_r5_review`;新 `test_r5_review_integration`)
- [ ] **人工复核批准**
