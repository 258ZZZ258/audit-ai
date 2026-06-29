# Plan: N1 HyDE 查询改写(假设性法言 → dense 检索)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-N1.md`(已批准:① HyDE 默认开;② Retriever 内 dense 接缝;
> HyDE 专管 dense、sparse 留原问;默认 stub→no-op byte 等价;LLM 失败 fail-safe 回落原问 dense;V0 未跑→记 🟡)。
> **sparse 通道零改**(法言 sparse 归 §5.4 dict);**`embedding_client`/`milvus_io`/`state.py`/graph 零改**;
> **enumerate/cases 不接 HyDE**(仅主 retrieve R1/R5)。

## 1. 组件与依赖

```
config.py            +hyde: bool = True(env QUERY_HYDE)+ hyde_model: str | None = None(env QUERY_HYDE_MODEL)
        ▲
retrieve/hyde.py     HYDE_SYSTEM / build_hyde_user / parse_passage          [新,纯函数零栈]
        │            hyde_dense_text(query, llm) -> str | None:
        │              try: passage = parse_passage(llm.chat_json(HYDE_SYSTEM, build_hyde_user(query)))
        │              except: return None                                   # fail-safe → 回落原问 dense
        │              return f"{query}\n{passage}" if passage else None     # §3.1 法言+原问一同送 dense
        ▲
retrieve/hybrid.py   Retriever.__init__(... , hyde_llm=None): self._hyde_llm = hyde_llm
        │            from_config: hyde_llm = make_llm_client(qcfg, model=hyde_model or llm_model)
        │                                    if qcfg.hyde and qcfg.llm_backend=="gateway" else None
        │            _dense_for(query, emb): self._hyde_llm None → emb.dense(byte 等价);
        │                                    else hyde_dense_text→embed([text]).dense,失败→emb.dense
        │            retrieve(): dense = self._dense_for(query, emb); search(dense, sparse, ...)
        │                        # retrieve_enumerate / retrieve_cases 不动(仅主 retrieve)
        ▲
PROMPTS.md           + §3.1 HyDE prompt(假设性法言改写;只写法言不作答、不编造字号/条号)
```

**复用**:`make_llm_client(cfg,*,model=)`(REVIEW 轮 add-only,**零改**)、`pipeline.llm_client`(真 `chat_json`+env key,**零改**)、
`EmbeddingClient.embed`(**零改**)、`MilvusIO.search`(**零改**)、`_sparse_for`(§5.4,**零改**)。**零新依赖、默认零网络、默认 byte 等价。**

> **hyde_llm 仅 hyde 开+gateway 建**(镜像 §9.2 复核 / N0 merge 客户端);toggle 关 **或** stub → `None` → `_dense_for` 返原问
> dense(零网络、byte 等价)。**默认 stub → HyDE 默认 no-op**(「默认开」仅在配 gateway 时活)。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `config` +`hyde`/`hyde_model`(独立)
- `QueryConfig` +`hyde: bool = True` + `hyde_model: str | None = None`;`_apply_env` +`QUERY_HYDE`(字符串→bool,对齐
  `merge_context`/`docnum_boost` 范式)+ `QUERY_HYDE_MODEL` 覆盖。既有默认行为零变化(默认 stub → HyDE no-op)。
- **检查点 A**:`test_query_config.py` —— `hyde` 默认 `True`、`hyde_model` 默认 `None`;env 覆盖(`QUERY_HYDE=0`→False、`QUERY_HYDE_MODEL` 设值)。零栈。

### Phase B — `retrieve/hyde.py` 纯函数(独立,核心,可与 A 并行)
- `HYDE_SYSTEM`(口语→1–2 句假设性法言,**只写法言、不作答、不编造字号/条号**)+ `build_hyde_user(query)` +
  `parse_passage(resp)->str|None`(取 `passage`,非串/空→None)+ `hyde_dense_text(query, llm)->str|None`(生成→`f"{query}\n{passage}"`;
  LLM 抛/返空→None)。
- **检查点 B**:`test_hyde.py`(零栈零网络)—— `parse_passage` 畸形→None;`hyde_dense_text`:fake llm 返 passage→`原问+法言`、
  fake llm 抛→None、返空→None;`build_hyde_user` 含原问;`HYDE_SYSTEM` 含「不编造」「只写」。

### Phase C — `PROMPTS.md` 记 §3.1 HyDE prompt(独立,doc)
- 录 `HYDE_SYSTEM`/`build_hyde_user`(契约约定,代码内联镜像,同 L2/E2/§9.2/§3.4 范式);标注**只写假设性法言、不作答、
  不生成 `clause_id`/发文字号**(§7.1 污染兜底)+ 失败 fail-safe 回落原问 dense。
- **检查点 C**:人工核对 `PROMPTS.md` 与 `hyde.py` prompt 文本一致。

### Phase D — `retrieve/hybrid.py` `_dense_for` + `hyde_llm` 接线(依赖 A+B)
- `Retriever.__init__` +`hyde_llm=None` 参 + 存 `self._hyde_llm`;`from_config` 建 `hyde_llm`(仅 `hyde` 开+gateway);
  `_dense_for(query, emb)`;`retrieve()` 用 `dense = self._dense_for(query, emb)` 替 `emb.dense`(**仅 retrieve;enumerate/cases 不动**)。
- **检查点 D**:`test_hyde.py`(扩,fake embed/fake hyde_llm 构 Retriever,零栈)—— ① `hyde_llm=None` → `_dense_for` 返 `emb.dense`
  (embed 仅原问);② `hyde_llm` 返 passage → `_dense_for` embed「原问+法言」并返其 dense;③ `hyde_llm` 抛 → 回落 `emb.dense`;
  ④ `from_config` 仅 hyde 开+gateway 建 `hyde_llm`(monkeypatch `make_llm_client` sentinel);⑤ enumerate/cases 不调 `_dense_for`。

### Phase E — 真-LLM 生成门控集成(依赖 B;gate=gateway+`OPENAI_API_KEY`)
- `test_hyde_integration.py`:`hyde_dense_text(口语问句, 真 llm)` → 非空、含原问 + 一段法言文本(断言生成成功、格式合理);
  **未设 `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。聚焦 HyDE 生成层(无需全栈/Milvus)。
- **检查点 E**:集成绿(gate 满足时);真 HyDE 生成闭环成立。**本地无 key → 诚实记 🟡**(实装+单测+门控就位),待真 gateway 跑绿。

### Phase F — 收尾(devlog/GAP/RTM)+ 全仓门
- `query_devlog.md` 记决策/踩坑;`GAP.md`(N1 ❌→🟡、§1.3 TO-1 推进);**`RTM.md`**(N1/N1-fail/N1-decision 挂 SC+test_id,
  覆盖摘要重算);`docs/devlog.md` 加阶段。
- **检查点 F**:全 query 套件(非模型门)+ ruff 全绿 + DAG 无环;**提交前模型门控全量跑一次**(无 key 时 HyDE 集成 skip,不漏回归)。

## 3. 并行 vs 串行
A(config)∥ B(hyde.py 核心)∥ C(PROMPTS)→ D(hybrid 接线,依赖 A+B)→ E(集成,依赖 B,真 gateway)→ F(收尾+全仓门)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **默认回归**(HyDE 误改默认 dense)| 默认 stub → `hyde_llm` 不建 → `_dense_for` 返 `emb.dense`;`test_dense_for_noop` + 既有 `test_hybrid_integration` 守 byte 等价 |
| R2 | **HyDE 默认开偏离「默认零 LLM」** | 已决①批准;默认 stub → no-op 零网络;HyDE 仅 gateway 生效;`test_hyde` 断言 stub 路径不调网络 |
| R3 | **真 LLM 失败/超时阻断检索** | `hyde_dense_text` try/except→None → `_dense_for` 回落原问 dense,**绝不阻断**;`test_hyde_dense_text_failsafe` 守 |
| R4 | **HyDE 错误法言污染答案** | HyDE 只改 dense 向量、**不产出 `clause_id`**;§7.1 引用注入兜底(答案只引检索上下文带 `clause_id` 者);`test_evidence_guards` 既有不破 |
| R5 | **污染 sparse 精确匹配** | HyDE **只改 dense**,sparse 走 `_sparse_for`(原问+§5.4 dict)零改;`test_dense_for_*` 断言 sparse 不变 |
| R6 | **污染 classify/route** | HyDE 在 Retriever 内、**不改 `state.query`**;route 仍基于原问(已决②);graph/state 零改 |
| R7 | **HyDE 误入 R3/R4** | 仅 `retrieve()` 用 `_dense_for`;`retrieve_enumerate`/`retrieve_cases` 零改;`test_enumerate_cases_no_hyde` 守 |
| R8 | **额外 embed 调用**(query + query+passage 两次)| HyDE 固有(必 embed 假设文档);仅 hyde 开+gateway 时多一次;关/stub 单次(零增量)|
| R9 | **key 泄漏** | key 仅 env `OPENAI_API_KEY` 绝不入库;集成无 key→skip(不调)|
| R10 | **V0 未跑 overclaim 召回** | 诚实记 🟡(召回收益待 §13 第5组 A/B);默认值待实测;devlog/RTM 标注 |

## 5. 可追溯(SPEC §7 SC → 组件 / 守护)
| SC | 组件 | 守护 |
|---|---|---|
| SC1 HyDE dense 改写 | `_dense_for` + `hyde_dense_text` | `test_dense_for_hyde`(fake embed 收拼接文本)|
| SC2 默认 no-op byte 等价 | `_dense_for`(`hyde_llm None`→`emb.dense`)| `test_dense_for_noop` + 既有 `test_hybrid_integration` |
| SC3 fail-safe 不阻断 | `hyde_dense_text` try/except + `_dense_for` 回落 | `test_hyde_dense_text_failsafe` / `test_dense_for_fallback` |
| SC4 真-LLM 生成闭环 | `hyde_dense_text` + 真 `hyde_llm` | `test_hyde_integration`(gate)|
| SC5 默认开 + 零网络 | `config` 默认 True + `hyde_llm` 仅 gateway 建 | `test_query_config` / `test_hyde`(无网络)|
| SC6 仅主 retrieve | `retrieve` 用 `_dense_for`;enumerate/cases 不动 | `test_enumerate_cases_no_hyde` |
| SC7 红线无臆造 | HyDE 不产出 `clause_id` + §7.1 注入兜底 | `test_evidence_guards`(既有不破)|

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–F)· [x] 并行 · [x] 风险(含默认零回归 + 零网络 + fail-safe + 红线无臆造 + 仅主 retrieve)· [x] 可追溯(SC1–SC7)
- [ ] **人工复核批准**
