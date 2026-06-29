# Spec: §9.3 Langfuse 全链路观测(trace 接缝)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md **P3 横切/工程**。把 §9.3 观测从 ❌ 推进到实装:
> 查询理解前端→检索→生成→复核**全链路 trace**(可回放);HyDE 改写文本、问题分解子查询、route_type、事项标签进 trace,
> 供 §13 V0 第5组 A/B 分析 + 查询分型统计(证伪监测)。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §9.3 观测(L434)/ §安全验收(L507)。
> **关键现状(研究已确认)**:`QueryAgent.ask()` 的 `self._app.invoke(...)` 返回**终态 QueryState**(含 `query` 归并句 /
> `scene` / `route_type` / `candidates` / `result`);HyDE 文本、N3 子查询是 `Retriever` 内部态(`_dense_for`/`_subqueries_for`),
> **不在 QueryState**。`make_llm_client`/接缝 idiom 已立(可镜像 tracer 接缝)。
>
> **已决(2026-06-29,AskUserQuestion):** ① **MVP 范围 = 图层 trace + Retriever 内 HyDE/子查询**(设计 §9.3 全量:HyDE 文本 /
> 分解子查询 / route_type 都进 trace)。
>
> **本切片承诺的假设(请复核;有异即纠)**:
> 1. **observe 默认关**(`observe = False`)——观测是**外发外部服务**(Langfuse)的基建,无 design「默认开」依据,且守本仓
>    「默认零网络」;`NoopTracer` 默认 → 所有 `trace`/`event` 调用 no-op → **零开销、byte 等价**。区别于 N0/N1/N3 的默认开。
> 2. **接缝 + 离线安全**(镜像 offline-gate):`make_tracer(qcfg)` —— `observe` 开 + Langfuse creds(env)齐 → `LangfuseTracer`;
>    否则(关 / 无 creds)→ `NoopTracer`。Langfuse key 走 **env**(`LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`/`HOST`)**绝不入库**。
> 3. **单一 tracer 实例 + contextvar 串联**:`QueryAgent.from_config` 建 tracer,传 `Retriever.from_config(tracer=)`;module-level
>    `contextvar` 记「当前 trace」——`ask()` 开 trace 设 contextvar,`Retriever.event()` 读它 → HyDE/子查询事件**自动挂到同一条
>    trace**(全链路可回放)。无 contextvar(无当前 trace)→ event no-op。
> 4. **langfuse 可选 extra**(`pyproject [observe]`);`LangfuseTracer` **懒导入** langfuse → 默认 noop 路径**零新依赖、不装 langfuse**。
> 5. **MVP = 单 trace + 结构化 events/metadata**(非深层嵌套 span 树):一条 trace/查询,metadata 含归并句/scene/route_type/候选数/
>    result,events 含 HyDE passage、子查询。深层 per-stage span 树留后续。
> 6. **观测只读旁路**:tracer **绝不**改 `state.query`/检索结果/答复/控制流——失败(Langfuse 网络抖动)**fail-safe 吞掉**(observe
>    不阻断查询);trace 内容**不回灌**任何业务逻辑。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **Langfuse trace 接缝**:(A)新 `query/query/observe.py` —— `Tracer` Protocol(`trace(name, **fields)` 上下文管理 + `event(name, **fields)`)+ `NoopTracer`(默认,全 no-op)+ `LangfuseTracer`(懒导入 langfuse;module-level `contextvar` 串联当前 trace;`flush` 收口;**任何异常 fail-safe 吞**)+ `make_tracer(qcfg)`(observe 开+creds → Langfuse,否则 Noop);(B)`config` +`observe: bool = False`(env `QUERY_OBSERVE`);(C)`graph.py` `QueryAgent.__init__`/`from_config` 建并持 tracer,传 `Retriever.from_config(tracer=)`;`ask()` 包 `with self._tracer.trace("query", input=query)`,终态 metadata(归并句/scene/route_type/候选数/result)`update`;(D)`hybrid.py` `Retriever.__init__(tracer=)` + `_dense_for` 发 `event("hyde", passage=)` + `_subqueries_for` 发 `event("decompose", subqueries=)`;(E)`pyproject` `[observe]` extra(langfuse);(F)**单元**(Noop no-op / make_tracer 选择 / ask 与 Retriever 发 event / fail-safe 吞)+ **真 Langfuse 门控**(gate=observe+creds,缺则 skip,绝不联网)。§9.3 观测 RTM ❌→🟡。 |
| **不做** | **深层 per-stage span 树**(MVP 单 trace + events;嵌套 span 留后续);**敏感词 / SSO / 操作日志 / AI 标识页脚**(§9.3 其余,各自切片);**§13 V0 分析逻辑本身**(本切片只产 trace,A/B 分析另做);**改检索/生成/路由控制流**(tracer 只读旁路,零业务改动);**trace 内容回灌业务**(纯观测);**生产 Langfuse 部署/采样率/保留策略**(运维)。 |

## 1. Objective

把 §9.3 观测从 ❌ 推进到实装:`observe` 开 + Langfuse creds 时,每次 `ask()` 产一条**全链路 trace**——含原问 / 归并句(N0)/
HyDE 假设性法言(N1)/ N3 子查询 / scene 事项标签(N2)/ route_type(N4)/ 候选数 / 最终 result——供 §13 V0 第5组 A/B 与
查询分型证伪监测。**默认关 → NoopTracer → 零网络、byte 等价**;Langfuse 网络失败 **fail-safe 吞**(观测绝不阻断查询)。

**成功** = `observe=True` + Langfuse creds → `ask()` 产一条挂齐 graph + Retriever(HyDE/子查询)事件的 trace(集成断言 record 被调、
事件齐);**默认关 → NoopTracer → 所有 trace/event no-op、零网络、既有行为 byte 等价**;Langfuse 抛 → 吞掉不阻断;**未设 creds →
集成 skip**(绝不联网);tracer **不改** state/检索/答复/控制流。§9.3 观测 RTM ❌→🟡。

## 2. Tech Stack(增量)

- 复用 `query/`:`graph.py`(`QueryAgent` 持 tracer + `ask` 包 trace)、`retrieve/hybrid.py`(`Retriever` 持 tracer + 发 event)、
  `config.py`(加 1 字段 + 1 env)。
- 新增:`query/query/observe.py`(Tracer 接缝);`config` 字段 `observe`;`pyproject` `[observe]` extra(langfuse);
  `query/tests/test_observe.py` + `test_observe_integration.py`(真 Langfuse 门控)。
- **默认零新依赖**(langfuse 懒导入 + 可选 extra;默认 noop 不需)、**默认零网络**(observe 关 → Noop)、creds 仅 env 绝不入库。

## 3. Commands

```bash
# 单元(零网络):Noop no-op + make_tracer 选择 + ask/Retriever 发 event + fail-safe
.venv/bin/python -m pytest query/tests/test_observe.py query/tests/test_query_config.py -q
# 真 Langfuse 门控集成(需 observe + creds;缺 → skip,绝不联网):
QUERY_OBSERVE=1 LANGFUSE_PUBLIC_KEY=*** LANGFUSE_SECRET_KEY=*** LANGFUSE_HOST=<host> \
  .venv/bin/python -m pytest query/tests/test_observe_integration.py -q
pip install -e ".[observe]"   # 安装 langfuse(可选 extra;默认不需)
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/observe.py        # 新:Tracer(Protocol)/NoopTracer/LangfuseTracer/make_tracer + _current contextvar
query/query/config.py         # + observe: bool = False(env QUERY_OBSERVE)
query/query/graph.py          # __init__/from_config 建 tracer + 传 Retriever.from_config(tracer=);ask 包 trace + update 终态
query/query/retrieve/hybrid.py # Retriever.__init__(tracer=NoopTracer) + _dense_for/_subqueries_for 发 event
pyproject.toml                # [project.optional-dependencies] observe = ["langfuse>=2"]
query/tests/
  test_observe.py             # Noop no-op / make_tracer(off/无creds/有creds)/ ask·Retriever 发 event(fake tracer)/ LangfuseTracer fail-safe 吞
  test_observe_integration.py # 真 Langfuse(gate=observe+creds;缺→skip):record 不抛、trace 产出
docs/query-agent-docs/SPEC-OBSERVE.md / PLAN-OBSERVE.md / TASKS-OBSERVE.md
```

## 5. Code Style

接缝 idiom（Protocol + 默认 noop + 真实现懒导入 + fail-safe 吞）。tracer 只读旁路、不碰控制流：

```python
# observe.py —— 默认 NoopTracer 全 no-op(零网络、byte 等价);contextvar 串联 graph↔Retriever
_current = contextvars.ContextVar("langfuse_trace", default=None)

class NoopTracer:
    @contextmanager
    def trace(self, name, **fields):
        yield _NoopSpan()      # update() 也 no-op
    def event(self, name, **fields):
        pass

class LangfuseTracer:
    @contextmanager
    def trace(self, name, **fields):
        try:
            tr = self._client.trace(name=name, input=fields)
        except Exception:        # noqa: BLE001 — observe 失败绝不阻断查询
            yield _NoopSpan(); return
        token = _current.set(tr)
        try:
            yield _Span(tr)
        finally:
            _current.reset(token)
            try: self._client.flush()
            except Exception: pass  # noqa: BLE001
```

```python
# hybrid.py —— Retriever 旁路发 event(HyDE/子查询);noop 时零开销
text = hyde_dense_text(query, self._hyde_llm)
if text:
    self._tracer.event("hyde", passage=text)
    return self._embed.embed([text])[0].dense
```

## 6. trace 语义（§9.3）

| 阶段 | 进 trace 的内容 | 来源 |
|---|---|---|
| trace 根 | 原问 query / 最终 route_type / result 摘要 | `ask()` 终态 |
| N0 归并 | 归并句(`merged_query`) | 终态 `state.query` |
| N2 分类 | scene_type + 事项标签(matters)| 终态 `state.scene` |
| N1 HyDE | 假设性法言 passage | Retriever `_dense_for` event |
| N3 分解 | 子查询列表 | Retriever `_subqueries_for` event |
| 检索 | 候选数 | 终态 `state.candidates` |
| 失败 | Langfuse 网络抖动 → **fail-safe 吞**,不阻断查询 | tracer try/except |

## 7. Success Criteria（SC，挂 RTM）

| SC | 判据 | test_id |
|---|---|---|
| **SC1** 默认 no-op byte 等价 | `observe=False` → `make_tracer` 返 NoopTracer;`trace`/`event` 全 no-op、零网络;既有 ask 不变 | `test_noop_tracer` / 既有 `test_graph` |
| **SC2** make_tracer 选择 | observe 开+creds → Langfuse;观off / 无 creds → Noop(离线安全)| `test_make_tracer` |
| **SC3** ask 产 trace | `observe` 开 → `ask()` 调 `tracer.trace`,终态 metadata(归并句/scene/route_type/候选数/result)入 trace | `test_ask_records_trace`（fake tracer）|
| **SC4** Retriever 发 HyDE/子查询 event | `_dense_for` 发 `hyde` passage、`_subqueries_for` 发 `decompose` subqueries（fake tracer 捕获）| `test_retriever_emits_events` |
| **SC5** contextvar 串联 | Retriever event 挂到 ask() 开的当前 trace(同一条)| `test_event_attaches_to_current_trace` |
| **SC6** fail-safe 吞 | Langfuse client 抛 → tracer 不传播、ask 正常返 result(观测不阻断)| `test_tracer_failsafe` |
| **SC7** 真 Langfuse 闭环 | observe+creds → record 不抛、trace 产出 | `test_observe_integration`（gate）|
| **SC8** 只读旁路 | tracer 不改 state/检索/答复;observe 开关下 result 一致 | `test_observe_does_not_alter_result` |

## 8. Boundaries

- **Always**:tracer 只读旁路、绝不改 state/检索/答复/控制流;Langfuse 失败 fail-safe 吞、不阻断查询;默认关 → Noop 零网络
  byte 等价;creds 仅 env 绝不入库;langfuse 懒导入 + 可选 extra;跑改动波及范围测试,合并前全 query 门跑一次。
- **Ask first**:observe 默认值(本切片默认关,已述);加 langfuse 依赖(做可选 extra,默认不装);改检索/生成控制流(不改)。
- **Never**:trace 内容回灌业务逻辑(纯观测);creds 入库;Langfuse 失败抛断查询;默认开(外发外部服务);改 `state.query`/答复。

## 9. 红线（RL）

- **观测只读**:tracer 是旁路,**不改任何业务态/控制流**;开/关 observe,`ask()` 的 `result` 必一致(SC8)。
- **fail-safe 不阻断**:Langfuse 网络/SDK 任何异常**吞掉**,查询照常完成(observe 是增益,非依赖)。
- **零网络默认 + creds 不入库**:默认 Noop 零网络;Langfuse key 仅 env(`LANGFUSE_*`)绝不入库(同 `OPENAI_API_KEY` 范式)。

## 10. Open Questions

1. **trace 粒度**:MVP 单 trace + events;深层 per-stage 嵌套 span 树(检索/重排/生成/复核各一 span,带耗时)留后续。够用待复核。
2. **采样率 / 保留**:本切片全量 trace(observe 开时);生产采样率、PII 脱敏、保留策略归运维(§12)。
3. **langfuse 版本**:`[observe]` extra pin `langfuse>=2`(SDK trace API);真版本待对接(可用性 §15 网关同期)。
