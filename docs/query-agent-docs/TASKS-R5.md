# Tasks: R5 判定型路由 —— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-R5.md` + `PLAN-R5.md`(已批准:框定=clause直呈+LLM toggle、红线=形态+代码后检+§9.2接口、入口=复用 R3 桥接)。
> 约定:每任务 ≤5 文件、TDD(先断言后实现)、含验收+验证。**测试基名全仓唯一**(`test_framing`/`test_r5_review`/`test_r5_judgment`/`test_r5_judgment_integration`,均未占用)。
> **零契约改动(`review_required` 已存在)、零新依赖、默认零-LLM(stub)。** 集成 gate = **PG+Milvus+本地 BGE-M3**(同 R1/R3/R4)。八路**最后一路收官**。

- [ ] **T1:config toggles + `judge/framing.py`(红线核心 + 三段式,纯函数)** — Phase A
  - Acceptance:`config` +`judge_constituent_llm=False`/`judge_multimodel_review=False`;`strip_bare_conclusion(text)`:`_VERDICT`(复用 R1 违规/违法/合规/合法)+ `_TENTATIVE`(可能违反/疑似违规/涉嫌/倾向于不合规/构成违)→ 命中替 `_NEUTRAL`(不作判定);`build_framing(clauses, query, llm, qcfg)`:② **clause直呈**(零-LLM 默认,呈现命中条款适用边界+框定模板语)、`judge_constituent_llm` 开→ LLM 抽取适用前提/对象/行为类型(经 `strip_bare_conclusion`)、③ 固定"AI 辅助判断,建议人工复核"TEXT;**无 verdict 槽**。
  - Verify:`pytest query/tests/test_framing.py`(`strip_bare_conclusion` verdict+试探性→中性、纯依据文本不动;三段式结构无判定字段;clause直呈;LLM toggle 开/关)。零栈零模型。
  - Files:`query/query/config.py`、`query/query/judge/__init__.py`、`query/query/judge/framing.py`、`query/tests/test_framing.py`。

- [ ] **T2:`judge/review.py`(§9.2 多模型复核接口,toggle)** — Phase B
  - Acceptance:`review_tentative(blocks, citations, llm, qcfg)`:`qcfg.judge_multimodel_review` **关→passthrough**(原样返回);**开**→ 第二 LLM 校验各块试探性表述是否被 `citations` 支持,不支持→ `strip_bare_conclusion` 降"待核实"。模块级零 pipeline 导入(llm 经形参注入)。
  - Verify:`pytest query/tests/test_r5_review.py`(toggle 关 passthrough;开 + fake llm 返"不支持"→ 块降级中性;开 + "支持"→ 原样)。零栈零模型。
  - Files:`query/query/judge/review.py`、`query/tests/test_r5_review.py`。

- [ ] **T3:`judge/r5_judgment.py`(桥接入口 + 编排)** — Phase C
  - Acceptance:`resolve_cited_clauses(pg, case_dvids)`:`pg.get_case(dvid).cited_regulations` → `bridge.norm_ref` 键 → 反查外规条款 chunk(`doc_versions.doc_number` 归一匹配 + `chunks.clause_path_norm` 匹配,`version_status==effective`),**consumed-when-present** 默认空→`[]`;`answer_judgment(query, retriever, pg, llm, qcfg)`:桥接(`retrieve_cases`→resolve)∪ hybrid(`retrieve`,drop_degraded 就地)→ 空→`refuse_coverage`→ `fetch_anchors`(①)→ `build_framing`(②③)→ `review_tentative`(§9.2)→ `QueryResult(JUDGMENTAL, review_required=True, citations=①, answer_blocks=[②,③])`。
  - Verify:`pytest query/tests/test_r5_judgment.py`(fake retriever/pg/llm:`judgmental`+`review_required=true`、三段式块、桥接 consumed-when-present(cited 空→hybrid-only)、空→`refuse`、**默认无裸结论**、`judge_multimodel_review` toggle)。
  - Files:`query/query/judge/r5_judgment.py`、`query/tests/test_r5_judgment.py`。

- [ ] **T4:R5 集成(PG+Milvus+BGE-M3)** — Phase D 检查点
  - Acceptance:`test_r5_judgment_integration`:behavior 问句 → 三段式真数据、四级锚点 PG 权威、**断言输出无违规/合规裸结论**、**手插 `cited_regulations`** 验桥接入口(`session.get(Case, dvid).cited_regulations=[...]` → 命中外规条款入候选 → finally 复位 `[]`,同 R3/R4);autouse 幂等 `mio.connect()` 重连(R3/R4 踩坑预案)。
  - Verify:`pytest query/tests/test_r5_judgment_integration.py`(gate=PG+Milvus+BGE-M3;未起 skip;按 batch_id 反 FK 序清理或复用 `case_stack`)。
  - Files:`query/tests/test_r5_judgment_integration.py`(+ `query/tests/conftest.py` 如需 behavior 件 fixture)。

- [ ] **T5:graph 接线 + 八路全实装 + router 回归** — Phase E
  - Acceptance:`graph._r5_judgment` 节点替 placeholder(`_TERMINAL[JUDGMENTAL]="r5_judgment"`、`_build` 加节点+边、**`_PLACEHOLDER_NOTE` 清空**,懒导入 `answer_judgment` 传 `self._llm`/`self._qcfg`);**`_placeholder` 节点保留为防御兜底**(`_route_edge` 未知 route 仍落它);`test_graph` 删 R5 占位、加 `ask("二维码介绍开户是否违规")`→`judgmental`+`review_required`+**无裸结论**(fake);`test_router` 八路覆盖回归(judgmental 优先级)。**占位无剩**。
  - Verify:`pytest query/tests/test_graph.py query/tests/test_router.py`;端到端在 T4 集成验证。
  - Files:`query/query/graph.py`、`query/tests/test_graph.py`、`query/tests/test_router.py`。

- [ ] **T6:收尾(devlog/GAP/RTM/时间轴)+ 全仓门** — Phase F 收口
  - Acceptance:`query_devlog.md` 记 R5 决策(三段式无 verdict 槽、strip always-on verdict+试探性、桥接 resolver consumed-when-present、§9.2 toggle、§15-④ demo workaround)与踩坑;`GAP.md`(R5 ✅,**八路全实装**);**`RTM.md`** 更新挂 test_id:`R5-bridge`/`R5-mix`/`R5-elem`/`R5-3seg`/`R5-noraw`/`R5-render`→✅、`R5-review`/`§9.2`/`§9.2-r5`→🟡(接口+toggle,真复核留后续)、`§8.3`→✅、`§7.4`(R5 三段式)→✅、`§14-g`(核心目标不裸答)→✅、`RL-1` 维持 🟡(真复核)、`§15-④` 标注 demo workaround,覆盖摘要重算;`docs/devlog.md` 加阶段 R5;全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;R5 集成需 PG+Milvus+BGE-M3,**提交前模型门控全量**);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。

## 依赖与并行
T1(framing+config,红线叶子)→ T2(review,依赖 strip)→ T3(编排,依赖 T1+T2)→ T4(集成,依赖 T3,真栈)∥ T5(接线,依赖 T3)→ T6(收尾+全仓门)。T1 的 `strip_bare_conclusion` 是红线核心、最先且全覆盖。

## 覆盖 SPEC-R5 §8 成功标准
SC1 judgmental+review_required+三段式→T3/T4/T5;SC2 **不出裸结论红线**(verdict+试探性)→T1(strip)+T3/T4(端到端断言);SC3 构成要件框定 clause直呈+LLM toggle→T1;SC4 桥接入口 consumed-when-present→T3/T4;SC5 §9.2 复核接口 toggle→T2;SC6 四级锚点 PG+零-LLM→T3/T4;SC7 graph 八路全实装+router→T5;SC8 集成+全仓门+DAG→T4/T5/T6。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序 · [x] 覆盖成功标准(SC1–SC8)· [x] T6 同步更新 RTM(维护规则)· [x] 测试基名全仓唯一
- [ ] **人工复核批准**
