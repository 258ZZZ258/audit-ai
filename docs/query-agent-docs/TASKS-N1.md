# Tasks: N1 HyDE 查询改写(假设性法言 → dense 检索)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-N1.md` + `PLAN-N1.md`(已批准:① HyDE 默认开;② Retriever 内
> dense 接缝;HyDE 专管 dense、sparse 留原问;默认 stub→no-op byte 等价;LLM 失败 fail-safe 回落原问 dense;仅主 retrieve;
> V0 未跑→记 🟡)。
> 约定:每任务 ≤5 文件、TDD(先写失败测试)、含验收+验证。**测试基名全仓唯一**:新增 `test_hyde`(未占用)、
> `test_hyde_integration`(未占用);扩 `test_query_config`(已存在)。
> **sparse/`embedding_client`/`milvus_io`/`state.py`/graph 零改;enumerate/cases 不接 HyDE;默认 stub→`hyde_llm` 不建→零网络。**

- [ ] **T1:`config` +`hyde`/`hyde_model`(add-only)** — Phase A(可并行)
  - Acceptance:`QueryConfig` +`hyde: bool = True`(§3 节点链默认开,已决①)+ `hyde_model: str | None = None`(None→复用
    `llm_model`,§9.1 CP-007 轻量调用意图占位);`_apply_env` +`QUERY_HYDE`(字符串→bool,对齐 `merge_context`/`docnum_boost`)
    + `QUERY_HYDE_MODEL` 覆盖。既有默认行为零变化(默认 stub → HyDE no-op)。
  - Verify:`pytest query/tests/test_query_config.py`(`hyde` 默认 True / `hyde_model` 默认 None;`QUERY_HYDE=0`→False、`QUERY_HYDE_MODEL` 设值覆盖)。零栈。
  - Files:`query/query/config.py`、`query/tests/test_query_config.py`(扩)。

- [ ] **T2:`retrieve/hyde.py` 纯函数核(生成 + 解析 + fail-safe)** — Phase B(可并行,纯函数零栈)
  - Acceptance:`HYDE_SYSTEM`(口语→1–2 句假设性法言,**只写法言、不作答、不编造发文字号/条款号**)+ `build_hyde_user(query)`
    + `parse_passage(resp)->str|None`(取 `passage`,非串/空→None)+ `hyde_dense_text(query, llm)->str|None`(生成→`f"{query}\n{passage}"`;
    LLM 抛/返空→None,fail-safe)。**不产出 `clause_id`**(§7.1 红线)。
  - Verify:`pytest query/tests/test_hyde.py`(零栈零网络)—— `parse_passage` 畸形→None;`hyde_dense_text`:fake llm 返 passage→
    `原问+法言`、抛→None、返空→None;`build_hyde_user` 含原问;`HYDE_SYSTEM` 含「不编造」「只写」「假设」。
  - Files:`query/query/retrieve/hyde.py`(新)、`query/tests/test_hyde.py`(新)。

- [ ] **T3:`PROMPTS.md` 记 §3.1 HyDE prompt** — Phase C(可并行,doc)
  - Acceptance:录 `HYDE_SYSTEM`/`build_hyde_user` 归并 prompt(契约约定,代码内联镜像,同 L2/E2/§9.2/§3.4 范式);标注**只写
    假设性法言、不作答、不生成 `clause_id`/发文字号**(§7.1 污染兜底)+ 失败 fail-safe 回落原问 dense + 默认开(仅 gateway 活)。
  - Verify:人工核对 `PROMPTS.md` 与 `hyde.py` prompt 文本一致。
  - Files:`PROMPTS.md`。

- [ ] **T4:`retrieve/hybrid.py` `_dense_for` + `hyde_llm` 接线** — Phase D(依赖 T1+T2)
  - Acceptance:`Retriever.__init__` +`hyde_llm=None` 参 + 存 `self._hyde_llm`;`from_config` 建 `hyde_llm = make_llm_client(qcfg,
    model=qcfg.hyde_model or qcfg.llm_model) if qcfg.hyde and qcfg.llm_backend=="gateway" else None`;`_dense_for(query, emb)`
    (`hyde_llm None`→`emb.dense`;else `hyde_dense_text`→`embed([text])[0].dense`,失败→`emb.dense`);`retrieve()` 用
    `dense = self._dense_for(query, emb)` 替 `emb.dense`。**`retrieve_enumerate`/`retrieve_cases`/`_sparse_for` 不改。**
  - Verify:`pytest query/tests/test_hyde.py`(扩,fake embed[记录 embed 文本]/fake hyde_llm 构 Retriever,零栈)—— ① `hyde_llm=None`→
    `_dense_for` 返 `emb.dense`(embed 仅原问);② 返 passage→embed「原问+法言」并返其 dense;③ 抛→回落 `emb.dense`;④ `from_config`
    仅 hyde 开+gateway 建 `hyde_llm`(monkeypatch `make_llm_client` sentinel);⑤ enumerate/cases 不调 `_dense_for`(sparse 不变)。
  - Files:`query/query/retrieve/hybrid.py`、`query/tests/test_hyde.py`(扩)。

- [ ] **T5:真-LLM 生成门控集成(gate=gateway+`OPENAI_API_KEY`)** — Phase E 检查点(依赖 T2)
  - Acceptance:`hyde_dense_text(口语问句, 真 llm)` → 非空、含原问 + 一段假设性法言文本(断言生成成功、含原问子串);**未设
    `OPENAI_API_KEY` / 非 gateway → skip**(绝不联网)。聚焦 HyDE 生成层(无需全栈/Milvus)。
  - Verify:`pytest query/tests/test_hyde_integration.py`(gate 满足时绿;缺 key→skip)。证真 HyDE 生成闭环。**本地无 key→诚实记 🟡。**
  - Files:`query/tests/test_hyde_integration.py`(新建)。

- [ ] **T6:收尾(devlog/GAP/RTM)+ 全仓门** — Phase F 收口
  - Acceptance:`query_devlog.md` 记决策(HyDE 默认开 + 离线 stub no-op + dense 专管/sparse 归 §5.4 + fail-safe + V0 未跑记 🟡)
    与踩坑;`GAP.md`(N1 ❌→🟡、§1.3 TO-1 推进);**`RTM.md`** N1/N1-fail/N1-decision 挂 SC+test_id + 覆盖摘要重算(116 基线不变);
    `docs/devlog.md` 加阶段。
  - Verify:`PYTHONPATH=... .venv/bin/python -m pytest query/tests -q`(全 query 套件;HyDE 集成需 gateway+key,**提交前模型门控
    全量跑一次**,无 key 时 skip 不漏回归);`.venv/bin/ruff check .`;DAG 无环。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(config)∥ T2(hyde.py 核心)∥ T3(PROMPTS)→ T4(hybrid 接线,依赖 T1+T2)→ T5(集成,依赖 T2,真 gateway)→ T6(收尾+全仓门)。

## 覆盖 SPEC-N1 §7 成功标准
SC1 HyDE dense 改写→T2(`hyde_dense_text`)/T4(`_dense_for`);SC2 **默认 no-op byte 等价**→T4(`hyde_llm None`→`emb.dense`)/既有 `test_hybrid_integration`;SC3 **fail-safe 不阻断**→T2(try/except)/T4(回落);SC4 **真-LLM 生成闭环**→T5;SC5 **默认开+零网络**→T1(默认 True)/T4(`hyde_llm` 仅 gateway 建);SC6 仅主 retrieve→T4(enumerate/cases 不接);SC7 红线无臆造→T2(不产出 `clause_id`)+既有 `test_evidence_guards` 不破。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序(T1∥T2∥T3→T4→T5→T6)· [x] 覆盖成功标准(SC1–SC7)· [x] T6 同步 RTM(N1❌→🟡)· [x] 测试基名全仓唯一(新 `test_hyde`/`test_hyde_integration`;扩 `test_query_config`)· [x] sparse/embedding_client/milvus_io/state/graph 零改 · [x] 默认零回归守护(T4)· [x] V0 未跑诚实记 🟡(不 overclaim 召回)
- [ ] **人工复核批准**
