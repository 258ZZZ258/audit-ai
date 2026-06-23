# Tasks: R3 相似案例 + 案例桥接 —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-R3.md` + `PLAN-R3.md`(已批准,Q1–Q4 已决策)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。集成 gate = 模型+PG+Milvus+soffice(无则 skip)。
> **零契约改动、零新依赖、零 LLM**。

- [ ] **T1:`case/case_card.py`(纯函数组卡)** — Phase A
  - Acceptance:`CaseCard`(frozen:doc_version_id/title/penalty_org/penalty_date/respondent/penalty_type/amount_wan/violation_category/cited_regulations)+ `from_rows(case_row, doc_meta)`;`build_case_card(case_row, doc_meta) → AnswerBlock(CASE_CARD, content=JSON 字符串)`:标题取 `doc_meta`(PG 权威),**L2 空字段省略**(violation_category=None / cited_regulations=[] 不进 JSON),**零臆造**。
  - Verify:`pytest query/tests/test_case_card.py`(present/absent 字段、JSON 形状、缺失省略;零栈零模型)。
  - Files:`query/query/case/__init__.py`、`query/query/case/case_card.py`、`query/tests/test_case_card.py`。

- [ ] **T2:`case/bridge.py`(精确反查纯函数 + PG 索引,consumed-when-present)** — Phase B
  - Acceptance:`norm_ref(doc_no, clause_path) → str`(发文字号/文号 + `clause_path_norm` 归一,复用 chunking 归一口径);`build_cited_index(pg) → dict[str, list[str]]`(扫 `cases` 中 **cited_regulations 非空**行 → `norm_ref→[dvid]`;默认全空→空索引;全表扫 demo 可接受,注释标注生产换 JSONB GIN/containment);`cases_for_clauses(pg, clause_keys) → list[str]`(命中索引去重 dvid)。**cited_regulations 空 → 降级返回 [] / {}**。
  - Verify:`pytest query/tests/test_bridge.py`(`norm_ref` 归一等价类、命中反查、未命中、**空降级**;PG 索引用 fake/真栈小夹具;纯归一逻辑零栈)。
  - Files:`query/query/case/bridge.py`、`query/tests/test_bridge.py`。

- [ ] **T3:`retrieve_cases` + `case/r3_case.py`(编排 + 附挂,纯部分)** — Phase C
  - Acceptance:`Retriever.retrieve_cases(query) → list[Candidate]`(`milvus_io.search(corpus="P-CASE")`,status==effective 前置复用);`answer_case(query, retriever, pg, qcfg)`:检索 → `drop_degraded` → **按 dvid 去重一案一卡**(保留更高分)→ top-N → `get_case`+`get(DocVersion)` 回填 → `build_case_card` → `QueryResult(route_type=case)`;**空命中/无 cases 行 → 明示 TEXT 块**(不报错、不臆造),`get_case` None 的命中跳过该卡;`attach_cases(result, query, citations, retriever, pg, qcfg)`:语义(retrieve_cases)∪ 精确反查(`cases_for_clauses(pg, [norm_ref(c)…])`)→ 去重 → top-N(attach_topk)→ **追加** CASE_CARD 块,**零命中不挂**。
  - Verify:`pytest query/tests/test_r3_case.py`(纯部分用 fake retriever/pg:去重一案一卡、空命中明示、get_case None 跳过、attach 去重+零命中不挂)。
  - Files:`query/query/retrieve/hybrid.py`、`query/query/case/r3_case.py`、`query/tests/test_r3_case.py`。

- [ ] **T4:R3 集成(真栈案例件)** — Phase C 检查点
  - Acceptance:ingest 一件处罚决定书(P-CASE,`cases` L1 要素入库)→ `answer_case` 产出 `route_type=case` 契约:≥1 CASE_CARD、要素=PG `cases`/`doc_versions` 权威、一案一卡;空查询/无案例 → 明示无相似案例。**卡片要素不来自 Milvus 截断文本/不来自 LLM**。
  - Verify:`pytest query/tests/test_r3_case_integration.py`(栈未起/无模型 skip;按 batch_id 反 FK 序清理)。
  - Files:`query/tests/test_r3_case_integration.py`(+ 必要时 `query/tests/conftest.py` 加案例件 fixture)。

- [ ] **T5:graph 接线 + 附挂 + config + 端到端** — Phase D
  - Acceptance:`QueryConfig` +`attach_cases:bool=True`/`attach_topk:int=3`(读 `[query]` 段、env 可覆盖),`config/settings.toml` 加注释示例;`graph._r3_case` 节点替 placeholder(`_TERMINAL[CASE]="r3_case"`、`_build` 加节点+边);`_evidence` **充分分支**生成后:`if qcfg.attach_cases and route==evidence and scene!=definition: res = attach_cases(...)`(**拒答分支不附挂**、`definition` 不附挂);`QueryAgent.ask("<案例问句>")`→`route_type=case`、`ask("<依据问句>")`→`evidence`+默认尾挂**语义**案例卡;**手插** `cited_regulations` fixture → 依据答复尾挂**精确反查**案例卡。
  - Verify:`pytest query/tests/test_graph_integration.py`(加 R3 案例例 + 附挂例);手插 fixture 验证精确反查。
  - Files:`query/query/graph.py`、`query/query/config.py`、`config/settings.toml`、`query/tests/test_graph_integration.py`。

- [ ] **T6:收尾(devlog/GAP)+ 全仓门** — Phase D 收口
  - Acceptance:`query_devlog.md` 记 R3 决策(consumed-when-present 反查、一案一卡去重、附挂边界、norm_ref 契约)与踩坑;`GAP.md` 勾 R3(§2 R3、§8 `cases`/§5 附挂相关行更新状态);全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈 + 本地 BGE-M3,提交前模型门控全量);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`。

## 依赖与并行
T1(纯,叶子)∥ T2(纯+PG 索引,叶子)→ T3(依赖 T1+T2)→ T4(依赖 T3,真栈)→ T5(依赖 T3/T4,接线+附挂+e2e)→ T6(收尾+全仓门)。T1/T2 单测可并行写;T4 集成与 T5 e2e 共享真栈。

## 覆盖 SPEC-R3 §8 成功标准
SC1 route_type=case 卡片→T3/T4/T5;SC2 一案一卡→T3;SC3 要素保真/L2 省略→T1;SC4 精确反查/空降级→T2(+T5 fixture);SC5 附挂 top-N/零命中不挂/追加块→T3(impl)+T5(wiring/e2e);SC6 拒答不附挂→T5;SC7 零 LLM→全程(R3 不调 LLM);SC8 集成+全仓门+DAG→T4/T5/T6。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC8)
- [ ] **人工复核批准**
