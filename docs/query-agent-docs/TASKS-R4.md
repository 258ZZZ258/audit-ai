# Tasks: R4 多文档列举 —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-R4.md` + `PLAN-R4.md`(已批准:过滤=Milvus 标量+E1 义务、输出=TABLE+citations)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。**测试基名全仓唯一**(`test_dimensions` 已被 R6 占用 → R4 用 `test_listing_dimensions`)。
> **唯一承重改动 = `milvus_io.search` 加 `extra_expr`(add-only,T3 隔离守等价);零契约改动、零新依赖、零 LLM。** 集成 gate = **PG+Milvus+本地 BGE-M3**(同 R1/R3)。

- [ ] **T1:`listing/dimensions.py`(规则维度抽取,纯函数)** — Phase A
  - Acceptance:`EnumSpec`(frozen:`chunk_type_pref` bool 默 True / `biz_domains` / `entity_types` / `obligation_only`);`extract_enum_spec(query, biz_terms=(), entity_terms=())`:`obligation_only`= query 含 **"要求/义务/必须/应当/禁止/不得"**(Q3)、**"制度/规定/哪些" 不触发**;`biz_domains`/`entity_types`=`extract_terms`(词典子串,**只返词典成员**,dict 未注入→空);`chunk_type_pref`=True(Q5)。
  - Verify:`pytest query/tests/test_listing_dimensions.py`(义务意图触发/不触发、词典抽取、**非词典恶意串→不进 spec**;零栈零模型)。
  - Files:`query/query/listing/__init__.py`、`query/query/listing/dimensions.py`、`query/tests/test_listing_dimensions.py`。

- [ ] **T2:`listing/r4_listing.build_milvus_expr`(防注入 expr,纯函数)** — Phase B(安全核心)
  - Acceptance:字段名白名单 `{chunk_type, biz_domain, entity_type}`——**只此三名可入 expr**;`build_milvus_expr(spec)→str|None`:`chunk_type_pref`→`chunk_type == "clause"`(硬值);`biz_domains`非空→`array_contains_any(biz_domain, [<词典值>])`、`entity_types`同理(Q4,**仅抽到词典词才加**,避 E2 空数组 over-filter);AND 连接;全空→`None`。模块级**零 pipeline 导入**(可零栈测)。
  - Verify:`pytest query/tests/test_r4_listing.py::<安全节>` —— **安全断言**:expr 字段名 ∈ 白名单、`biz/entity` 值 ∈ 注入词典;**恶意 query 文本(`"; drop"`/`" or 1=1"`)不进 expr**(非词典成员被丢);空 spec→None;`chunk_type` expr 形正确。零栈零模型。
  - Files:`query/query/listing/r4_listing.py`(先只落 `build_milvus_expr`)、`query/tests/test_r4_listing.py`。

- [ ] **T3:`milvus_io.search` 加 `extra_expr`(add-only,承重隔离)** — Phase C(守等价)
  - Acceptance:`search(..., extra_expr: str | None = None)`:`clauses` 末尾 append `extra_expr`(非空时)→ `" and ".join`;hybrid 与 dense-only 兜底**两路都带** `extra_expr`;**`extra_expr=None` 时 `SearchResult.expr` 与原 byte 等价**(不回归 R1/R3/R6)。
  - Verify:`pytest pipeline/tests/test_milvus_search_expr.py` —— `extra_expr` 与 `status`/`corpus` **AND 拼接**正确;**`extra_expr=None` expr 等价**;两路兜底带 expr。**mock collection 断言 expr 串**(不需真 Milvus)。
  - Files:`pipeline/pipeline/index/milvus_io.py`、`pipeline/tests/test_milvus_search_expr.py`。

- [ ] **T4:`retrieve_enumerate` + config + `answer_enumerate`(编排,纯部分)** — Phase C/D
  - Acceptance:`hybrid.retrieve_enumerate(query, *, extra_expr, topk, partition_topk)`(分区配额循环 + 传 `extra_expr`,**不改 `retrieve`**);`config` +`enumerate_partition_topk=50`/`enumerate_topk=50`(Q2);`r4_listing.fetch_obligation_chunk_ids(pg, ids)→set`(clause_tags `is_obligation`|`deontic_type` 非空);`answer_enumerate(query, retriever, pg, qcfg)`:检索→(obligation_only)E1 后过滤(**oblig 空→降级不过滤+note**,consumed-when-present)→空→`refuse_coverage`→非空→`fetch_anchors`→**按 `doc_version` 聚合**(制度名/文号/命中条款路径/页码/状态)→`TABLE`(`{columns,rows,note}`,`stream=False`)+`citations[]` 四级锚点+**边界声明 note**(不保证穷举外规);`route_type=enumerate`。
  - Verify:`pytest query/tests/test_r4_listing.py`(fake retriever/pg:**按 doc 聚合**、E1 后过滤、E1 空→降级、E2 空→不过滤、空→拒答、边界 note 在)。
  - Files:`query/query/retrieve/hybrid.py`、`query/query/config.py`、`query/query/listing/r4_listing.py`、`query/tests/test_r4_listing.py`。

- [ ] **T5:R4 集成(PG+Milvus+BGE-M3 合成多文档)** — Phase D 检查点
  - Acceptance:fixture 入索引 **2–3 个同主题 `doc_versions`**(各含条款 chunk + 嵌入,标 `chunk_type=clause`/合成 `biz_domain`)→ `answer_enumerate`:**跨文档聚合**(各 doc 一行)、四级锚点真数据、**E1 义务过滤**(手插 `is_obligation` clause_tags 验证)、**Milvus `extra_expr` 真过滤**(`chunk_type`/`biz_domain`);**autouse 幂等 `mio.connect()` 重连**(R3 踩坑预案,防全局别名断开)。
  - Verify:`pytest query/tests/test_r4_listing_integration.py`(gate=PG+Milvus+BGE-M3;栈/模型未起 skip;按 batch_id 反 FK 序清理)。
  - Files:`query/tests/test_r4_listing_integration.py`(+ `query/tests/conftest.py` 加合成多文档索引 fixture)。

- [ ] **T6:graph 接线 + ENUMERATE 节点 + 端到端 + router 回归** — Phase E
  - Acceptance:`graph._r4_listing` 节点替 placeholder(`_TERMINAL[ENUMERATE]="r4_listing"`、`_build` 加节点+边、`_PLACEHOLDER_NOTE` 删 ENUMERATE,**懒导入** `answer_enumerate`;复用 `state.scene` 抽的 matters/entity 注入 dimensions);`test_graph` 删 ENUMERATE 占位 parametrize、加 `QueryAgent.ask("哪些制度规定了客户身份识别")`→`route_type=enumerate`(fake pg,零栈);**占位剩 R5 一路**;`router`/golden 回归(enumerate 触发词不串 R1)。
  - Verify:`pytest query/tests/test_graph.py query/tests/test_router.py`;端到端在 T5 集成验证。
  - Files:`query/query/graph.py`、`query/tests/test_graph.py`、`query/tests/test_router.py`。

- [ ] **T7:收尾(devlog/GAP/RTM)+ 全仓门** — Phase E 收口
  - Acceptance:`query_devlog.md` 记 R4 决策(Milvus expr 白名单防注入、`extra_expr` add-only 守等价、E1 PG 后过滤 consumed-when-present 降级、E2 预过滤"仅抽到词才加"、按 doc 聚合、不保证穷举外规边界)与踩坑;`GAP.md` 勾 R4(八路仅剩 R5 占位);**`RTM.md` 更新 → 挂 test_id**:`R4-filter`/`R4-mode`/`R4-bound`→✅、`§2-entity`/`§2-biz`/`§2-chunktype`/`§2-tagsE1`/`§5.3`→🟡(机制落地、consumed-when-present),覆盖摘要重算;全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;R4 集成需 PG+Milvus+BGE-M3,**提交前模型门控全量**);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`。

## 依赖与并行
T1(规则)∥ T2(expr 安全,纯)∥ T3(milvus 承重,独立)→ T4(依赖 T1+T2+T3)→ T5(依赖 T4,真栈)∥ T6(依赖 T4,接线)→ T7(收尾+全仓门)。
T1/T2/T3 可并行写(纯函数 + 隔离承重);T5 集成与 T6 接线共享真栈。

## 覆盖 SPEC-R4 §8 成功标准
SC1 route_type=enumerate+TABLE+citations→T4/T5/T6;SC2 枚举高 k+按 doc 聚合不激进截断→T4/T5;SC3 Milvus 标量预过滤+`extra_expr=None` 等价→T3(等价)/T4(expr 构造)/T5(真过滤);SC4 E1 义务后过滤 consumed-when-present→T4/T5;SC5 **安全红线**(白名单+恶意串不进 expr)→T2;SC6 边界声明+空→拒答→T4;SC7 零 LLM/逐字命中四级锚点→T4/T5;SC8 集成绿+全仓门+DAG→T5/T6/T7。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC8)· [x] T7 同步更新 RTM(维护规则)· [x] 测试基名全仓唯一(`test_listing_dimensions`/`test_r4_listing`/`test_r4_listing_integration`/`test_milvus_search_expr`)
- [ ] **人工复核批准**
