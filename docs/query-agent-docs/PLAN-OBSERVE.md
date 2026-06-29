# Plan: §9.3 Langfuse 全链路观测(trace 接缝)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-OBSERVE.md`(已批准:① MVP=图层+Retriever HyDE/子查询;observe
> 默认关;接缝+离线安全;单一 tracer + contextvar 串联;langfuse 可选 extra;tracer 只读旁路 + fail-safe 吞)。
> **检索/生成/路由控制流零改**(tracer 只读旁路);**默认 Noop → 零网络 byte 等价**。

## 1. 组件与依赖

```
config.py          +observe: bool = False(env QUERY_OBSERVE)
        ▲
observe.py         Tracer(Protocol:trace(name,**f) 上下文管理 + event(name,**f))    [新]
        │          NoopTracer(全 no-op)/ LangfuseTracer(懒导入 langfuse + _current contextvar + flush + fail-safe 吞)
        │          make_tracer(qcfg):observe 开 + LANGFUSE_* creds → Langfuse;否则 Noop
        ▲
retrieve/hybrid.py Retriever.__init__(... , tracer=NoopTracer()) + from_config(tracer=)
        │          _dense_for: text 命中 → self._tracer.event("hyde", passage=text)
        │          _subqueries_for: 拆出 → self._tracer.event("decompose", subqueries=subs)
        ▲
graph.py           QueryAgent.__init__(... , tracer=) ; from_config 建 tracer 传 Retriever.from_config(tracer=)
                   ask(): with self._tracer.trace("query", input=query) as t:
                            final = self._app.invoke(...); t.update(output=route_type, metadata={归并句/scene/候选数/...})
pyproject.toml     [project.optional-dependencies] observe = ["langfuse>=2"]
```

**复用**:接缝 idiom(同 llm/rerank);`maybe_make_llm_client` 的「开+creds 才建」离线安全范式。**默认零新依赖**(langfuse 懒导入+可选
extra)、**默认零网络**(Noop)、creds 仅 env 绝不入库。

> **contextvar 串联**:module-level `_current` 记当前 trace;`ask()` 的 `trace()` 进入时 set、退出 reset;`Retriever.event()` 读 `_current`
> → HyDE/子查询事件挂到 ask 开的同一条 trace。无当前 trace(Noop / 未开 trace)→ event no-op。**单一 tracer 实例**(graph 建、传
> Retriever)→ 一个 langfuse client。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `config` +`observe`(独立)
- `QueryConfig` +`observe: bool = False`;`_apply_env` +`QUERY_OBSERVE`(字符串→bool,对齐 `hyde`/`decompose`)。默认关、既有零变化。
- **检查点 A**:`test_query_config` —— `observe` 默认 False;`QUERY_OBSERVE=1`→True。零栈。

### Phase B — `observe.py` Tracer 接缝(独立,核心,可与 A/C 并行)
- `Tracer` Protocol;`NoopTracer`(`trace` 返 no-op span 上下文 / `event` pass);`LangfuseTracer`(懒导入 langfuse;`_current` contextvar;
  `trace` 建 langfuse trace + set/reset contextvar + finally flush;`event` 读 contextvar 挂事件;**所有 langfuse 调用 try/except 吞**);
  `make_tracer(qcfg)`(observe 开 + `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` 齐 → Langfuse,否则 Noop)。
- **检查点 B**:`test_observe`(零栈零网络)—— Noop `trace`/`event` no-op;`make_tracer`(关→Noop / 开+无 creds→Noop / 开+creds→Langfuse,monkeypatch langfuse);`LangfuseTracer` client 抛 → 不传播(fail-safe);contextvar set/reset。

### Phase C — `pyproject` `[observe]` extra(独立,doc/构建)
- `[project.optional-dependencies] observe = ["langfuse>=2"]`;`LangfuseTracer` 懒导入(默认 noop 不需 langfuse)。
- **检查点 C**:`pip install -e ".[observe]"` 可装(或核对声明);默认 `import query.observe` 不拉 langfuse。

### Phase D — `Retriever` 持 tracer + 发 event(依赖 B)
- `Retriever.__init__` +`tracer=None`(None→`NoopTracer()`)+ 存 `self._tracer`;`from_config(qcfg, *, tracer=None)`;`_dense_for` 命中
  HyDE → `self._tracer.event("hyde", passage=text)`;`_subqueries_for` 拆出 >1 → `self._tracer.event("decompose", subqueries=subs)`。
  **旁路:event 只读、不改返回值/控制流。**
- **检查点 D**:`test_observe`(扩,fake tracer 捕获 events,零栈)—— `_dense_for`(hyde_llm 返 passage)→ 发 `hyde` event 含 passage;
  `_subqueries_for`(decompose 返多)→ 发 `decompose` event 含 subqueries;Noop 默认 → 无 event、检索结果不变(byte 等价)。

### Phase E — `QueryAgent` 持 tracer + `ask` 包 trace(依赖 B+D)
- `__init__` +`tracer=None`(None→`make_tracer(qcfg)`)+ 存;`from_config` 建 tracer 传 `Retriever.from_config(qcfg, tracer=tracer)`;
  `ask()` 包 `with self._tracer.trace("query", input=query) as t:`,`final = invoke(...)`,`t.update(output=final["result"].route_type.value,
  metadata={merged: final["query"], scene: final.get("scene"), route_type: final.get("route_type"), candidates: len(final.get("candidates",[]))})`,返 `final["result"]`。
- **检查点 E**:`test_observe`/`test_graph`(扩,fake tracer)—— `ask()` 调 `trace("query")` + `update` 终态 metadata;Retriever 的 hyde/decompose
  event 挂到**同一条** trace(contextvar 串联);**Noop 默认 → ask 行为 byte 等价**(既有 `test_graph` 全绿)。

### Phase F — 真 Langfuse 门控集成(依赖 B/E;gate=observe+creds)
- `test_observe_integration.py`:`observe=True` + `LANGFUSE_*` creds → `make_tracer` 返 Langfuse;`ask`(或直接 tracer.trace+event)→
  record 不抛、flush 成功(轻断言,不依赖 server 回读)。**未设 creds → skip**(绝不联网)。
- **检查点 F**:集成绿(gate 满足时);真 trace 闭环。**本地无 creds → 诚实记 🟡**。

### Phase G — 收尾(devlog/GAP/RTM)+ 全仓门
- `query_devlog.md` 记决策/踩坑;`GAP.md`(§9.3 观测 ❌→🟡);`RTM.md`(§9.3 观测/安全验收挂 SC+test_id,摘要重算);`docs/devlog.md` 加阶段。
- **检查点 G**:全 query 套件(非模型门)+ ruff 全绿 + DAG 无环;**提交前模型门控全量**(无 creds 时 observe 集成 skip,不漏回归)。

## 3. 并行 vs 串行
A(config)∥ B(observe.py)∥ C(pyproject)→ D(Retriever tracer,依赖 B)→ E(QueryAgent tracer+ask,依赖 B+D)→ F(集成,真 Langfuse)→ G(收尾+全仓门)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **默认回归**(tracer 改行为)| 默认 `observe=False` → Noop → `trace`/`event` 全 no-op、零开销;`test_noop` + 既有 `test_graph`/`test_hyde`/`test_decompose` 守 byte 等价 |
| R2 | **observe 阻断查询**(Langfuse 网络抖)| LangfuseTracer 所有 langfuse 调用 try/except **吞**;`trace` 建失败 → 退化 noop span;`test_tracer_failsafe` 守 ask 仍返 result |
| R3 | **tracer 改业务态/控制流** | tracer **只读旁路**:event 不改返回值、trace.update 只读终态;`test_observe_does_not_alter_result`(开/关 result 一致)|
| R4 | **contextvar 串不上**(event 落不到当前 trace)| 单一 tracer 实例(graph 传 Retriever)+ module-level `_current`;`test_event_attaches_to_current_trace` 验同一 trace |
| R5 | **langfuse 强依赖**(默认装)| 可选 extra `[observe]` + 懒导入;默认 noop 路径不 import langfuse;`test_make_tracer` 关分支不触 langfuse |
| R6 | **creds 泄漏** | creds 仅 env `LANGFUSE_*` 绝不入库;集成无 creds → skip |
| R7 | **PII / 全量 trace 量** | 本切片全量(observe 开时);采样率/脱敏/保留归运维(§12,SPEC Open Q #2);trace 字段限已有业务字段 |
| R8 | **flush 未收口**(trace 丢) | `trace` 上下文 finally `flush`(try/except 吞);集成验 flush 不抛 |

## 5. 可追溯(SPEC §7 SC → 组件 / 守护)
| SC | 组件 | 守护 |
|---|---|---|
| SC1 默认 no-op byte 等价 | `make_tracer` 关→Noop | `test_noop_tracer` + 既有全链路 |
| SC2 make_tracer 选择 | `make_tracer`(observe+creds)| `test_make_tracer` |
| SC3 ask 产 trace | `ask` 包 `trace`+`update` | `test_ask_records_trace` |
| SC4 Retriever 发 event | `_dense_for`/`_subqueries_for` event | `test_retriever_emits_events` |
| SC5 contextvar 串联 | `_current` + 单一 tracer | `test_event_attaches_to_current_trace` |
| SC6 fail-safe 吞 | LangfuseTracer try/except | `test_tracer_failsafe` |
| SC7 真 Langfuse 闭环 | LangfuseTracer + 真 creds | `test_observe_integration`(gate)|
| SC8 只读旁路 | tracer 不改 state/答复 | `test_observe_does_not_alter_result` |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–G)· [x] 并行 · [x] 风险(含默认零回归 + fail-safe 不阻断 + 只读旁路 + contextvar 串联)· [x] 可追溯(SC1–SC8)
- [ ] **人工复核批准**
