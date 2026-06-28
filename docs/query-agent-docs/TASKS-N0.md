# Tasks: N0 多轮上下文归并 + R7 澄清闭环 —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-N0.md` + `PLAN-N0.md`(已批准:N0 LLM 为主默认开 / 入口
> `ask(query, history=None)` + CLI `--history-json` / R7 闭环跨请求 / 输出写回 `query`、状态契约零改 / 单轮 no-op byte 等价)。
> 约定:每任务 ≤5 文件、TDD(先写失败测试)、含验收+验证。**测试基名全仓唯一**:新增 `test_merge`(未占用)、
> `test_merge_integration`(未占用);扩 `test_query_config` / `test_graph` / `test_query_cli`(已存在,扩用例)。
> **状态契约 `state.py` 零改、下游 understand/检索/生成零改;默认 stub → 规则版零网络;merge 客户端仅 toggle 开+gateway 时建。**

- [ ] **T1:`config` +`merge_context`/`merge_model`(add-only)** — Phase A(可并行)
  - Acceptance:`QueryConfig` +`merge_context: bool = True`(§3.4 N0 默认开,已决①)+ `merge_model: str | None = None`(None→复用
    `llm_model`,§9.1 N0 轻量调用意图占位);`_apply_env` +`QUERY_MERGE_CONTEXT`(字符串→bool,对齐既有 `docnum_boost` 范式)
    + `QUERY_MERGE_MODEL` 覆盖。既有默认行为零变化。
  - Verify:`pytest query/tests/test_query_config.py`(`merge_context` 默认 True / `merge_model` 默认 None;`QUERY_MERGE_CONTEXT=0`→False、`QUERY_MERGE_MODEL` 设值覆盖)。零栈。
  - Files:`query/query/config.py`、`query/tests/test_query_config.py`(扩)。

- [ ] **T2:`understand/merge.py` 规则版核 + LLM 接缝(核心)** — Phase B(可并行,纯函数零栈)
  - Acceptance:`_rule_merge(query, history)` —— R7 闭环(末轮 assistant+`route_type=="clarify"`→`f"{上一 user 问} {query}"`)→
    代词/省略顺承(含 `router._PRONOUN_ONLY` 标记或 `len<router._MIN_LEN`→`f"{最近 user 问} {query}"`)→ 否则 `None`;坏/缺
    `role`/`content` 轮忽略。`MERGE_SYSTEM`+`build_merge_user(query, history)`+`parse_merged(resp)->str|None`(取 `merged_query`,非串/空→None)。
    `merge_context(query, history, *, llm=None)`:空 history→原句(no-op);`llm` 给定→`parse_merged(llm.chat_json(...))`(空/抛→fail-safe
    回落规则版);无 `llm`→`_rule_merge or query`。**只改写问句,不产出 `clause_id`/不作答**(§7.1 红线)。
  - Verify:`pytest query/tests/test_merge.py`(零栈零网络)—— R7 闭环 / 代词顺承 / no-op(空 history)/ fail-safe(fake llm 抛→规则版)/
    LLM 正常(fake llm 返 `{"merged_query":...}`→采纳)/ 坏轮忽略 / `parse_merged` 畸形→None。
  - Files:`query/query/understand/merge.py`(新)、`query/tests/test_merge.py`(新)。

- [ ] **T3:`PROMPTS.md` 记 §3.4 N0 归并 prompt** — Phase C(可并行,doc)
  - Acceptance:录 `MERGE_SYSTEM`/`build_merge_user` 归并 prompt(契约约定,代码内联镜像,同 L2/E2/§9.2 范式);标注**只改写自足
    问句、不作答、不生成 `clause_id`/发文字号**(§7.1)+ 失败 fail-safe 回落规则版。
  - Verify:人工核对 `PROMPTS.md` 与 `merge.py` prompt 文本一致。
  - Files:`PROMPTS.md`。

- [ ] **T4:`graph.py` `_n0_merge` 节点 + `ask(history)` 接线** — Phase D(依赖 T1+T2)
  - Acceptance:`__init__` +`self._merge_llm = make_llm_client(qcfg, model=qcfg.merge_model or qcfg.llm_model) if qcfg.merge_context
    and qcfg.llm_backend=="gateway" else None`;`_n0_merge(state)`:`merged = merge_context(state.query, state.history, llm=self._merge_llm)`;
    `return {"query": merged} if merged != state.query else {}`;`_build` 改 `START→n0_merge→understand`(加节点+边);
    `ask(query, history=None)`:`invoke(QueryState(query=query, history=history or []))`。**`state.py` 不改;下游节点不改。**
  - Verify:`pytest query/tests/test_graph.py`(扩,零栈,复用既有 fake retriever/monkeypatch)—— ① R7 闭环:`ask(澄清答, history=[原问,clarify])`
    →归并句重路由真实答路径(非再 CLARIFY);② 代词顺承多轮→继承主题;③ **单轮 no-op**:`ask(q)` 空 history→`_n0_merge` 返 `{}`、
    既有路由用例全绿;④ toggle 关+gateway→`_merge_llm is None`(不建、零网络)。
  - Files:`query/query/graph.py`、`query/tests/test_graph.py`(扩)。

- [ ] **T5:CLI `ask --history-json`** — Phase E(依赖 T4 的 `ask` 签名)
  - Acceptance:`ask` 命令 +`--history-json: str | None`;`json.loads`→list[dict] 传 `ask(query, history)`;畸形 JSON→`typer` 友好报错
    (非栈崩、非裸答)。无 `--history-json`→单轮(history 空)。
  - Verify:`pytest query/tests/test_query_cli.py`(扩,CliRunner,monkeypatch `QueryAgent.from_config`)—— `--history-json` 解析→`ask`
    收到 history;畸形 JSON→非零退出+提示;无 flag→单轮。零栈。
  - Files:`query/query/cli.py`、`query/tests/test_query_cli.py`(扩)。

- [ ] **T6:真-LLM 闭环集成(gate=gateway+`OPENAI_API_KEY`)** — Phase F 检查点(依赖 T4)
  - Acceptance:`merge_context=True`+`llm_backend=gateway`+真 `merge_model`→多轮指代(如「它呢」接上轮制度名)**真归并为自足问句**
    (断言 LLM 输出含上轮主题、不含裸指代);**未设 `OPENAI_API_KEY` / 非 gateway→skip**(绝不联网)。聚焦归并层(无需全栈)。
  - Verify:`pytest query/tests/test_merge_integration.py`(gate 满足时绿;缺 key→skip)。证 N0 真-LLM 归并闭环。**本地无 key→诚实记 🟡。**
  - Files:`query/tests/test_merge_integration.py`(新)。

- [ ] **T7:收尾(devlog/GAP/RTM)+ 全仓门** — Phase G 收口
  - Acceptance:`query_devlog.md` 记决策(N0 LLM 为主默认开 + 离线规则版降级 + fail-safe + R7 跨请求闭环 + 状态契约零改)与踩坑;
    `GAP.md`(N0 ❌→部分✅、R7 🟡→闭环✅、§1.3 TO-1 推进);**`RTM.md`** N0/R7/§3.4 挂 SC+test_id + 覆盖摘要重算;`docs/devlog.md` 加阶段。
  - Verify:`PYTHONPATH=... .venv/bin/python -m pytest query/tests -q`(全 query 套件;merge 集成需 gateway+key,**提交前模型门控全量
    跑一次**,无 key 时 skip 不漏回归);`.venv/bin/ruff check .`;DAG 无环。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(config)∥ T2(merge.py 核心)∥ T3(PROMPTS)→ T4(graph 接线,依赖 T1+T2)→ T5(CLI,依赖 T4)∥ T6(集成,依赖 T4,真 gateway)→ T7(收尾+全仓门)。

## 覆盖 SPEC-N0 §7 成功标准
SC1 R7 澄清闭环→T2(`_rule_merge` R7 分支)/T4(`_n0_merge`+跨请求);SC2 代词/省略顺承→T2/T4;SC3 **单轮 no-op byte 等价**→T2(空 history 短路)/T4(返 `{}`)/既有全链路;SC4 **LLM 为主+fail-safe**→T2(LLM 分支 try/except)/T6(真闭环);SC5 **默认开+零网络**→T1(默认 True)/T4(`_merge_llm` 仅 gateway 建)/T2(stub 路径无网络);SC6 入口契约→T4(`ask(history)`)/T5(`--history-json`);SC7 红线无臆造→T2(不产出 `clause_id`)+既有 `test_evidence_guards` 不破。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序(T1∥T2∥T3→T4→T5∥T6→T7)· [x] 覆盖成功标准(SC1–SC7)· [x] T7 同步 RTM(N0❌→部分✅ / R7🟡→闭环✅)· [x] 测试基名全仓唯一(新 `test_merge`/`test_merge_integration`;扩 `test_query_config`/`test_graph`/`test_query_cli`)· [x] 状态契约 `state.py` 零改 · [x] 单轮零回归守护(T2/T4)
- [ ] **人工复核批准**
