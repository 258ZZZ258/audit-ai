# Plan: §5.5 重排(bge-reranker)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-RERANK.md`(已批准:Milvus rerank-hop、仅主 retrieve、
> 加载失败抛不退化)。延续接缝 idiom(Protocol + demo 默认 + factory + 本地懒载)。
> **唯一承重改动 = `milvus_io.search` 加 `with_text`(add-only);零新依赖、`rerank=none` 默认 byte 等价。**

## 1. 组件与依赖

```
rerank/reranker.py   RerankerClient(Protocol).rerank(query, candidates) → list[Candidate]
        ▲            NoneReranker.rerank → 入参原样(保 RRF 序;rerank=none byte 等价)    [默认]
        │            BGEReranker.rerank → FlagReranker.compute_score([(q, c.text)]) 降序重排  [本地懒载]
        │            make_reranker(qcfg) → none|bge(同 llm/embedding factory)
        ▲
retrieve/hybrid.py   Retriever 持 _reranker;Candidate +text(add-only,默认 None)
        │            retrieve(query):
        │              with_text = (qcfg.rerank_backend != "none")
        │              merge 分区(search(..., with_text=with_text))→ pool
        │              ranked = sorted(pool, RRF desc)           # 现行序(rerank=none 终态)
        │              ranked = _reranker.rerank(query, ranked)  # none=passthrough / bge=重排
        │              return ranked[:topk]
        ▲
milvus_io.search(..., with_text=False)   with_text=True → output_fields += "text" → hit 带 text(add-only)
config.py   QueryConfig +rerank_model(默认 BAAI/bge-reranker-v2-m3;env QUERY_RERANK_MODEL)
```

**复用**:`config`(`rerank_backend` 已存在)、`FlagEmbedding.FlagReranker`(同 BGE-M3,零新依赖)、`Candidate`/`_to_candidate`、
`MilvusIO.search`。**零新依赖、默认零 reranker 加载、本地离线**。

> **`rerank` 模块级零 pipeline 导入**:`reranker.py` 只依 `Candidate`(retrieve.hybrid)+ 懒载 `FlagReranker`;
> 纯函数 `NoneReranker`/`make_reranker` 可零栈测;`BGEReranker._model()` 首次 rerank 时载(同 BGE-M3 懒载)。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `milvus_io.search` 加 `with_text`(承重隔离,守等价)
- `search(..., with_text: bool = False)`:`with_text` 时 `output_fields = _OUTPUT_FIELDS + ["text"]`(hybrid 与 dense-only 兜底两路同步);`_hits` 透传 text;**`with_text=False` 时 output_fields 与原 byte 等价**(不回归)。
- **检查点 A**:`pipeline/tests/test_milvus_search_text.py`(mock collection)——`with_text=True` output_fields 含 `text`、hit 带 text;**`with_text=False` 与原 `_OUTPUT_FIELDS` 等价**;两路兜底一致。**单元 mock,不需真 Milvus**。

### Phase B — `Candidate` +text + `rerank/reranker.py`(接缝,纯部分)
- `Candidate` +`text: str | None = None`(add-only,末位,默认 None → 向后兼容既有位置构造);`_to_candidate` 填 `hit.get("text")`。
- `RerankerClient` Protocol;`NoneReranker.rerank` 入参原样;`BGEReranker.__init__(model)` + `_model()` 懒载 `FlagReranker(model)` + `rerank` = `compute_score([(query, c.text or "")])` 降序;`make_reranker(qcfg)`:none→`NoneReranker`、bge→`BGEReranker(qcfg.rerank_model)`(env `QUERY_RERANK_MODEL` 由 config 覆盖)。
- **检查点 B**:`query/tests/test_reranker.py`——`NoneReranker` passthrough(序不变);`BGEReranker`(**fake model** compute_score 返预设分)按分降序重排、`text=None` 不崩;`make_reranker` none/bge 分支。**零栈零模型**。

### Phase C — `config` + `Retriever` 接线
- `config` +`rerank_model="BAAI/bge-reranker-v2-m3"`;`_apply_env` 加 `QUERY_RERANK_MODEL` 覆盖。
- `Retriever.__init__` +`reranker`;`from_config` 经 `make_reranker(qcfg)` 注入;`retrieve`:`with_text = qcfg.rerank_backend != "none"` → `search(with_text=...)` → 合并 → RRF 序 → `_reranker.rerank` → `topk`。**`retrieve_enumerate`/`retrieve_cases` 不动**(R4/R3 不重排)。
- **检查点 C**:`test_reranker`(fake retriever 级)或 `test_hybrid_integration` 单元侧——`rerank=none` 时 retrieve 终态 = RRF 序(等价);构造注入 fake reranker 验 bge 路径走 rerank。

### Phase D — 集成(PG+Milvus+BGE-M3 + 本地 bge-reranker)
- `test_rerank_integration.py`:`rerank=bge`(`QUERY_RERANK_MODEL` 设)→ `retrieve` 重排序与 RRF 序**不同**(构造已知更相关 chunk,断言重排后靠前);**`rerank=none` 与原 retrieve byte 等价**;未设 `QUERY_RERANK_MODEL` → skip;autouse 幂等 `mio.connect()`(R3/R4/R5 预案)。
- **检查点 D**:`test_rerank_integration` 绿(gate=PG+Milvus+BGE-M3+本地 reranker;缺则 skip)。

### Phase E — 收尾(devlog/GAP/RTM/时间轴)+ 全仓门
- `query_devlog.md` 记决策/踩坑;`GAP.md`(§5.5 ✅);`RTM.md`(`§5.5`/`R1-filter`(重排部分)→✅/🟡 挂 test_id,§5.5 维护规则);`docs/devlog.md` 加阶段;全仓全量 + ruff 全绿、DAG 无环。
- **检查点 E**:全仓非模型门 + rerank 模型门集成绿;ruff 全绿。

## 3. 并行 vs 串行
A(milvus with_text,承重隔离)∥ B(reranker 接缝,纯)→ C(Retriever 接线,依赖 A+B)→ D(集成,依赖 C,真栈)→ E(收尾+全仓门)。A/B 可并行(隔离承重 + 纯接缝)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **`rerank=none` 回归** R1/R3/R4/R5/R6 | `NoneReranker` passthrough 接在 RRF 序后 = 终态不变;`with_text=False` 默认(零 text 开销);`test_reranker`+`test_milvus_search_text` 守 byte 等价 |
| R2 | **`milvus_io.search` `with_text` 回归** | **add-only**:`with_text=False` output_fields/expr 与原等价;hybrid 与 dense-only 两路同步;`test_milvus_search_text` 守 |
| R3 | reranker **联网下载** | 本地 `FlagReranker(QUERY_RERANK_MODEL)`;未设路径 → 集成 skip(同 BGE-M3,`HF_HUB_OFFLINE`);**绝不默认加载** |
| R4 | bge 后端**静默退化** none(误以为重排)| 加载失败 **抛**(Q5),不退化;`rerank=none` 才 passthrough |
| R5 | `Candidate` +text 破既有**位置构造** | text 末位 + 默认 None → R1/R3/R4/R5 既有 8-arg 构造不变(全仓门守)|
| R6 | reranker 截断(2000 vs 512)| bge-reranker 内部截 512 token,Milvus 2000 足够;rerank-hop 免 PG 往返(§5.5 schema 意图)|
| R7 | R4 枚举被误重排(违 §6.4)| `retrieve_enumerate` **不接 reranker**(只主 `retrieve`);测试断言 R4 路径无重排 |

## 5. 可追溯(§5.5 → 组件 / 守护)
| §5.5 能力 | 组件 | 守护 |
|---|---|---|
| bge-reranker cross-encoder 重排 | `BGEReranker`(`FlagReranker`)| 本地离线 |
| top50→top8 | `retrieve`(池~50 → rerank → topk)| §15 V0 标定 |
| 检索-重排一跳(Milvus text)| `search(with_text)` + `Candidate.text` | add-only,rerank-hop |
| 接缝可替换(none/bge)| `make_reranker` factory | rerank=none 默认 byte 等价 |
| 仅主 retrieve(R1/R5)| `Retriever.retrieve` | R4 枚举/R3 案例不重排 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–E)· [x] 并行 · [x] 风险(含 none 等价 + 承重 + 静默退化)· [x] 可追溯
- [ ] **人工复核批准**
