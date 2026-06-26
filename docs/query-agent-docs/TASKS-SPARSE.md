# Tasks: §5.4 sparse 精确通道(发文字号提权 + 词典扩展)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-SPARSE.md` + `PLAN-SPARSE.md`(已批准:范围=提权+扩展 v0-draft seed、
> 机制=查询层 sparse token 提权保持 RRFRanker、应用=主 retrieve R1/R5)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。**测试基名全仓唯一**(`test_sparse_boost`/`test_sparse_boost_integration` 未占用;config 扩既有 `test_query_config`)。
> **零承重(pipeline)改动 = `milvus_io.search` 签名不变;零新依赖;双开关默认关 byte 等价。§7 已核实 `seed_dicts` 显式读命名文件、新 CSV inert。** 集成 gate = **PG+Milvus+BGE-M3**。

- [ ] **T1:`sparse_boost.py` 纯函数(detect / load / augment,零栈零模型)** — Phase A
  - Acceptance:`detect_doc_numbers(query)`(`to_halfwidth` 后 regex 命中机关代字`〔年〕第?序号号` + 制度全名`《…》`,去重保序);`load_scenario_terms(path)`(CSV `oral_term,legal_terms`,`legal_terms` 按 `|` 拆 → dict;**文件缺/空/坏行 → `{}`/跳过**,consumed-when-present);`_matched_legal_terms(query, terms)`(口语词子串命中→法言词扁平去重);`augment_sparse(query, base_sparse, *, embed, scenario_terms={}, docnum_factor=2.0, expand_factor=1.0, docnum_on=False, expand_on=False)`:装配 spans → **无命中返 `base_sparse` 同一对象**;有命中 → `dict(base_sparse)` + `embed(spans)` 选择性 token **加权并入**(`out[t]=out.get(t,0)+f*w`);**只返 sparse、不碰 dense**。模块级**零 pipeline 承重导入**(仅 `to_halfwidth`,embed 注入 duck-typed)。
  - Verify:`pytest query/tests/test_sparse_boost.py`(**fake embed**)——detect 命中 `银保监发〔2021〕5号`/`证监发〔2020〕第53号`/`财会〔2017〕22号`/半角`(2023)5号`/`《XX管理办法》` + **不误命中**普通句/纯数字/全角半角归一;`load_scenario_terms` 解析 + 缺/空→`{}`;`augment_sparse` 命中 token 按 `factor` 并入、**双关关/无命中→返回 `base_sparse` 同一性(byte 等价守护)**、`docnum_on`/`expand_on` 各自独立。零栈零模型。
  - Files:`query/query/retrieve/sparse_boost.py`、`query/tests/test_sparse_boost.py`。

- [ ] **T2:`config` 加字段 + env(add-only)** — Phase B(可与 T1 并行)
  - Acceptance:`QueryConfig` +`docnum_boost: bool=False`、`docnum_boost_factor: float=2.0`(⚠V0)、`scenario_expand: bool=False`、`scenario_expand_factor: float=1.0`(⚠V0)、`scenario_terms_path: str`(默认锚 `<repo>/seeds/dict_scenario_terms.csv`,同 `DEFAULT_CONFIG_DIR` 用 `parents[2]`);`_apply_env` +`QUERY_DOCNUM_BOOST`/`QUERY_SCENARIO_EXPAND`/`QUERY_SCENARIO_TERMS_PATH`(bool 由 pydantic 强转 `"1"/"true"`)。**add-only,默认关 → 既有行为零变化**。
  - Verify:`pytest query/tests/test_query_config.py`(默认值;`QUERY_DOCNUM_BOOST=1`→`docnum_boost=True`;`scenario_terms_path` 默认锚 `<repo>/seeds`)。零栈。
  - Files:`query/query/config.py`、`query/tests/test_query_config.py`(扩既有)。

- [ ] **T3:`Retriever` 接线 + seed CSV(提权应用于主 retrieve)** — Phase C(依赖 T1+T2)
  - Acceptance:`Retriever.__init__` +`self._scenario_terms = load_scenario_terms(qcfg.scenario_terms_path) if qcfg.scenario_expand else {}`(关→`{}` 免 IO);`retrieve`:`emb=embed([query])[0]` 后,`if qcfg.docnum_boost or qcfg.scenario_expand: sparse = augment_sparse(...)` 否则 `sparse = emb.sparse` → `search(emb.dense, sparse, …)`(**`dense` 恒等、`search` 签名不变**)。**`retrieve_enumerate`/`retrieve_cases` 不动**(R4/R3 不接)。新增 `seeds/dict_scenario_terms.csv`(header `oral_term,legal_terms` + §3.2 示例:`代客理财,全权委托|受托理财`、`二维码介绍开户,违规招揽客户|居间介绍`、`见底到顶,对买卖时机的具体建议`;**v0-draft 待 §15⑥**)。
  - Verify:`pytest query/tests/test_sparse_boost.py`(retriever 级:**fake embed + fake milvus 捕获入参**)——双关关 → `search` 收到 `emb.sparse` **同一性** + `dense` **恒等**(byte 等价 + **只动 sparse** 守护);开 + fake → `search` 收到增强 sparse;`retrieve_enumerate`/`retrieve_cases` 入参 sparse 不变。
  - Files:`query/query/retrieve/hybrid.py`、`seeds/dict_scenario_terms.csv`、`query/tests/test_sparse_boost.py`(加 retriever 级用例)。

- [ ] **T4:集成(PG+Milvus+BGE-M3)** — Phase D 检查点
  - Acceptance:**提权** —— 索引含特定发文字号的多 chunk;查询该编号 → `docnum_boost=True` 目标 chunk 名次 **高于** `False`(断言 rank↑/进 topk);**扩展** —— seed `代客理财,…|受托理财`,索引仅含"受托理财"chunk,口语查"代客理财" → `scenario_expand=True` 召回、`False` 漏;**byte 等价** —— 双关关 → `retrieve` 与本轮前同序;未设 BGE-M3 模型 → **skip**(绝不联网);autouse 幂等 `mio.connect()` 重连。
  - Verify:`pytest query/tests/test_sparse_boost_integration.py`(gate=PG+Milvus+BGE-M3;缺则 skip;按 batch 反 FK 序清理或复用既有索引 fixture)。
  - Files:`query/tests/test_sparse_boost_integration.py`(+ `query/tests/conftest.py` 如需发文字号/法言词专用 fixture)。

- [ ] **T5:收尾(devlog/GAP/RTM/时间轴)+ 全仓门** — Phase E 收口
  - Acceptance:`query_devlog.md` 记决策(查询层 token 提权弃 WeightedRanker、只动 sparse、consumed-when-present、`seed_dicts` inert 核实)与踩坑;`GAP.md`(§5.4 ❌→✅;§8 资产 `dict_*` 加 `dict_scenario_terms` 行 v0-draft;§3 N2 桥接备注);**`RTM.md`** 挂 test_id:`§5.4`→✅、`R1`(发文字号提权部分)→✅/🟡、`dict_scenario_terms` 行,覆盖摘要重算;`docs/devlog.md` 加阶段。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;sparse 集成需 PG+Milvus+BGE-M3,**提交前模型门控全量**);`.venv/bin/ruff check .`(含 `alembic/versions` 若动,本切片不动迁移)。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(`sparse_boost` 纯函数)∥ T2(`config` add-only)→ T3(`Retriever` 接线 + seed,依赖 T1+T2)→ T4(集成,依赖 T3,真栈)→ T5(收尾+全仓门)。T1/T2 可并行(纯函数 + config 独立)。

## 覆盖 SPEC-SPARSE §8 成功标准
SC1 发文字号提权名次↑→T3(接线)/T4(集成);SC2 词典扩展召回↑→T3/T4;SC3 **双关 byte 等价 + 只动 sparse**→T1(augment 同一性)/T3(检查点 `dense` 恒等)/T4(集成同序);SC4 detect 覆盖+不误命中→T1;SC5 load consumed-when-present→T1;SC6 augment 纯函数 fake embed→T1;SC7 零网络 skip→T4;SC8 config add-only + env→T2;SC9 全仓门+DAG→T5。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC9)· [x] T5 同步更新 RTM(维护规则)· [x] 测试基名全仓唯一(`test_sparse_boost`/`test_sparse_boost_integration`;config 扩 `test_query_config`)
- [ ] **人工复核批准**
