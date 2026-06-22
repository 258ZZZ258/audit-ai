# Tasks: 制度查询智能体 MVP —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**(批准后才进 Phase 4 IMPLEMENT,逐任务 TDD)。
> 依据:`SPEC.md`(已批准)+ `PLAN.md`(已批准,LangGraph 采用 / 接口保真 / §2.5 可拓展性)。
> 约定:每任务 ≤5 文件、单次专注会话可完成、TDD(先写断言再实现)、含验收 + 验证。`[P]`=可与同阶段任务并行。

---

## Phase A —— 地基与契约(串行,最先;全部依赖其上)

- [x] **T1:建 `query/` 包 + 打包接线 + DAG 守护** ✅
  - Acceptance:`pip install -e query` 成功;`import query` 可用;根 `pyproject` 的 `pythonpath`/`testpaths`/`known-first-party` 含 `query`;`import pipeline` 不触发 `import query`(DAG 无环)。
  - Verify:`pip install -e query && python -c "import query"`;`python -c "import pipeline"` 正常;`ruff check .` 0 报。
  - Files:`query/pyproject.toml`、`query/query/__init__.py`、`query/tests/__init__.py`、`pyproject.toml`(根)。

- [x] **T2:`QueryState` + 输出契约 `contract.py`(§10 全字段)** ✅
  - Acceptance:`QueryState` dataclass 含 §2.5-2 全字段;契约含 `route_type/answer_blocks/citations/confidence/ai_label/review_required/exhausted_scope/export_enabled`,序列化形状对齐 §10;`test_contract` 绿。
  - Verify:`pytest query/tests/test_contract.py`。
  - Files:`query/query/state.py`、`query/query/contract.py`、`query/tests/test_contract.py`。

- [x] **T3:`config.py` + `config/settings.toml [query]` 段** ✅
  - Acceptance:`load_query_config()` 读 `[query]`(`topk`、分区配额、充分性阈值、`llm_backend`、`rerank_backend`),缺省值齐全;⚠ 值不硬编码;`test_config` 绿。
  - Verify:`pytest query/tests/test_config.py`。
  - Files:`query/query/config.py`、`config/settings.toml`、`query/tests/test_config.py`。

- [x] **T4:LLM 接缝(`llm/client.py` Protocol + `make_llm_client` + `llm/stub.py`)** ✅
  - Acceptance:`LLMClient` ABC + `from_config`(读 `QUERY_LLM_BACKEND`,默认 `stub`);`StubLLMClient.chat_json` **零网络、确定性**——从上下文选前 N 个 `clause_id`(使引用注入可测);`gateway` 后端**懒导入** `pipeline.llm_client`;`test_llm_stub` 绿。
  - Verify:`pytest query/tests/test_llm_stub.py`(零网络)。
  - Files:`query/query/llm/__init__.py`、`query/query/llm/client.py`、`query/query/llm/stub.py`、`query/tests/test_llm_stub.py`。
  - **检查点 A**:✅ **已过**(query 15 passed、ruff 全仓绿、DAG 无环;`query` 可装可导、契约/配置/stub 就位)。

---

## Phase B —— 检索与回查脊柱(`[P]` 可与 Phase C 并行;依赖 A)

- [x] **T5:`retrieve/hybrid.py`(查询向量化 + 混合检索 + 分区配额 + 过滤位)** ✅
  - Acceptance:复用 `pipeline.index.embedding_client` 向量化、`pipeline.index.milvus_io` 混合检索(内规∥外规分区各 top25,§5.2)+ `status=effective` + `perm_tag`(预留)/`entity_type`/`biz_domain` 过滤(§5.3);返回带 `clause_id` 的候选;hybrid 失败 dense-only 兜底标记。
  - Verify:`pytest query/tests/test_hybrid_integration.py`(连真栈,栈未起 `skip`;用 `ingest_index` 造一小件入库)。
  - Files:`query/query/retrieve/__init__.py`、`query/query/retrieve/hybrid.py`、`query/tests/test_hybrid_integration.py`。

- [x] **T6:`generate/anchors.py`(四级锚点 PG 回查 + 父块供证)** ✅
  - Acceptance:给 `chunk_id` 列表 → 回查 `common.pg_models.Chunk`/`DocVersion` 得 `clause_path`/`doc_version_id`/`page_start/end`/`version+status`;命中子块经 `parent_chunk_id` 取父块供证(§5.6);**不用 Milvus 截断 text**。
  - Verify:`pytest query/tests/test_anchors_integration.py`(连真栈,栈未起 `skip`)。
  - Files:`query/query/generate/__init__.py`、`query/query/generate/anchors.py`、`query/tests/test_anchors_integration.py`。
  - **检查点 B**:✅ **已过**(真栈 + 真 BGE-M3,query 20 passed、ruff 全仓绿、DAG 无环;混合检索命中 ingest 件、四级锚点含 page_start/status 回查正确、父块供证验通)。

---

## Phase C —— 路由与理解骨架(`[P]` 可与 Phase B 并行;依赖 A)

- [x] **T7:`understand/classify.py`(N2 场景/事项/entity_type,规则+词典)** ✅
  - Acceptance:输出场景类型 + 涉及事项(映射 `dict_biz_domains`)+ entity_type(命中 `dict_entity_types`);规则 + 词典前置匹配;LLM 经接缝**可选**(默认不调);确定性。
  - Verify:`pytest query/tests/test_classify.py`。
  - Files:`query/query/understand/__init__.py`、`query/query/understand/classify.py`、`query/tests/test_classify.py`。

- [x] **T8:`understand/router.py`(N4 八路骨架,R1/R7/R8 实装)** ✅
  - Acceptance:**分满 8 类** `route_type`;置信度;低置信→R7;多标签优先级(§4.3 判定>统计>变更>列举>依据);R2–R6 输出正确标签但**不实装**;router golden 绿(R1/R7/R8 正确、R2–R6 正确打标且不裸答不报错)。
  - Verify:`pytest query/tests/test_router.py`。
  - Files:`query/query/understand/router.py`、`query/tests/golden/router_golden.jsonl`、`query/tests/test_router.py`。
  - **检查点 C**:✅ **已过**(query 31 passed / 5 skipped、ruff 全仓绿;router golden 15 例全中、八路分满、R7/R8 触发与置信度验通)。

---

## Phase D —— R1 生成 + 引用注入 + 充分性(`[P]` 可与 Phase E 并行;依赖 A+B)

- [x] **T9:`retrieve/sufficiency.py`(N5 充分性,接口按 §8.1 保真)** ✅
  - Acceptance:纯函数 `(query, candidates, 涉及事项) → {sufficient: bool, exhausted_scope: list[str]}`;实现先务实(biz_domain 分区高召回命中与否),**接口对齐 §8.1**(出参带 `exhausted_scope`),升级判据不动调用方;`test_sufficiency` 绿。
  - Verify:`pytest query/tests/test_sufficiency.py`。
  - Files:`query/query/retrieve/sufficiency.py`、`query/tests/test_sufficiency.py`。

- [x] **T10:`generate/citation_inject.py`(§7.1 引用 ID 注入 prompt)** ✅
  - Acceptance:候选每块注入 `clause_id`;system prompt 强约束"只引用上下文中带 clause_id 的内容、禁凭记忆生成发文字号/条号";返回 `(system, user)`。
  - Verify:`pytest query/tests/test_citation_inject.py`。
  - Files:`query/query/generate/citation_inject.py`、`query/tests/test_citation_inject.py`。

- [x] **T11:`generate/r1_evidence.py`(R1 主路径)+ 红线断言** ✅
  - Acceptance:编排 retrieve→sufficiency→(充分)citation_inject→LLM(stub)→anchors→contract;**引用真实性**:`citations[].clause_id ⊆ 上下文注入集合`;**无裸结论**正则断言;产出合法契约(`route_type=evidence`)。
  - Verify:`pytest query/tests/test_citation_faithfulness.py query/tests/test_no_bare_conclusion.py`。
  - Files:`query/query/generate/r1_evidence.py`、`query/tests/test_citation_faithfulness.py`、`query/tests/test_no_bare_conclusion.py`。
  - **检查点 D**:✅ **已过**(真栈 + 真 BGE-M3,query 47 passed、ruff 全仓绿、DAG 无环;引用真实性 clause_id⊆候选、四级锚点、无裸结论、R1 端到端 stub 验通;`select_faithful` 代码级兜底)。

---

## Phase E —— 覆盖感知拒答(`[P]` 可与 Phase D 并行;依赖 B 的 sufficiency 接口 + contract)

- [x] **T12:`refuse/coverage_refusal.py`(§8.2 + §6.8 兜底)** ✅
  - Acceptance:不足 → 契约 `route_type=refuse` + `exhausted_scope` 非空 + 话术含"未检索到…明确禁止性规定" + 附最接近 N 条;**绝不裸答**。
  - Verify:`pytest query/tests/test_coverage_refusal.py`。
  - Files:`query/query/refuse/__init__.py`、`query/query/refuse/coverage_refusal.py`、`query/tests/test_coverage_refusal.py`。
  - **检查点 E**:✅ **已过**(query 46 passed / 7 skipped、ruff 全仓绿;覆盖感知拒答话术 + exhausted_scope + 最接近 N 条 + 兜底拒答 + 无裸结论验通)。

---

## Phase F —— 编排装配 + CLI(最后;依赖 C+D+E)

- [x] **T13:`graph.py`(LangGraph 装配 + langgraph 依赖)** ✅
  - Acceptance:`QueryState` 共享;图 = router →{r1_evidence / clarify(R7)/ refuse(R8)/ R2–R6 占位};**节点为纯函数**(不 import langgraph),`graph.py` 只装配边;stub 下端到端跑通;`langgraph` 入 `query/pyproject.toml` 依赖。
  - Verify:`pytest query/tests/test_graph.py`。
  - Files:`query/query/graph.py`、`query/tests/test_graph.py`、`query/pyproject.toml`。

- [x] **T14:`cli.py`(`query ask` / `query route`,thin shell)** ✅
  - Acceptance:`query ask "<q>"` 跑图 → 打印契约 JSON;`query route "<q>"` 打印判定;console script `query` 注册;thin shell over 域函数。
  - Verify:`query ask "费用报销发票3个月的规定在哪"` 手验 + `pytest query/tests/test_cli.py`。
  - Files:`query/query/cli.py`、`query/pyproject.toml`(entry point)、`query/tests/test_cli.py`。

- [x] **T15:devlog + CLAUDE.md 模块索引 + 收尾全量门** ✅
  - Acceptance:`query_devlog.md` 记关键决策(LangGraph/接口保真/务实判据/§2.5);CLAUDE.md 模块索引加 query 行;全量 `pytest -q` 绿且**默认零网络**;`ruff check .` 0;DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`;`.venv/bin/ruff check .`;`python -c "import pipeline"`(不引 query)。
  - Files:`docs/query-agent-docs/query_devlog.md`、`CLAUDE.md`。
  - **检查点 F**:✅ **已过**(`query ask` 端到端产出 §10 契约;**全仓 440 passed / 0 failed**,真模型全程;`query route` console script 实跑;R2–R6 诚实占位;ruff 全仓绿、DAG 无环)。

> ⚠ 踩坑(已修):pytest prepend 模式 + tests 无 `__init__.py` → 测试**基名须全仓唯一**;
> `test_smoke/test_cli/test_config` 与 eval/pipeline 撞名致收集报错,重命名为 `test_query_*`。

---

## 依赖与并行总览

```
A(T1→T2→T3→T4)
   ├── B(T5 [P] T6)  ──┐
   └── C(T7→T8)    ──┐ │
                     │ ├── D(T9→T10→T11,需 A+B) ──┐
                     │ └── E(T12,需 B+contract) ──┤
                     └──────────────────────────── F(T13→T14→T15,需 C+D+E)
```
- A 串行最先;**B 与 C 并行**;**D 与 E 并行**;F 收尾。
- 任务内 TDD:先写该任务 Verify 列的测试到红,再实现到绿。

---

## 验证清单(进入 Phase 4 IMPLEMENT 前)

- [ ] 任务离散、≤5 文件、单会话可完成 —— ✅
- [ ] 每任务有验收 + 验证步骤 —— ✅
- [ ] 按依赖排序、并行边界清晰 —— ✅
- [x] 覆盖 SPEC §8 全部成功标准(SC1–SC7)—— ✅(T11/T12/T8/T6/T4/T15)
- [x] **Phase 4 IMPLEMENT 全部完成** —— ✅ T1–T15 全过,Checkpoints A–F 全绿,全仓 440 passed / 0 failed(真模型)
