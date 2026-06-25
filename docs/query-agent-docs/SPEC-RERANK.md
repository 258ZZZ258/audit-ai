# Spec: §5.5 重排(bge-reranker-v2-m3 cross-encoder,top50→top8)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md P1。八路收官后**首个横切检索增强**(惠及 R1/R5)。
> 延续 MVP 范式(接缝 = Protocol + demo 默认 + 读配置 factory + 本地实现;零网络默认)。上游设计:
> `制度查询智能体_技术框架设计_v1_0.md` §5.5 / §5.1。本文件只述重排增量。
> **已决(2026-06-25,AskUserQuestion)**:候选文本来源=**Milvus rerank-hop**(扩 `search` 加 `with_text` add-only);
> 应用范围=**仅主 hybrid `retrieve`(R1/R5)**(R4 枚举求召回完整性不精排、R3 案例一案一卡去重,均不重排)。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **§5.5 重排实装**:`rerank_backend=bge` 时,主 hybrid `retrieve` 对合并候选池(~50,2 分区×`partition_topk`)用 **bge-reranker-v2-m3** cross-encoder 重排 → 取 `topk`(8)。新增 `query/query/rerank/`(`RerankerClient` Protocol + `NoneReranker` passthrough **默认** + `BGEReranker` 本地 `FlagReranker` 懒载 + `make_reranker` factory)。扩 `milvus_io.search` 加 **`with_text`**(add-only;输出 Milvus 截断 text 供"检索-重排一跳")。`Candidate` +`text`(add-only,默认 None)。**`rerank=none`(默认)byte 等价**(RRF 序 + passthrough,不回归 R1/R3/R4/R5/R6)。本地 reranker **离线**(未设 `QUERY_RERANK_MODEL` → 集成 skip,绝不联网)。 |
| **不做** | 重排应用于 **R4 枚举**(§6.4 召回完整性,不激进截断 —— 与精排 top8 相悖)/ **R3 案例**(一案一卡去重)/ **R6**(无向量)。LLM reranker(`FlagLLMReranker`)——用判别式 bge-reranker。rerank **endpoint/网关**(§9.1;本地 `FlagReranker` 同 BGE-M3 本地 workaround)。top-k **V0 标定**(§15,默认 50→8 占位)。sparse 发文字号提权(§5.4,另议)。`partition_topk` 调参(沿用 25)。 |

## 1. Objective

把 §5.1 的 **RRF 融合序**升级为 **bge-reranker-v2-m3 cross-encoder 重排**(§5.5),提升 R1 依据 / R5 判定的
检索精度(query×doc 交叉打分 > RRF 的向量近邻序)。

成功 = `rerank_backend=bge` 时 `Retriever.retrieve` 用 reranker 对候选池重排 → `topk`,rerank 序 ≠ RRF 序
(已知相关 chunk 升序);**`rerank=none`(默认)与本轮前 byte 等价**(不回归);reranker **本地离线**
(未设模型路径自动 skip 集成);接缝 = Protocol + demo 默认 + factory(同 LLM/embedding 接缝)。

## 2. Tech Stack(增量)

- 复用 `query/` 既有:`config`(`rerank_backend` Literal["none","bge"] **已存在** + `QUERY_RERANK_BACKEND` env)/
  `retrieve.hybrid`(`Retriever.retrieve` / `Candidate`)。
- 复用 `pipeline`:`milvus_io.search`(扩 `with_text`)。**`FlagEmbedding.FlagReranker`** 已在栈内(同 BGE-M3 的
  FlagEmbedding,零新依赖)。
- 新增 `query/query/rerank/`:`reranker.py`(`RerankerClient` Protocol + `NoneReranker` + `BGEReranker` 本地懒载 +
  `make_reranker(qcfg)`)。
- `config` +`rerank_model`(默认 `BAAI/bge-reranker-v2-m3`;env `QUERY_RERANK_MODEL` 本地路径覆盖)。
- **零新依赖、默认零 reranker 加载(none passthrough)、本地离线**。

## 3. Commands

```bash
demo up                                                   # rerank 集成需 PG+Milvus+BGE-M3 + 本地 bge-reranker
QUERY_RERANK_BACKEND=bge QUERY_RERANK_MODEL=<本地 reranker 目录> demo search "合同法务审查"   # 走重排
.venv/bin/python -m pytest query/tests/test_reranker.py pipeline/tests/test_milvus_search_text.py \
  query/tests/test_rerank_integration.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/rerank/
  __init__.py
  reranker.py    # RerankerClient(Protocol) + NoneReranker(passthrough,默认) + BGEReranker(FlagReranker 本地懒载) + make_reranker(qcfg)
query/query/retrieve/hybrid.py   # retrieve:rerank!=none → with_text 池 → reranker 重排 → topk;Candidate +text(add-only)
pipeline/pipeline/index/milvus_io.py  # search +with_text(add-only:输出 text 字段)
query/query/config.py            # +rerank_model(默认 bge-reranker-v2-m3);rerank_backend 已存在
query/tests/
  test_reranker.py               # 纯单元:NoneReranker passthrough;BGEReranker 用 fake model 按分重排;text 缺省
  test_rerank_integration.py     # 连真栈(PG+Milvus+BGE-M3+本地 reranker):重排序生效、rerank=none 等价
pipeline/tests/test_milvus_search_text.py  # with_text(mock):输出 text;with_text=False 与原等价
docs/query-agent-docs/SPEC-RERANK.md / PLAN-RERANK.md / TASKS-RERANK.md
```

## 5. Code Style

沿用接缝 idiom(`llm/client.py` / `embedding_client`):Protocol + demo 默认 + factory + 本地懒载。

```python
@runtime_checkable
class RerankerClient(Protocol):
    def rerank(self, query: str, candidates: list[Candidate]) -> list[Candidate]: ...

class NoneReranker:
    def rerank(self, query, candidates):
        return candidates            # passthrough:保留入参(RRF)序 → rerank=none byte 等价

class BGEReranker:                   # 本地 FlagReranker 懒载(同 BGE-M3,首次 rerank 时载)
    def rerank(self, query, candidates):
        scores = self._model().compute_score([(query, c.text or "") for c in candidates])
        order = sorted(zip(scores, candidates), key=lambda z: z[0], reverse=True)
        return [c for _, c in order]
```

## 6. Testing Strategy

- **单元(零栈零模型)**:
  - `reranker`:`NoneReranker` passthrough(序不变,等价守护);`BGEReranker` 用 **fake model**(`compute_score` 返预设分)→ 按分降序重排;`make_reranker`(none/bge 分支);`text=None` 缺省不崩。
  - `milvus with_text`(**mock collection**):`with_text=True` output_fields 含 `text`、hit 带 text;**`with_text=False` 与原 `_OUTPUT_FIELDS` 等价**(守不回归)。
- **集成(gate = PG+Milvus+BGE-M3 + 本地 bge-reranker)**:`rerank=bge` → `retrieve` 重排序与 RRF 序**不同**(构造已知更相关 chunk,断言重排后升序到 top);**`rerank=none` 与原 `retrieve` byte 等价**;未设 `QUERY_RERANK_MODEL` → skip。
- **守护断言**:**`rerank=none` 默认 byte 等价**(`test_reranker` + `test_milvus_search_text`,不回归 R1/R3/R4/R5/R6);reranker **本地离线**(绝不联网下载)。

## 7. Boundaries

- **Always**:`rerank=none` 默认 **byte 等价**(不回归既有八路);本地 reranker **离线**(未设路径 skip);`Candidate.text` / `search(with_text)` **add-only**(默认关,既有调用零变化);重排只施于主 `retrieve`(R1/R5)。
- **Ask first**:**扩 `milvus_io.search` `with_text`**(`pipeline` 承重检索层 —— add-only:加可选输出字段,既有调用零行为变化,`test_milvus_search_text` 守等价);新依赖(`FlagReranker` 已在 `FlagEmbedding`,**零新增**)。
- **Never**:改 `rerank=none` 默认行为 / 默认加载 reranker;**联网下载** reranker;重排应用于 **R4 枚举**(违 §6.4 召回完整性);rerank 改变 `status`/可见性过滤语义。

## 8. Success Criteria(可测)

1. `rerank_backend=bge` → `Retriever.retrieve` 用 **bge-reranker-v2-m3** 对候选池(~50)cross-encoder 重排 → `topk`(8);**rerank 序 ≠ RRF 序**(集成断言)。
2. **`rerank=none`(默认)byte 等价**:`retrieve` 行为与本轮前一致(`test_reranker` passthrough + 集成等价);默认**零 reranker 加载**。
3. **`milvus_io.search` +`with_text`(add-only)**:`True` 输出 `text`、`False` 与原 `_OUTPUT_FIELDS` **等价**(`test_milvus_search_text`)。
4. **`Candidate` +`text`(add-only,默认 None)**:向后兼容既有位置构造(R1/R3/R4/R5 测试)。
5. **reranker 接缝**:`NoneReranker` passthrough / `BGEReranker` 本地 `FlagReranker` 懒载;`make_reranker(qcfg)` factory(同 LLM/embedding)。
6. **本地离线**:未设 `QUERY_RERANK_MODEL` → 集成 **skip**(绝不联网)。
7. 集成(`rerank=bge` 真栈)→ 重排序生效;`rerank=none` 等价。
8. 全仓全量 + ruff 全绿;**DAG 无环**(`query → pipeline → common`)。

## 9. Open Questions(已决 2 项 + 默认待 gate 确认)

| # | 事项 | 处置(✅=AskUserQuestion 已定 / 默认) |
|---|---|---|
| **文本来源** | 重排候选文本 | ✅ **Milvus rerank-hop**(扩 `search` `with_text` add-only,Milvus 截断 text;reranker 截 512 token,2000 足够)。 |
| **应用范围** | 重排施于哪些 retrieve | ✅ **仅主 hybrid `retrieve`(R1/R5)**;R4 枚举/R3 案例/R6 不重排。 |
| Q1 | pool / topk 值 | 默认 `partition_topk=25`(池 ~50)→ `topk=8`(§5.5 top50→top8);⚠ V0 标定。 |
| Q2 | reranker 模型 | 默认 `BAAI/bge-reranker-v2-m3`(`rerank_model` config + `QUERY_RERANK_MODEL` 本地路径 env)。 |
| Q3 | `compute_score` 归一 | 默认 raw logits(仅用于排序,不设阈值;`normalize` 留 config 增强)。 |
| Q4 | 集成 fixture | 默认复用 `indexed_stack`(R1 件多 chunk),构造已知更相关 chunk 验重排序;gate 加本地 bge-reranker。 |
| Q5 | reranker 加载失败 | 默认与 BGE-M3 一致:加载失败 / 未设路径 → 集成 **skip**;运行期 `bge` 后端载失败 → 抛(不静默退化 none,避免误以为重排了)。 |

## 10. 与 §15 / §5.5 的关系

- **§15-①(网关轻量小模型)**:reranker 走**本地 `FlagReranker`**(同 BGE-M3 本地 workaround,**绝不联网**);
  生产换 rerank **endpoint**(§9.1 模型网关)。top-k(50→8)属 **§15 待 V0 标定**(默认占位,不对甲方承诺)。
- **§5.5 既定默认**:bge-reranker-v2-m3,top50→top8;本轮落地接缝 + 本地实现,**`rerank=none` 默认不回归**。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§7 Ask-first 扩 `milvus_io.search` `with_text` add-only、§8 SC2 `rerank=none` 等价、§9 Q5 加载失败处置)
