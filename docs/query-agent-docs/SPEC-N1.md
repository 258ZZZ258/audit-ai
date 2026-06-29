# Spec: N1 HyDE 查询改写(假设性法言 → dense 检索)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md **P2 查询理解前端**(backlog #6,N0 后第二块)。
> 把 §3.1 N1 HyDE 从 ❌ 推进到实装:口语问句 → 1–2 句假设性法言条款 → **与原问一同送入 dense 检索通道**,提升术语断层
> 问句(口语描述命中法言条款)的召回。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §3.1 N1 HyDE(L155)/ §3 节点链(L88)/ §1.3-1 取舍(L107)/
> §7.1 引用注入污染兜底(L109/L162)/ §13 V0 第5组 A/B(L491)/ §15-①⑦(L518/L524)。
> **关键现状(研究已确认)**:`retrieve/hybrid.py` `Retriever.retrieve(query)` 内 `emb=self._embed.embed([query])[0]` →
> `emb.dense`(dense)+ `_sparse_for(query, emb)`(§5.4 sparse 接缝);HyDE 改 **dense 向量**。`make_llm_client(cfg,*,model=)`
> 工厂 + `chat_json(system,user)->dict` 接缝 + `EmbeddingClient.embed(list[str])->[Embedding(.dense/.sparse)]` **均已实装**。
> sparse 法言扩展归 **§5.4 dict 桥接**(口语→法言,L174),HyDE **专管 dense** —— 分工干净。
>
> **已决(2026-06-28,AskUserQuestion):** ① **HyDE 默认开**(`hyde` 默认 `True`,对齐设计 §3 节点链「默认 on」+ N0 默认开
> 范式);② **注入点 = Retriever 内 dense 接缝**(镜像 §5.4 `_sparse_for` / §5.5 rerank,**不**走图 N1 节点 / 不改 `state.query`——
> HyDE 只改 dense 向量,绝不污染 classify/route)。
>
> **本切片承诺的假设(请复核;有异即纠)**:
> 1. **HyDE 专管 dense、sparse 留原问**:dense 文本 = `f"{query}\n{passage}"`(§3.1「假设性法言与原始问句一同送入 dense」);
>    sparse 仍由 `_sparse_for`(原问 + §5.4 dict)。**理由**:§7.1 污染兜底 + sparse 法言归 §5.4 dict 桥接(避免编造法言污染
>    精确 sparse 匹配)。
> 2. **「默认开」的离线落地**:默认 `llm_backend=stub`(零网络),HyDE 无规则版兜底(必须 LLM 生成法言)。故 `hyde_llm`
>    **仅 `hyde` 开 + gateway 时建**;**stub/无 key → `hyde_llm=None` → `_dense_for` 返原问 dense(no-op)→ 默认 byte 等价**。
>    「默认开」体现在:配齐 gateway 即真 HyDE。LLM 失败/返空 → **fail-safe 回落原问 dense**(§3.1 N1-fail,绝不阻断)。
> 3. **仅主 `retrieve`(R1/R5)**:`retrieve_enumerate`(R4)/`retrieve_cases`(R3)**不接** HyDE(同 §5.4 sparse 提权范式)。
> 4. **V0 未跑 → 诚实 🟡**:§13 第5组 A/B(hit@10 提升)未跑、真 HyDE 召回收益未验证;真-LLM 生成门控就位、本地无 key
>    skip → N1 记 🟡(待真 gateway 跑绿 + V0 标定后定默认值/配额折算)。`state.rewrites` 字段保留占位(HyDE 文本为检索内部态,
>    不经 graph state,不污染 route)。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **N1 HyDE dense 接缝**:(A)新 `retrieve/hyde.py` —— `HYDE_SYSTEM`/`build_hyde_user`/`parse_passage`/`hyde_dense_text(query, llm)` 纯函数(生成假设性法言 → `f"{query}\n{passage}"`;LLM 抛/返空 → None);(B)`retrieve/hybrid.py` `Retriever` +`_dense_for(query, emb)`(`hyde_llm` 给定 → `embed(hyde_dense_text)` 作 dense,失败 → `emb.dense`;`None` → `emb.dense`)+ `retrieve()` 用 `_dense_for` 替 `emb.dense`(**仅主 retrieve**;enumerate/cases 不动);`Retriever.__init__`/`from_config` +`hyde_llm`(**仅 `hyde` 开 + gateway 建**);(C)`config` +`hyde: bool = True`(env `QUERY_HYDE`)+ `hyde_model: str | None = None`(None→复用 `llm_model`;env `QUERY_HYDE_MODEL`);(D)`PROMPTS.md` §3.1 HyDE prompt;(E)**单元**(纯函数 + `_dense_for` 接缝 + 默认 no-op + fail-safe)+ **真-LLM 生成门控集成**(gate=gateway+`OPENAI_API_KEY`,缺则 skip,绝不联网)。N1 RTM ❌→🟡。 |
| **不做** | **N3 问题分解**(另切片);**改 sparse 通道**(HyDE 只动 dense;sparse 法言归 §5.4 dict);**HyDE 进 R3/R4**(仅主 retrieve R1/R5);**改写 `state.query` / 图 N1 节点**(已决②:Retriever 内接缝,不污染 route);**§13 V0 A/B 实验 / 术语断层率统计 / 配额折算**(V0 未做,默认值待实测——本切片默认开但记 🟡,不 overclaim 召回收益);**Langfuse trace HyDE 文本**(§9.3 观测未做);**桶触发降级**(「仅术语断层桶触发」是 V0 后的二档预案,本切片只做全局 toggle);**改 `embedding_client`/`milvus_io`**(复用,零改)。**§15-①** 网关轻量小模型(HyDE 属 CP-007 轻量调用)/ **§15-⑦** 配额(每查询 +1 轻量调用)—— 待甲方确认,非本切片阻塞(本地 gateway+env key 跑通即闭环;stub 默认 no-op)。 |

## 1. Objective

把查询理解前端 N1 HyDE 从 ❌ 推进到实装:`hyde` 开 + gateway 时,口语问句先由 LLM 改写为 1–2 句**假设性法言条款**,
与原问拼接后 embed 作 **dense 向量**送混合检索(sparse 仍走原问 + §5.4 dict)——缩小「口语描述 ↔ 法言条款」的术语断层、
提升 dense 召回(§1.3-1)。**污染兜底**:即便 HyDE 编出貌似合理的错误法言,最终答案仍只能引用检索上下文中带 `clause_id`
的内容(§7.1),故 HyDE 错误**不污染答案**。

**成功** = `hyde=True` + `llm_backend=gateway` + key → `retrieve()`(R1/R5)dense 用「原问+假设性法言」嵌入;真 LLM 生成
假设性法言闭环(集成断言生成非空法言文本);**默认 stub → `hyde_llm` 不建 → `_dense_for` 返原问 dense → byte 等价**;
LLM 失败/返空 → 回落原问 dense(绝不阻断);**未设 key → 集成 skip**(绝不联网);enumerate/cases/sparse/route 不受影响。
**V0(§13 第5组)未跑 → N1 记 🟡**(召回收益待实测、默认值/配额待定)。

## 2. Tech Stack(增量)

- 复用 `query/`:`retrieve/hybrid.py`(`Retriever` 加 `_dense_for` + `hyde_llm`)、`llm/client.py`(`make_llm_client(cfg,*,model=)`,
  **零改**)、`config.py`(加 2 字段 + 2 env)、`pipeline.index.embedding_client`(`embed`,**零改**)、`pipeline.llm_client`(真
  `chat_json`,**零改**)。
- 新增:`retrieve/hyde.py`(纯函数);`config` 字段 `hyde`/`hyde_model`;`PROMPTS.md` §3.1 条目;`query/tests/test_hyde.py`
  + `test_hyde_integration.py`(真-LLM 门控);扩 `test_query_config`/`test_hybrid_integration`(可选)。
- **零新依赖;默认开但默认 stub 零网络(`hyde_llm` 不建)、单轮/默认 byte 等价;真 key 仅 env 绝不入库。**

## 3. Commands

```bash
# 单元(零网络):HyDE 纯函数 + _dense_for 接缝 + 默认 no-op + fail-safe + 配置
.venv/bin/python -m pytest query/tests/test_hyde.py query/tests/test_query_config.py -q
# 真-LLM 生成门控集成(需 gateway + key;缺 → skip,绝不联网):
QUERY_LLM_BACKEND=gateway OPENAI_API_KEY=*** OPENAI_BASE_URL=<gateway> \
  QUERY_HYDE_MODEL=<轻量模型> \
  .venv/bin/python -m pytest query/tests/test_hyde_integration.py -q
.venv/bin/ruff check .
# worktree 跑测试(无 .venv,复用主 venv):前置
#   PYTHONPATH=<worktree>/{query,pipeline,libs/common,eval} .venv/bin/python -m pytest ...
```

## 4. Project Structure(增量)

```
query/query/retrieve/hyde.py     # 新:HYDE_SYSTEM/build_hyde_user/parse_passage/hyde_dense_text(query, llm)
query/query/retrieve/hybrid.py   # Retriever +_dense_for(query, emb) + __init__/from_config 建 hyde_llm(仅 hyde 开+gateway);retrieve() 用 _dense_for
query/query/config.py            # + hyde: bool = True(QUERY_HYDE)+ hyde_model: str | None = None(QUERY_HYDE_MODEL)
PROMPTS.md                       # + §3.1 HyDE prompt(假设性法言改写;只写法言不作答、不编造字号/条号)
query/tests/
  test_hyde.py                   # 单元:parse_passage / hyde_dense_text(生成/抛→None/空→None)/ _dense_for(no-op/HyDE/fail-safe)
  test_hyde_integration.py       # 真-LLM 生成(gate=gateway+OPENAI_API_KEY;缺→skip):口语→非空假设性法言
  test_query_config.py           # + hyde/hyde_model 默认 + env 覆盖
docs/query-agent-docs/SPEC-N1.md / PLAN-N1.md / TASKS-N1.md
```

## 5. Code Style

沿用接缝 idiom（纯函数 + 默认关/no-op + LLM 失败 fail-safe 回落）。HyDE dense 接缝镜像 `_sparse_for`：

```python
# retrieve/hyde.py —— 纯函数、零栈可测、LLM 失败回落 None(调用方回落原问 dense)
def hyde_dense_text(query: str, llm: LLMClient) -> str | None:
    """口语问句 → 假设性法言,与原问拼接为 dense 检索文本。LLM 抛/返空 → None。"""
    try:
        passage = parse_passage(llm.chat_json(HYDE_SYSTEM, build_hyde_user(query)))
    except Exception:  # noqa: BLE001 — fail-safe:任何 LLM/网络异常 → None → 回落原问 dense
        return None
    return f"{query}\n{passage}" if passage else None   # §3.1 假设性法言与原始问句一同送入 dense
```

```python
# retrieve/hybrid.py —— hyde_llm 仅 hyde 开+gateway 建(镜像 §9.2/§5.4);否则 None → 原问 dense(byte 等价)
def _dense_for(self, query: str, emb) -> list:
    if self._hyde_llm is None:
        return emb.dense                                   # 关/stub → 原问 dense(byte 等价)
    text = hyde_dense_text(query, self._hyde_llm)
    return self._embed.embed([text])[0].dense if text else emb.dense  # 失败 → 回落原问
```

## 6. HyDE 语义(§3.1)

| 项 | 设计 |
|---|---|
| 任务 | 口语问句 → 1–2 句假设性法言条款,与原问**一同送入 dense**(本切片:`f"{query}\n{passage}"` embed 作 dense)|
| sparse | 不动(原问 + §5.4 dict 桥接);HyDE 只改 dense |
| 失败回落 | LLM 抛/返空 → 原问 dense(N1-fail,绝不阻断)|
| 污染兜底 | 错误法言不污染答案——引用 ID 注入(§7.1)保证答案只引检索上下文带 `clause_id` 者;HyDE **不产出引用**|
| 默认值 | `hyde=True`(对齐设计);真 HyDE 仅 gateway 生效;默认 stub → no-op。**on/off 终值待 §13 V0 第5组 A/B**(本切片记 🟡)|

## 7. Success Criteria（SC，挂 RTM）

| SC | 判据 | test_id |
|---|---|---|
| **SC1** HyDE dense 改写 | `hyde_llm` 给定 → `_dense_for` embed「原问+假设性法言」作 dense(fake embed 断言收到拼接文本)| `test_dense_for_hyde` |
| **SC2** 默认 no-op byte 等价 | `hyde_llm=None`(关/stub)→ `_dense_for` 返 `emb.dense`;既有检索全链路不变 | `test_dense_for_noop` + 既有 `test_hybrid_integration` |
| **SC3** fail-safe 不阻断 | LLM 抛/返空 → `hyde_dense_text` None → `_dense_for` 回落 `emb.dense` | `test_hyde_dense_text_failsafe` / `test_dense_for_fallback` |
| **SC4** 真-LLM 生成闭环 | gateway+key → `hyde_dense_text` 生成非空假设性法言(含原问+法言)| `test_hyde_integration`（gate）|
| **SC5** 默认开 + 零网络 | `hyde` 默认 `True`;默认 stub → `hyde_llm` 不建、**零网络**;env `QUERY_HYDE`/`QUERY_HYDE_MODEL` 覆盖 | `test_query_config` / `test_hyde`（无网络）|
| **SC6** 仅主 retrieve | `retrieve_enumerate`/`retrieve_cases` 不调 `_dense_for`(HyDE 不入 R3/R4）| `test_enumerate_cases_no_hyde` |
| **SC7** 红线无臆造 | HyDE 不产出 `clause_id`;错误法言经 §7.1 注入兜底不污染答案 | `test_evidence_guards`（既有不破）|

## 8. Boundaries

- **Always**:HyDE 只改 dense 向量,sparse/route/enumerate/cases 零改;纯函数零栈可测;LLM 失败 fail-safe 回落原问、绝不阻断;
  默认 stub → `hyde_llm` 不建、零网络、byte 等价;跑改动波及范围测试,合并前全 query 模型门跑一次。
- **Ask first**:HyDE 默认开偏离「默认零 LLM」(**已决①** 批准,且默认 stub 实为 no-op);改 sparse 通道;HyDE 进 R3/R4;
  加新依赖;改 `embedding_client`/`milvus_io`。
- **Never**:HyDE 生成/编造 `clause_id`/发文字号(只写假设性法言,§7.1 红线);真 key 入库(仅 env);无 gateway 时联网/阻断
  (回落原问 dense);污染 classify/route(不改 `state.query`);在 V0 未跑时 overclaim HyDE 召回收益(诚实记 🟡)。

## 9. 红线（RL，byte-identical to 设计）

- **§7.1 引用 ID 注入(污染兜底)**:HyDE 编出错误法言**不污染最终答案**——答案只能引用检索上下文中带 `clause_id` 的内容
  (设计 L109/L162)。HyDE **不产出引用**、不改 sparse 精确匹配通道。
- **§3.1 N1-fail**:HyDE 失败回落原句/原问 dense,绝不阻断检索。
- **不污染 route**:HyDE 改 dense 向量,**不改 `state.query`** → classify/route 仍基于原问(已决②:Retriever 内接缝)。

## 10. Open Questions

1. **默认值终定**:`hyde=True` 对齐设计意图,但 on/off 默认值**待 §13 V0 第5组 A/B 实测**(hit@10>5pp+边界无负面→on;仅断层
   桶提升→桶触发配额减半)。本切片默认开 + 记 🟡;V0 后回填。
2. **dense 组合策略**:MVP 取 `embed(query+"\n"+passage)`(原问+法言一同 embed 一次)。备选:`embed(passage)` 纯 HyDE 替换 /
   两向量平均。设计「一同送入」倾向合并,取拼接 embed(最简、确定);V0 可调。
3. **`hyde_model` 真名 / 轻量小模型**:§9.1/§15-① CP-007 轻量调用,真名待甲方网关注册表;默认 None→复用 `llm_model`;
   env `QUERY_HYDE_MODEL`。非阻塞。
