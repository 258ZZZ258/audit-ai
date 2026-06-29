# Tasks: §9.3 Langfuse 全链路观测(trace 接缝)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-OBSERVE.md` + `PLAN-OBSERVE.md`(已批准:MVP=图层+Retriever
> HyDE/子查询;observe 默认关;接缝+离线安全;单一 tracer + contextvar 串联;langfuse 可选 extra;只读旁路 + fail-safe 吞)。
> 约定:每任务 ≤5 文件、TDD、含验收+验证。**测试基名全仓唯一**:新增 `test_observe`/`test_observe_integration`(均未占用);
> 扩 `test_query_config`。**检索/生成/路由控制流零改;默认 Noop → 零网络 byte 等价;creds 仅 env 绝不入库。**

- [ ] **T1:`config` +`observe`(add-only)** — Phase A(可并行)
  - Acceptance:`QueryConfig` +`observe: bool = False`(§9.3,默认关——观测外发外部服务、守零网络);`_apply_env` +`QUERY_OBSERVE`
    (字符串→bool,对齐 `hyde`/`decompose`)。既有默认零变化。
  - Verify:`pytest query/tests/test_query_config.py`(`observe` 默认 False;`QUERY_OBSERVE=1`→True)。零栈。
  - Files:`query/query/config.py`、`query/tests/test_query_config.py`(扩)。

- [ ] **T2:`observe.py` Tracer 接缝核(Noop/Langfuse/make_tracer)** — Phase B(可并行,核心)
  - Acceptance:`Tracer` Protocol(`trace(name, **fields)` 上下文管理 yield span(`update(**f)`)+ `event(name, **fields)`);`NoopTracer`
    (全 no-op);`LangfuseTracer`(**懒导入 langfuse**;module-level `_current` contextvar;`trace` 建 langfuse trace + set/reset + finally
    flush;`event` 读 `_current` 挂事件;**所有 langfuse 调用 try/except 吞**,异常退化 noop span);`make_tracer(qcfg)`(observe 开 +
    `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` 齐 → Langfuse,否则 Noop)。
  - Verify:`pytest query/tests/test_observe.py`(零栈零网络)—— Noop `trace`/`event` no-op;`make_tracer`(关→Noop / 开+无 creds→Noop /
    开+creds→Langfuse,monkeypatch langfuse + setenv creds);`LangfuseTracer` client 抛 → 不传播(fail-safe);contextvar set/reset。
  - Files:`query/query/observe.py`(新)、`query/tests/test_observe.py`(新)。

- [ ] **T3:`pyproject` `[observe]` extra(langfuse 可选)** — Phase C(可并行,构建)
  - Acceptance:`[project.optional-dependencies] observe = ["langfuse>=2"]`;`LangfuseTracer` 懒导入(默认 noop 不需);`query.observe`
    import 期**不拉 langfuse**。
  - Verify:核对 pyproject 声明;`python -c "import query.observe"` 不报缺 langfuse(默认路径)。
  - Files:`query/pyproject.toml`。

- [ ] **T4:`Retriever` 持 tracer + 发 HyDE/子查询 event** — Phase D(依赖 T2)
  - Acceptance:`Retriever.__init__` +`tracer=None`(None→`NoopTracer()`)+ 存 `self._tracer`;`from_config(qcfg, *, tracer=None)`;
    `_dense_for` 命中 HyDE(text 非空)→ `self._tracer.event("hyde", passage=text)`(发后照常 embed 返 dense);`_subqueries_for` 拆出
    >1 → `self._tracer.event("decompose", subqueries=subs)`(发后照常返 subs)。**event 只读旁路、不改返回值/控制流。**
  - Verify:`pytest query/tests/test_observe.py`(扩,fake tracer 捕获,零栈)—— `_dense_for`(hyde_llm 返 passage)→ 发 `hyde` event 含 passage、
    dense 不变;`_subqueries_for`(decompose 返多)→ 发 `decompose` event 含 subqueries、返值不变;**Noop 默认 → 无 event、检索 byte 等价**。
  - Files:`query/query/retrieve/hybrid.py`、`query/tests/test_observe.py`(扩)。

- [ ] **T5:`QueryAgent` 持 tracer + `ask` 包 trace** — Phase E(依赖 T2+T4)
  - Acceptance:`QueryAgent.__init__` +`tracer=None`(None→`make_tracer(qcfg)`)+ 存;`from_config` 建 tracer 传 `Retriever.from_config(qcfg,
    tracer=tracer)`;`ask()` 包 `with self._tracer.trace("query", input=query) as t:`,`final = self._app.invoke(...)`,`t.update(output=
    final["result"].route_type.value, metadata={merged句/scene/route_type/候选数})`,返 `final["result"]`。**控制流/返回 result 不变。**
  - Verify:`pytest query/tests/test_observe.py`/`test_graph.py`(扩,fake tracer)—— `ask()` 调 `trace("query")`+`update` 终态;Retriever
    hyde/decompose event 挂**同一条** trace(contextvar 串联);**Noop 默认 → ask byte 等价**(既有 `test_graph` 全绿);开/关 result 一致。
  - Files:`query/query/graph.py`、`query/tests/test_observe.py`(扩)。

- [ ] **T6:真 Langfuse 门控集成(gate=observe+`LANGFUSE_*`)** — Phase F 检查点(依赖 T2/T5)
  - Acceptance:`observe=True` + `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`(+`HOST`)→ `make_tracer` 返 Langfuse;`tracer.trace`+`event`+flush
    不抛(轻断言,不依赖 server 回读)。**未设 creds → skip**(绝不联网)。
  - Verify:`pytest query/tests/test_observe_integration.py`(gate 满足时绿;缺 creds→skip)。证真 trace 闭环。**本地无 creds→诚实记 🟡。**
  - Files:`query/tests/test_observe_integration.py`(新建)。

- [ ] **T7:收尾(devlog/GAP/RTM)+ 全仓门** — Phase G 收口
  - Acceptance:`query_devlog.md` 记决策(默认关 + 接缝离线安全 + 单一 tracer/contextvar 串联 + 只读旁路 + fail-safe + langfuse 可选 extra)
    与踩坑;`GAP.md`(§9.3 观测 ❌→🟡、P3 #7 推进);`RTM.md`(§9.3 观测/安全验收挂 SC+test_id + 摘要重算,116 基线不变);`docs/devlog.md` 加阶段。
  - Verify:`PYTHONPATH=... .venv/bin/python -m pytest query/tests -q`(全 query 套件;observe 集成需 creds,**提交前模型门控全量**,
    无 creds 时 skip 不漏回归);`.venv/bin/ruff check .`;DAG 无环。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(config)∥ T2(observe.py 核心)∥ T3(pyproject)→ T4(Retriever tracer,依赖 T2)→ T5(QueryAgent tracer+ask,依赖 T2+T4)→ T6(集成,真 Langfuse)→ T7(收尾+全仓门)。

## 覆盖 SPEC-OBSERVE §7 成功标准
SC1 默认 no-op byte 等价→T2(Noop)/T4·T5(默认 Noop)/既有全链路;SC2 make_tracer 选择→T2;SC3 ask 产 trace→T5;SC4 Retriever 发 event→T4;SC5 contextvar 串联→T2(contextvar)/T5(同一 trace);SC6 fail-safe 吞→T2(try/except);SC7 真 Langfuse 闭环→T6;SC8 只读旁路→T4/T5(开/关 result 一致)。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序(T1∥T2∥T3→T4→T5→T6→T7)· [x] 覆盖成功标准(SC1–SC8)· [x] T7 同步 RTM(§9.3 观测 ❌→🟡)· [x] 测试基名全仓唯一(新 `test_observe`/`test_observe_integration`;扩 `test_query_config`)· [x] 控制流零改 + 只读旁路 + 默认 Noop byte 等价 · [x] creds 仅 env
- [ ] **人工复核批准**
