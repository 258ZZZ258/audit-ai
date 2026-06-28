# Plan: N0 多轮上下文归并 + R7 澄清闭环 —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-N0.md`(已批准:① N0 LLM 为主、`merge_context` 默认开;
> ② 入口 `ask(query, history=None)` + CLI `--history-json`;R7 闭环=跨请求无状态;输出写回 `state.query`、不改状态契约;
> 单轮 no-op byte 等价)。
> **状态契约 `state.py` 零改**(消费既有 `history`、改写 `query`);**下游 `understand`/检索/生成零改**(N0 只前置改写问句);
> 默认 `llm_backend=stub` → 规则版确定性归并(零网络);merge 客户端**仅 `merge_context` 开 + gateway 时建**。

## 1. 组件与依赖

```
config.py            +merge_context: bool = True(env QUERY_MERGE_CONTEXT)
        ▲            +merge_model: str | None = None(env QUERY_MERGE_MODEL;None→复用 llm_model)
        │
understand/merge.py  merge_context(query, history, *, llm) -> str         [新,纯函数零栈]
        │              ├─ not history → query                               # no-op(单轮 byte 等价)
        │              ├─ llm 给定 → parse_merged(llm.chat_json(MERGE_SYSTEM, build_merge_user))  # LLM 为主
        │              │            except/空 → 回落规则版                   # fail-safe
        │              └─ _rule_merge(query, history) or query              # R7 闭环 + 代词/省略顺承
        ▲
graph.py             __init__: self._merge_llm = make_llm_client(qcfg, model=qcfg.merge_model or qcfg.llm_model)
        │                                          if qcfg.merge_context and qcfg.llm_backend=="gateway" else None
        │             _n0_merge(state): merged = merge_context(state.query, state.history, llm=self._merge_llm)
        │                               return {"query": merged} if merged != state.query else {}
        │             _build: START → n0_merge → understand → 条件路由(既有)
        │             ask(query, history=None): invoke(QueryState(query=query, history=history or []))
        ▲
cli.py               ask + --history-json: str(JSON 数组 → list[dict] → ask(query, history))
PROMPTS.md           + §3.4 N0 多轮归并 prompt(自足问句改写;只改写不作答、不编造 clause_id)
```

**复用**:`make_llm_client(cfg, *, model=)`(REVIEW 轮已实装 add-only model 覆盖,**零改**)、`pipeline.llm_client`
(真 `chat_json` + env key,**零改**)、`router._PRONOUN_ONLY`/`_MIN_LEN`(指代标记/过短阈值对齐,避免漂移)、`QueryState`
(零改)。**零新依赖、默认零网络、单轮 byte 等价。**

> **merge 客户端独立于复核/主答**:gateway 时 `_merge_llm` 用 `merge_model`(默认复用 `llm_model`);toggle 关 **或** stub →
> `_merge_llm=None` → `merge_context` 走规则版(零网络、确定性)。**单轮(空 history)无论后端 → no-op → byte 等价。**

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `config` +`merge_context`/`merge_model`(独立)
- `QueryConfig` +`merge_context: bool = True` + `merge_model: str | None = None`;`_apply_env` +`QUERY_MERGE_CONTEXT`(bool 解析,
  同既有 `docnum_boost` 字符串→bool 范式)+ `QUERY_MERGE_MODEL` 覆盖。
- **检查点 A**:`test_query_config.py` —— `merge_context` 默认 `True`、`merge_model` 默认 `None`;env 覆盖(`QUERY_MERGE_CONTEXT=0`→False、`QUERY_MERGE_MODEL` 设值)。零栈。

### Phase B — `understand/merge.py` 规则版核 + LLM 接缝(独立,核心,可与 A 并行)
- `_rule_merge(query, history)`:R7 闭环(末轮 assistant+`route_type=="clarify"` → `f"{上一 user 问} {query}"`)→ 代词/省略顺承
  (含 `_PRONOUN_ONLY` 标记或 `len<_MIN_LEN` → `f"{最近 user 问} {query}"`)→ 否则 `None`。坏/缺 `role`/`content` 轮忽略。
- `MERGE_SYSTEM` + `build_merge_user(query, history)` + `parse_merged(resp)->str|None`(取 `merged_query`,非串/空→None)。
- `merge_context(query, history, *, llm=None)`:no-op / LLM(fail-safe)/ 规则版兜(见 §1)。
- **检查点 B**:`test_merge.py`(零栈零网络)—— R7 闭环归并 / 代词顺承 / no-op(空 history)/ fail-safe(fake llm 抛→规则版)/
  LLM 正常(fake llm 返 `{"merged_query":...}`→采纳)/ 坏轮忽略 / `parse_merged` 畸形→None。

### Phase C — `PROMPTS.md` 记 §3.4 N0 归并 prompt(独立,doc)
- 录 `MERGE_SYSTEM`/`build_merge_user` 的归并 prompt(契约约定,代码内联镜像,同 L2/E2/§9.2 范式);标注**只改写问句、不作答、
  不生成 `clause_id`/发文字号**(§7.1 红线)+ 失败 fail-safe 回落。
- **检查点 C**:人工核对 `PROMPTS.md` 与 `merge.py` prompt 文本一致。

### Phase D — `graph.py` `_n0_merge` 节点 + `ask(history)` 接线(依赖 A+B)
- `__init__` 建 `self._merge_llm`(仅 `merge_context` 开 + gateway);`_n0_merge` 节点;`_build` 加 `START→n0_merge→understand`
  (原 `START→understand` 改);`ask(query, history=None)` 注入 `QueryState.history`。
- **检查点 D**:`test_graph.py`(扩,零栈)—— ① 多轮 R7 闭环:`ask(澄清答, history=[原问,clarify])` → 归并句重路由到真实答路径
  (非再 CLARIFY);② 代词顺承多轮 → 归并继承主题;③ **单轮 no-op**:`ask(q)` 空 history → `_n0_merge` 返 `{}`、既有路由用例全绿;
  ④ toggle 关(`merge_context=False`)+ gateway → `_merge_llm=None`(不建客户端、零网络)。复用既有 fake retriever/monkeypatch 范式。

### Phase E — CLI `--history-json`(依赖 D 的 `ask` 签名)
- `ask` 命令 +`--history-json: str | None`;`json.loads` → list[dict] 传 `ask(query, history)`;畸形 JSON → 友好报错(非栈崩)。
- **检查点 E**:`test_query_cli.py`(扩,typer CliRunner,monkeypatch `QueryAgent.from_config`)—— `--history-json` 解析 → `ask`
  收到 history;无 `--history-json` → 单轮(history 空)。零栈。

### Phase F — 真-LLM 闭环集成(依赖 D;gate=gateway+`OPENAI_API_KEY`)
- `test_merge_integration.py`:`merge_context=True` + `llm_backend=gateway` + 真 `merge_model` → 多轮指代(如「它呢」接上轮制度名)
  **真归并为自足问句**(断言 LLM 输出含上轮主题、不含裸指代);**未设 `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。
  聚焦 `merge_context` + 真模型(无需全栈,纯归并层)。
- **检查点 F**:集成绿(gate 满足时);N0 真-LLM 归并闭环成立。**本地无 key → 诚实记 🟡**(实装+单测+门控就位),待真 gateway 跑绿翻✅。

### Phase G — 收尾(devlog/GAP/RTM)+ 全仓门
- `query_devlog.md` 记决策/踩坑;`GAP.md`(N0 ❌→部分✅、R7 🟡→闭环✅、§1.3 TO-1 推进);**`RTM.md`**(N0/R7/§3.4 挂 SC+test_id,
  覆盖摘要重算);`docs/devlog.md` 加阶段。
- **检查点 G**:全 query 套件(非模型门)+ ruff 全绿 + DAG 无环;**提交前模型门控全量跑一次**(无 key 时 merge 集成 skip,不漏回归)。

## 3. 并行 vs 串行
A(config)∥ B(merge.py 核心)∥ C(PROMPTS)→ D(graph 接线,依赖 A+B)→ E(CLI,依赖 D)∥ F(集成,依赖 D,真 gateway)→ G(收尾+全仓门)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **单轮回归**(N0 误改单轮 query)| 空 history → `merge_context` 返原句、`_n0_merge` 返 `{}`;`test_merge_noop` + 既有 `test_graph`/`test_r1_integration` 守 byte 等价 |
| R2 | **N0 默认开偏离「默认零 LLM」** | 已决①批准;默认 `llm_backend=stub` → 规则版**零网络**;LLM 仅 gateway 生效;`test_merge` 断言 stub 路径不调网络 |
| R3 | **真 LLM 失败/超时阻断查询** | `merge_context` try/except → fail-safe 回落规则版/原句,**绝不阻断**;`test_merge_llm_failsafe`(fake llm 抛)守 |
| R4 | **N0 臆造引用/裸答**(LLM 编法言)| N0 **只改写问句、不产出 `clause_id`**;§7.1 引用注入兜底(最终答案只引检索上下文带 `clause_id` 者);`test_evidence_guards` 既有不破 |
| R5 | **改状态契约**(SPEC 承诺不改)| 只消费 `history`、改写 `query`;`state.py` 零改;检查点 D 不新增字段 |
| R6 | **R7 误判图内环** | R7 闭环走**跨请求**(下一请求入 `n0_merge`),非 LangGraph cycle;守 §0.3;检查点 D 用两次 `ask` 模拟 |
| R7 | **指代标记两处漂移**(router vs merge)| `merge.py` 复用/对齐 `router._PRONOUN_ONLY`/`_MIN_LEN`;不另起黑名单 |
| R8 | **history 坏数据崩**(前端传脏)| 坏/缺 `role`/`content` 轮忽略(consumed-when-present);CLI 畸形 JSON 友好报错;`test_merge` 坏轮用例守 |
| R9 | **key 泄漏** | key 仅 env `OPENAI_API_KEY` 绝不入库;集成无 key→skip(不调) |
| R10 | merge 客户端**关时仍建**(无谓网络)| `__init__` `if merge_context and gateway` 才建;检查点 D 断言关时 `_merge_llm is None` |

## 5. 可追溯(SPEC §7 SC → 组件 / 守护)
| SC | 组件 | 守护 |
|---|---|---|
| SC1 R7 澄清闭环 | `_rule_merge` R7 分支 + `_n0_merge` + 跨请求 | `test_merge_r7_closure` / `test_graph` n0 用例 |
| SC2 代词/省略顺承 | `_rule_merge` 顺承分支 | `test_merge_followup` |
| SC3 单轮 no-op byte 等价 | `merge_context` 空 history 短路 + `_n0_merge` 返 `{}` | `test_merge_noop` + 既有全链路 |
| SC4 LLM 为主 + fail-safe | `merge_context` LLM 分支 + try/except + `_merge_llm`(gateway)| `test_merge_integration`(gate)/ `test_merge_llm_failsafe` |
| SC5 默认开 + 零网络 | `config` 默认 True + `_merge_llm` 仅 gateway 建 | `test_query_config` / `test_merge`(无网络)|
| SC6 入口契约 | `ask(query, history=None)` + CLI `--history-json` | `test_query_cli` |
| SC7 红线无臆造 | N0 不产出 `clause_id` + §7.1 注入兜底 | `test_evidence_guards`(既有不破)|

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–G)· [x] 并行 · [x] 风险(含单轮零回归 + 默认零网络 + fail-safe + 红线无臆造)· [x] 可追溯(SC1–SC7)
- [ ] **人工复核批准**
