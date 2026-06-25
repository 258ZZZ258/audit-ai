# Tasks: §5.5 重排(bge-reranker)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-RERANK.md` + `PLAN-RERANK.md`(已批准:Milvus rerank-hop、仅主 retrieve、加载失败抛不退化)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。**测试基名全仓唯一**(`test_reranker`/`test_milvus_search_text`/`test_rerank_integration`,均未占用)。
> **唯一承重改动 = `milvus_io.search` 加 `with_text`(add-only,T1 隔离守等价);零新依赖、`rerank=none` 默认 byte 等价。** 集成 gate = **PG+Milvus+BGE-M3 + 本地 bge-reranker**。

- [ ] **T1:`milvus_io.search` 加 `with_text`(add-only,承重隔离)** — Phase A
  - Acceptance:`search(..., with_text: bool = False)`:`with_text` 时 `output_fields = _OUTPUT_FIELDS + ["text"]`(hybrid 与 dense-only 兜底两路同步),`_hits` 透传 `text`;**`with_text=False` 时 output_fields 与原 `_OUTPUT_FIELDS` byte 等价**(不回归 R1/R3/R4/R5/R6 检索)。
  - Verify:`pytest pipeline/tests/test_milvus_search_text.py`(mock collection:`with_text=True` output_fields 含 `text`、hit 带 text;`with_text=False` 等价;两路兜底一致)。单元 mock,不需真 Milvus。
  - Files:`pipeline/pipeline/index/milvus_io.py`、`pipeline/tests/test_milvus_search_text.py`。

- [ ] **T2:`rerank/reranker.py` 接缝 + `Candidate` +text(纯部分)** — Phase B
  - Acceptance:`Candidate` +`text: str | None = None`(add-only,末位,默认 None → 向后兼容既有位置构造);`_to_candidate` 填 `hit.get("text")`;`RerankerClient`(Protocol);`NoneReranker.rerank` 入参原样(保 RRF 序);`BGEReranker._model()` 懒载 `FlagReranker(model)` + `rerank`=`compute_score([(query, c.text or "")])` 降序;`make_reranker(qcfg)`:none→`NoneReranker`、bge→`BGEReranker(qcfg.rerank_model)`。模块级零 pipeline 导入。
  - Verify:`pytest query/tests/test_reranker.py`(`NoneReranker` passthrough 序不变;`BGEReranker` 用 **fake model**(compute_score 返预设分)按分降序重排、`text=None` 不崩;`make_reranker` none/bge 分支)。零栈零模型。
  - Files:`query/query/rerank/__init__.py`、`query/query/rerank/reranker.py`、`query/query/retrieve/hybrid.py`(仅 `Candidate` +text + `_to_candidate`)、`query/tests/test_reranker.py`。

- [ ] **T3:`config` + `Retriever` 接线(rerank 应用于主 retrieve)** — Phase C
  - Acceptance:`config` +`rerank_model="BAAI/bge-reranker-v2-m3"` + `_apply_env` 加 `QUERY_RERANK_MODEL` 覆盖;`Retriever.__init__` +`reranker`、`from_config` 经 `make_reranker(qcfg)` 注入;`retrieve`:`with_text = qcfg.rerank_backend != "none"` → `search(with_text=...)` → 合并 → RRF 序 → `_reranker.rerank(query, ranked)` → `topk`。**`retrieve_enumerate`/`retrieve_cases` 不动**(R4/R3 不重排)。
  - Verify:`pytest query/tests/test_reranker.py`(接线节:fake reranker 注入 Retriever → `rerank=none` 终态=RRF 序等价、bge 走 rerank);`pytest query/tests/test_query_config.py`(rerank_model 默认 + env)。
  - Files:`query/query/config.py`、`query/query/retrieve/hybrid.py`(`Retriever` 接线)、`query/tests/test_reranker.py`、`query/tests/test_query_config.py`。

- [ ] **T4:rerank 集成(PG+Milvus+BGE-M3 + 本地 reranker)** — Phase D 检查点
  - Acceptance:`rerank=bge`(`QUERY_RERANK_MODEL` 设)→ `retrieve` 重排序与 RRF 序**不同**(构造已知更相关 chunk,断言重排后靠前/升序);**`rerank=none` 与原 `retrieve` byte 等价**;未设 `QUERY_RERANK_MODEL` → **skip**(绝不联网);autouse 幂等 `mio.connect()` 重连(R3/R4/R5 预案)。
  - Verify:`pytest query/tests/test_rerank_integration.py`(gate=PG+Milvus+BGE-M3+本地 reranker;缺则 skip;按 batch 反 FK 序清理或复用 `indexed_stack`)。
  - Files:`query/tests/test_rerank_integration.py`(+ `query/tests/conftest.py` 如需多 chunk fixture)。

- [ ] **T5:收尾(devlog/GAP/RTM/时间轴)+ 全仓门** — Phase E 收口
  - Acceptance:`query_devlog.md` 记决策(Milvus rerank-hop with_text、none 默认 byte 等价、加载失败抛不退化、仅主 retrieve)与踩坑;`GAP.md`(§5.5 ✅,重排接缝实装);**`RTM.md`** 更新挂 test_id:`§5.5`→✅、`R1-filter`(重排部分)→🟡/✅、`§9.1-matrix`(reranker 本地)备注,覆盖摘要重算;`docs/devlog.md` 加阶段;全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;rerank 集成需 PG+Milvus+BGE-M3+本地 reranker,**提交前模型门控全量**);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(milvus with_text,承重隔离)∥ T2(reranker 接缝 + Candidate text,纯)→ T3(Retriever 接线,依赖 T1+T2)→ T4(集成,依赖 T3,真栈)→ T5(收尾+全仓门)。T1/T2 可并行(隔离承重 + 纯接缝)。

## 覆盖 SPEC-RERANK §8 成功标准
SC1 bge 重排序≠RRF→T3(接线)/T4(集成);SC2 **rerank=none byte 等价**→T2(passthrough)/T3(终态)/T4(集成);SC3 milvus with_text add-only→T1;SC4 Candidate +text 向后兼容→T2(全仓门);SC5 reranker 接缝(none/bge/factory)→T2;SC6 本地离线 skip→T4;SC7 集成→T4;SC8 全仓门+DAG→T5。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC8)· [x] T5 同步更新 RTM(维护规则)· [x] 测试基名全仓唯一(`test_reranker`/`test_milvus_search_text`/`test_rerank_integration`)
- [ ] **人工复核批准**
