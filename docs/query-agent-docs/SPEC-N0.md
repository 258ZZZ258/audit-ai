# Spec: N0 多轮上下文归并 + R7 澄清闭环

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md **P2 查询理解前端**(backlog #6)+ 闭合 R7 已知缺口
> (§6.7「用户回答后回到 N0 重新归并」)。把 `QueryState.history` 从占位推进到**真消费**:多轮指代消解 / 省略补全 +
> R7 澄清答归并回原问。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §3.4 N0 多轮归并(L180)/ §3 前端节点链(L86)/ §6.7 R7 澄清(L337)/
> §0.3 不进 agentic 循环(L178)/ §7.1 引用 ID 注入红线(L109)。
> **关键现状(研究已确认)**:`QueryState.history: list[dict]` 字段**已在状态契约预留**(占位、单轮直通);
> `graph.py` 为 `START → understand → 条件路由 → 终端`,**understand 之前无 N0 节点**;`ask(query)` 单轮、空 history;
> R7 `_clarify` 节点产出澄清问句块即 END、**无回环**;LLM 接缝 `chat_json(system,user)->dict` + `make_llm_client(cfg,*,model=)`
> 工厂 + StubLLMClient(零网络确定性、R1 引用专用)**均已实装**(R5/REVIEW 轮)。
>
> **已决(2026-06-28,AskUserQuestion):** ① **N0 LLM 为主、归并默认开**(`merge_context` 默认 `True`;§3.4 指代消解 /
> 省略补全本质是 LLM 友好任务,用户明确接受其代价:违本仓「默认零 LLM」、每轮多一次网关调用、无 key 时降级、默认非 byte 等价);
> ② **多轮入口 = `ask(query, history=None)` 无状态 API + CLI `--history-json`**(调用方维护会话;**不做**交互式 `chat` REPL)。
>
> **本切片承诺的假设(请复核;有异即纠)**:
> 1. **R7 闭环 = 跨请求无状态**:clarify 返回 → 调用方带 history 重问 → 下一请求进 `n0_merge` 节点重新归并。**不建图内环**
>    (LangGraph cycle),守 §0.3「不进 plan→retrieve→reason→re-retrieve 的 agentic 循环」。"回到 N0" = 下一请求的入口节点。
> 2. **「LLM 为主」的离线落地**:默认 `llm_backend=stub`(零网络)。故 **LLM 为主路径仅 gateway 配置时生效**;**stub/无 key →
>    规则版确定性归并**(= 用户接受的"降级"),且**真 LLM 调用失败/返空 → fail-safe 回落规则版/原句**(绝不阻断、绝不臆造)。
> 3. **单轮零回归**:`history` 为空 → N0 **no-op**(返回原 `query`)→ 既有单轮全链路 **byte 等价**,440+ 既有测试不受影响。
>    "默认非 byte 等价"仅指**多轮带 history**时(本就是新行为)。
> 4. **N0 输出写回 `state.query`**(归并后的自足问句),下游 `understand`/检索读 `state.query` **零改动**;原句多轮时可从
>    `history` 复得。**不新增状态字段**(守 `state.py`「加节点永不改状态契约」),只消费既有 `history` + 改写 `query`。
> 5. **history 轮次形状** = `{"role": "user"|"assistant", "content": str, "route_type"?: str}`;assistant 轮可带
>    `route_type`(供 R7 闭环识别上一轮是否 `clarify`)。坏/缺字段 → 该轮忽略(consumed-when-present,fail-safe)。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **N0 多轮上下文归并节点 + R7 澄清闭环**:(A)新 `understand/merge.py` —— `merge_context(query, history, *, llm)` 纯函数:**规则版确定性核**(`_rule_merge`:R7 澄清答归并 + 代词/省略顺承)+ **LLM 归并接缝**(`llm` 给定 → `chat_json(MERGE_SYSTEM, build_merge_user)` → 解析 `{"merged_query": str}`;失败/空 → 回落规则版/原句);(B)`graph.py` 加 `n0_merge` 节点接在 `START → n0_merge → understand`,产出 `{"query": merged}`(归并)或 `{}`(no-op);merge 客户端**仅 `merge_context` 开 + `llm_backend=gateway` 时建**(镜像 §9.2 复核「仅 toggle 开时建」),否则 `None` → 规则版;(C)`ask(query, history=None)` 无状态入口,`history` 注入 `QueryState`;(D)`config` +`merge_context: bool = True`(env `QUERY_MERGE_CONTEXT`)+ `merge_model: str | None = None`(None → 复用 `llm_model`;env `QUERY_MERGE_MODEL`);(E)CLI `ask` +`--history-json`(JSON 数组 → history);(F)`PROMPTS.md` 记 §3.4 N0 归并 prompt;(G)**单元**(规则版 R7 闭环 / 顺承 / no-op / fail-safe)+ **真-LLM 闭环集成测试**(gate=gateway+`OPENAI_API_KEY`,缺则 skip,绝不联网)。R7 闭环 / N0 RTM 🟡→部分✅。 |
| **不做** | **N1 HyDE / N3 问题分解**(同属前端但另切片,§15-①⑦/独立);**图内 LangGraph 环 / agentic 多跳**(R7 闭环走跨请求,守 §0.3);**交互式 `chat` REPL**(已决②:仅 API + `--history-json`);**会话持久化 / 服务端 session**(无状态,调用方维护 history);**`dict_intent_routes` 路由分类器**(N4 仍规则版);**指代消解的完整 NLP**(规则版只做确定性顺承 + R7 闭环,深度指代靠 gateway 真 LLM,无 gateway 不强求);**改既有 `understand/classify`·`router`·下游检索/生成**(N0 只前置改写 `query`,下游零改);**`StubLLMClient` 改造**(R1 引用专用,不混入 merge;规则版归并不经 stub)。**§15-①** 网关轻量小模型(N0 属 CP-007 轻量调用)/ **§12** 配额预留 —— 待甲方确认,非本切片阻塞(本地 gateway+env key 跑通即闭环;无则规则版兜)。 |

## 1. Objective

把查询理解前端入口节点 **N0 多轮上下文归并**从占位推进到**真消费 `history`**,并**闭合 R7 已知缺口**:

- **指代消解 / 省略补全**(§3.4):多轮中「它 / 该制度 / 上面那条」等指代、省略的制度名 / 业务域,结合会话上下文补全为
  **自足问句**送下游检索 —— 解决 TO-1「查询理解前端替代裸检索」中 N0 的 ❌ 缺口。
- **R7 澄清闭环**(§6.7):R7 产出单问澄清(纯对话、不出复选框,§3.4 硬约束)→ 用户回答 → **下一请求经 N0 把澄清答归并回
  原问** → 重新路由 → 给出真实答复。闭合「澄清后回 N0 重新归并」(GAP / RTM 标 R7🟡「回 N0 缺」)。

**成功** = 带 history 的多轮问句经 `n0_merge` 归并为自足问句 → 下游正确路由 / 检索;R7 澄清答 + 原问归并后路由到真实答路径;
**单轮(空 history)byte 等价零回归**;`merge_context` 默认开(LLM 为主),**gateway 配置时真 LLM 归并、stub/失败时规则版兜**
(确定性、零网络、绝不阻断、绝不臆造引用——守 §7.1 红线:即便 LLM 编出错误法言,最终答案仍只能引用检索上下文中带
`clause_id` 的内容)。

## 2. Tech Stack(增量)

- 复用 `query/`:`graph.py`(加节点 + 入口签名)、`state.py`(**零改**,消费既有 `history` / 改写 `query`)、
  `llm/client.py`(`make_llm_client(cfg, *, model=)` 工厂,**零改**)、`config.py`(加 2 字段 + 2 env)、`cli.py`(加 `--history-json`)。
- 复用 `pipeline.llm_client`(真 OpenAI 兼容 `chat_json`,key 走 env;**零改**)。
- 新增:`understand/merge.py`(规则版 + LLM 接缝纯函数);`config` 字段 `merge_context` / `merge_model`;`PROMPTS.md` §3.4 条目;
  `query/tests/test_merge.py`(规则版单元)+ `test_graph` 增 N0 用例 + `test_query_config` 增字段 + `test_merge_integration.py`(真-LLM 闭环 gate)。
- **零新依赖;默认开但默认 stub 零网络(规则版确定性);真 LLM key 仅 env 绝不入库;单轮 no-op byte 等价。**

## 3. Commands

```bash
# 单元(零网络):规则版归并 + R7 闭环 + no-op + fail-safe + 配置 + 图装配
.venv/bin/python -m pytest query/tests/test_merge.py query/tests/test_graph.py \
  query/tests/test_query_config.py query/tests/test_query_cli.py -q
# 真-LLM 闭环集成(需 OpenAI 兼容 gateway + key;缺 → skip,绝不联网):
QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
  QUERY_MERGE_MODEL=<轻量模型> \
  .venv/bin/python -m pytest query/tests/test_merge_integration.py -q
# CLI 多轮(stub 规则版,零网络):R7 闭环手验
.venv/bin/python -m query.cli ask "现行版本" --history-json \
  '[{"role":"user","content":"合同管理办法什么时候改的"},{"role":"assistant","content":"您问现行版本还是某历史版本?","route_type":"clarify"}]'
.venv/bin/ruff check .
# worktree 跑测试(无 .venv,复用主 venv):前置
#   PYTHONPATH=<worktree>/{query,pipeline,libs/common,eval} .venv/bin/python -m pytest ...
```

## 4. Project Structure(增量)

```
query/query/understand/merge.py   # 新:merge_context(query, history, *, llm) + _rule_merge + MERGE_SYSTEM/build_merge_user/parse_merged
query/query/graph.py              # + _n0_merge 节点;START→n0_merge→understand;__init__ 建 _merge_llm(仅 toggle 开+gateway);ask(query, history=None)
query/query/state.py              # 零改(消费 history、改写 query)
query/query/config.py             # + merge_context: bool = True(QUERY_MERGE_CONTEXT)+ merge_model: str | None = None(QUERY_MERGE_MODEL)
query/query/cli.py                # ask + --history-json: str(JSON 数组 → list[dict] history)
PROMPTS.md                        # + §3.4 N0 多轮归并 prompt(自足问句改写;只改写不作答、不编造)
query/tests/
  test_merge.py                   # 单元:R7 闭环归并 / 代词顺承 / no-op(空 history)/ fail-safe(LLM 抛→规则版)/ 坏轮忽略
  test_merge_integration.py       # 真-LLM 闭环(gate=gateway+OPENAI_API_KEY;缺→skip):多轮指代真归并
  test_graph.py                   # + n0_merge 装配:多轮归并→正确路由;单轮 no-op
  test_query_config.py            # + merge_context/merge_model 默认 + env 覆盖
  test_query_cli.py               # + --history-json 解析 → 多轮
docs/query-agent-docs/SPEC-N0.md / PLAN-N0.md / TASKS-N0.md
```

## 5. Code Style

沿用接缝 idiom（纯函数 + 规则版默认 + LLM 接缝 + fail-safe 回落）。N0 归并核心：

```python
# understand/merge.py —— 纯函数、零栈可测、规则版确定性、LLM 失败 fail-safe 回落原句
def merge_context(query: str, history: list[dict], *, llm: LLMClient | None = None) -> str:
    """多轮归并为自足问句。history 空 → 原句(no-op)。llm 给定 → 真 LLM 改写（失败回落规则版）；
    None → 规则版。绝不阻断、绝不臆造（只改写问句，不作答、不生成引用）。"""
    if not history:
        return query                              # 单轮 no-op → byte 等价
    if llm is not None:
        try:
            merged = parse_merged(llm.chat_json(MERGE_SYSTEM, build_merge_user(query, history)))
            if merged:
                return merged                     # LLM 为主
        except Exception:
            pass                                  # fail-safe → 规则版
    return _rule_merge(query, history) or query   # 规则版兜 / 无可归并 → 原句
```

```python
# graph.py —— merge 客户端仅 toggle 开 + gateway 时建（镜像 §9.2 复核），否则 None → 规则版
self._merge_llm = (
    make_llm_client(qcfg, model=qcfg.merge_model or qcfg.llm_model)
    if qcfg.merge_context and qcfg.llm_backend == "gateway" else None
)
def _n0_merge(self, state: QueryState) -> dict:
    merged = merge_context(state.query, state.history, llm=self._merge_llm)
    return {"query": merged} if merged != state.query else {}   # 仅变更时写回
```

## 6. N0 归并语义（规则版确定性核 —— 默认 / 离线 / fail-safe 基准行为）

> 真 LLM（gateway）做完整指代消解；规则版是**确定性、可测、离线**的基准 + 兜底。两者输出同一形状（自足问句字符串）。

| 规则（有序，首个命中即定） | 触发 | 归并 |
|---|---|---|
| **R7 澄清闭环** | 末轮 = assistant 且 `route_type == "clarify"` | `merged = f"{上一 user 问} {当前 query}"`（原问 + 澄清答；末轮前的 user 轮即原问） |
| **代词 / 省略顺承** | 当前 query 含指代标记（它 / 该 / 这条 / 那条 / 上面那个 / 这个 / 那个 / 呢）**或** 过短 | `merged = f"{最近 user 问} {当前 query}"`（继承上轮主题） |
| **无可归并** | 以上均不命中 | `None` → 调用方返回原句（no-op） |

- **指代标记 / 过短阈值**复用 / 对齐 `router._PRONOUN_ONLY` + `_MIN_LEN`（避免两处漂移）。
- 归并后 `query` 经 `understand`（classify/route）重判：如 R7 原问「…什么时候改的」+ 澄清答 → 仍命中 CHANGE；顺承「那差旅呢」+
  上轮「报销保存几个月」→ 检索得到主题上下文。
- **坏 / 缺字段轮忽略**（consumed-when-present）：`role`/`content` 缺 → 跳过该轮；history 全坏 → 视同空 → no-op。

## 7. Success Criteria（SC，挂 RTM）

| SC | 判据 | test_id |
|---|---|---|
| **SC1** R7 澄清闭环 | 末轮 clarify + 当前澄清答 → 归并 = 原问 + 答；归并句重路由到真实答路径（非再 CLARIFY） | `test_merge_r7_closure` / `test_graph` n0 用例 |
| **SC2** 代词 / 省略顺承 | 含指代标记 / 过短的跟问 + 上轮主题 → 归并继承主题 | `test_merge_followup` |
| **SC3** 单轮 no-op | 空 history → 返回原句；既有单轮 `ask` 全链路 byte 等价（既有测试全绿） | `test_merge_noop` / 既有 `test_graph`·`test_r1_integration` |
| **SC4** LLM 为主 + fail-safe | gateway+key：真 LLM 归并生效（集成断言指代被消解）；LLM 抛 / 返空 → 回落规则版（不阻断） | `test_merge_integration`（gate）/ `test_merge_llm_failsafe` |
| **SC5** 默认开 + 零网络 | `merge_context` 默认 `True`；默认 `llm_backend=stub` → 规则版、**零网络调用**；env `QUERY_MERGE_CONTEXT`/`QUERY_MERGE_MODEL` 覆盖 | `test_query_config` / `test_merge`（无网络断言） |
| **SC6** 入口契约 | `ask(query, history=None)` 注入 `QueryState.history`;CLI `--history-json` 解析 list[dict] | `test_query_cli` |
| **SC7** 红线无臆造 | N0 只改写问句、不作答、不生成 `clause_id`；归并后引用仍只取检索上下文带 `clause_id` 者（§7.1） | `test_evidence_guards`（既有，回归不破） |

## 8. Boundaries

- **Always**:N0 只前置改写 `query`，下游零改;规则版纯函数零栈可测;LLM 失败 fail-safe 回落、绝不阻断;单轮 no-op byte 等价;
  跑改动波及范围测试（merge/graph/config/cli + 受影响集成），合并前全 query 模型门跑一次。
- **Ask first**:改状态契约 `state.py`（本切片承诺不改）;N0 用 LLM 默认开偏离本仓「默认零 LLM」（**已决①** 批准）;
  加任何新依赖;改 `understand/classify`·`router` 既有逻辑。
- **Never**:N0 生成 / 编造 `clause_id` 或发文字号（只改写问句，§7.1 红线）;真 key 入库（仅 env）;无 gateway 时联网下载 /
  阻断（规则版兜）;引入图内 agentic 循环（§0.3）;裸答 / 替用户作澄清判断（R7 仍由用户回答）。

## 9. 红线（RL，byte-identical to 设计）

- **§7.1 引用 ID 注入**:N0 改写问句**不污染最终答案**——即便（gateway）LLM 在归并时编出貌似合理的错误法言，最终答案仍只能
  引用检索上下文中带 `clause_id` 的内容（设计 L109/L162「污染兜底」）。N0 **不产出引用**。
- **§3.4 纯 chatbox 硬约束**:R7 澄清走纯对话，N0 / R7 **不渲染任何条件复选框**（甲方明确否决）。
- **§0.3 不进 agentic 循环**:N0 归并是**一次性**前置改写;R7 闭环靠**跨请求**重入,非图内 plan→retrieve→reason 迭代。

## 10. Open Questions

1. **`merge_model` 真名 / 轻量小模型**:§9.1 模型矩阵 N0 属 CP-007「轻量调用」,真名待甲方网关注册表（§15-①）。本切片默认
   `None` → 复用主答 `llm_model`;env `QUERY_MERGE_MODEL` 可指定。**非阻塞**（本地 gateway 跑通即闭环）。
2. **规则版顺承的「主题」粒度**:MVP 取「最近 user 问整句」拼接（确定性、提升召回）;更细的名词短语抽取 / 指代替换留真 LLM
   或后续。是否够用待复核。
3. **history 由谁维护**:无状态 API → 调用方（CLI/web/前端）维护并回传。Web 工作台接线留后续（本切片只到 API + CLI）。
