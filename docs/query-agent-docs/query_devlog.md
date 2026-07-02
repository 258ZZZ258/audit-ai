# 制度查询智能体 — 开发记忆(决策 / 踩坑)

> 改 `query/` 前读本文件(lazy)。全链路叙事见 SDD 三件:`SPEC.md` / `PLAN.md` / `TASKS.md`。
> 上游设计:`docs/制度查询智能体_技术框架设计_v1_0.md`(v1.0,功能1)。

## 切片与状态

MVP 切片 = **R1 依据查询 + 覆盖感知拒答 + 八路路由/输出契约骨架**(spec-driven 四阶段门控产出)。
代码落 `query/`(audit-query)包,依赖 DAG `query → pipeline → common` 无环。Phase A–F 全过,
query 全量 **47 passed**(真栈 + 真 BGE-M3)/ 零网络默认(stub)/ ruff 全仓绿。

## 关键决策

- **编排用 LangGraph**(`graph.py`,§1.2 原生底座):节点写成**纯函数薄封装**(understand/generate/refuse
  不 import langgraph),`graph.py` 只装配节点+条件边——换底座纯函数照搬(PLAN §2.5-1)。完整设计的
  R2–R6/多轮/案例桥接/§9.2 复核都是"加节点+边"。LangGraph 1.x:`StateGraph(dataclass)` + 节点返回
  dict 更新 + `invoke` 返回 **dict**(`out["result"]`)。
- **可拓展性=设计保真接口 + 占位实现**(PLAN §2.5):路由现在就**分满 8 类**、§10 契约**全字段**、
  `sufficiency` 出参带 `exhausted_scope`(§8.1 接口保真,实现先务实)、`QueryState` 一次定全。R2–R6
  二次开发 = 填 handler,不动既有。
- **检索复用 pipeline 脊柱**(不重造):`milvus_io`(dense+sparse + RRF + status 前置过滤 + dense-only
  兜底)+ `embedding_client`(查询向量化)+ PG `chunks/doc_versions` 四级锚点回查。
- **LLM 可配置工厂**(`llm/`,Protocol + `make_llm_client`):默认 `stub`(零网络、确定性,从上下文
  `[[clause_id:X]]` 选 id)、`gateway` 懒导入复用 `pipeline.llm_client`(PR#4)。与摄取侧"LLM 默认全关"一致。
- **红线落地**:引用真实性 = prompt 约束(§7.1)+ `select_faithful` **代码级兜底**(答案只能引用上下文
  clause_id);无裸结论 = prompt + 断言(真 LLM 由 §9.2 复核兜,本切片未实装);可解释拒答 = 覆盖感知
  拒答附 exhausted_scope + 最接近 N 条。

## 踩坑

- **flat 布局命名空间遮蔽**:从**仓库根 cwd** 跑 `python -c "import query"` → `__file__=None`(外层
  `query/` 目录无 `__init__.py` 被当 namespace 包)。与 `pipeline`/`eval` 行为一致;pytest(pythonpath)
  与非根 cwd 下解析正常。非 bug。
- **`StrEnum` 而非 `(str, Enum)`**:py311 下 ruff UP042 要求 `enum.StrEnum`(本仓既有 idiom)。
- **entity_type/biz_domain 过滤暂缓**:`milvus_io.search` 未暴露附加 expr、`_OUTPUT_FIELDS` 不含该两列
  → MVP 走不了条件过滤(§5.3 仅 status 前置生效)。升级路径:pipeline 侧给 search 加附加 expr/output_fields(另议)。
- **stub 必须从上下文选 clause_id**:否则引用真实性测试空跑;约定标记 `[[clause_id:X]]`,citation_inject
  产出、stub 解析,两端闭环。
- **CJK 注释行宽**:ruff E501 按字符宽计(CJK=1),仍易超 100 → 独立行/缩短(本仓通病)。
- **集成测试模型门控**:连真栈 + ingest 需 BGE-M3;`PIPELINE_EMBEDDING_MODEL` 指向 modelscope 本地
  缓存(完整),未设则集成自动 skip(绝不联网)。

## MVP 简化 / 未实装(见 SPEC §9 Open Questions)

- HyDE(N1)、N0 多轮归并、问题分解(N3)、案例桥接(§6.3)、多模型复核(§9.2):未做。
- R2–R6:仅路由占位(诚实标 route_type + "暂未实装",不裸答)。
- 重排:默认 `none`(用 RRF 序);bge-reranker 为可选接缝(待本地模型)。
- 依赖未就绪资产:`dict_scenario_terms`/`dict_intent_routes` 未建(路由用内置规则种子);
  `clause_references` 空表(R1 不依赖多跳)。
- `confidence` 口径占位(§Q8 待标定),不参与任何闸门。

## R2 变更查询(第二轮 spec-driven,SPEC/PLAN/TASKS-R2)

- **切片**:R2 实装(替占位)——定位(R1 检索 top1)→ 版本对回查(logical 的 effective=current + supersedes 前驱)→
  **条款级 diff**(`change/version_diff.py`,按 clause_path_norm 对齐,added/removed/changed)→ 修订原因回查 → §6.2 四栏 §10 契约。**全程零 LLM**。
- **决策**:`resolve_version_pair` 一律取 logical 的 effective 为 current(与命中哪版无关);只 diff **最近一跳**前驱;
  修订原因**仅回查 `revision_notes`**,缺失明示"修订说明未提供"、**绝不 LLM 推测**(§6.2 红线);degraded 块不入 diff/引用。
- **踩坑**:`diff_clauses` 按 clause_path_norm **字符串序**排序——中文数字按 Unicode 码点(一<三<二),非数字序;
  测试只验"确定性排序"(`sorted()`),数字序属后续 polish。`revision_notes` ingest 不填(仅人工录入),集成测试手插一条。
- **未做(SPEC-R2 §0)**:背景栏(同期案例,明示"未纳入本期")、多跳历史、条款内字句级 diff、修订条目↔diff 的 LLM 对齐。

## R3 相似案例 + 案例桥接(第三轮 spec-driven,SPEC/PLAN/TASKS-R3)

- **切片**:R3 实装(替占位)——(a) `route_type=case`:case 分区(P-CASE)语义检索 → 按 `doc_version_id`
  **去重一案一卡** → PG `cases`/`doc_versions` 要素回填 → `CASE_CARD` 卡片;(b) **附挂通道**:R1 充分
  evidence 答复尾挂相关案例卡(语义 ∪ 精确反查);(c) **精确反查桥接原语**(`bridge.cases_for_clauses`)。
  **全程零 LLM**。新增 `query/query/case/`(case_card / bridge / r3_case)。
- **决策**:
  - **consumed-when-present**(关键):`cited_regulations` 是 L2 LLM 字段、**默认关**(`case_extract.py:131` 留 `[]`)
    → 精确反查**默认无数据**;只**消费**已有值,默认路径索引空 → 反查 `[]`、**降级语义-only**、**绝不臆造外规引用**。
    fixture **手插** `cited_regulations`(仿 R2 手插 revision_notes)验证机制。`§15-⑤` 不阻塞本轮。
  - **一案一卡**:case 分区多 chunk(case_summary + case_section)按 `doc_version_id` 去重保高分(`_dedup_by_case`)。
  - **附挂边界**(§6.3):仅**充分 evidence** + **非 `definition`(概念判断型)**附挂;拒答/降级不挂、追加块不改 R1
    引用核心、可关。配置 `[query] attach_cases`(默认 on)/`attach_topk`(3)——入 **QueryConfig 非 pipeline `[toggles]`**。
  - **`norm_ref` 匹配契约**(Q3):发文字号/文号 + `clause_path_norm` 归一(复用 chunking 口径);`cited_regulations`
    单条目 = **dict(`doc_no`+`clause_path`)**,非 dict / 缺键跳过;**真实 JSONB shape 随 L2 对齐落地校准**(§15-⑤)。
  - **CASE_CARD content = 结构化 JSON 字符串**(Q4,`stream=False` 原子块);要素逐字 PG 权威,**L2 空字段省略不臆造**。
- **踩坑**:
  - `chunk_type=case_summary` 主命中面**无法 milvus 强过滤**(`_OUTPUT_FIELDS` 不含 `chunk_type`)→ 以**一案一卡**去重替代(GAP #12)。
  - 集成 fixture 案例件 **B 模式自动放行**:`cross_check` 仅在「manifest 非空 ∧ L1 候选非空 ∧ 不一致」才冲突,故
    首段=manifest 标题(免 title 冲突)、body **无可抽文号**(`meta.doc_numbers` 空→免 doc_number 冲突)、
    manifest `issue_date=None`(免日期冲突)、`issuer=INTERNAL`(不解析到 dict code→免 issuer 冲突)。
  - **`upsert_case` 是 `s.merge`** → 传部分字段会把其余列 **NULL 掉**;手插 `cited_regulations` 改用
    `session.get(Case, dvid).cited_regulations = [...]` 直改单列(非 merge),并 finally 复位 `[]` 不污染会话级 fixture。
  - **P-CASE QC** 只跑锚点(4)/文本质量(6),`cases` 字段完整率是**批次度量非 s2 拦截**(`qc/indicators.py`)→ 案例件易自动放行。
  - **pymilvus 全局连接顺序依赖**:`test_r2_change_integration` 的**模块级** `stack` fixture teardown `mio.disconnect()`
    断开全局 `default` 别名连接(与会话级 `indexed_stack`/`case_stack` 共享);R3 集成按字母序在 r2 **之后**跑、
    是首个在该断开后检索 Milvus 的用例 → `ConnectionNotExist`(单跑/r3 先跑则不暴露)。修:R3 集成文件 autouse
    幂等 `mio.connect()` 重连。**系统性脆弱**(共享全局别名 + 模块级 disconnect),后续 query 集成新增检索用例须注意。
- **未做(SPEC-R3 §0)**:桥接-as-入口(behavior→R5 检索入口,R5 占位/§15-④ 阻塞)、L2 `cited_regulations` 生产、
  bge-reranker、`cited_regulations`→四级 `citations` 解析(Q6,默认空路径本就不加)、R6 统计型 cases SQL。

## R6 统计型(第四轮 spec-driven,SPEC/PLAN/TASKS-R6)

- **切片**:R6 实装(替占位)——`route_type=statistical`:**规则维度抽取**(`stats/dimensions`)→ **参数化 SQL**
  (`stats/sql_builder`,白名单 + bound params)over `cases` → **TABLE** 输出(`stats/r6_stats`)。两模式:聚合(GROUP BY
  维度 → count/sum(amount) 降序)+ 列表(date 过滤 → 按 `penalty_date` 降序列案例)。**全程零 LLM、不走向量检索**(§6.6)。
- **决策**:
  - **防注入(红线)**:聚合/过滤列**只来自 `GroupBy` 白名单枚举 → 真实 Column**(`_GROUP_COL` dict);过滤值经
    SQLAlchemy 算子**自动绑定为 bound params**;用户问句只经规则映射到枚举/标量,**绝不拼接进 SQL**。`test_sql_builder`
    编译断言 parametrized + 恶意输入(`"; DROP TABLE"`)落默认枚举不进 SQL 结构。**拒任意 SQL / 拒 LLM 生成 SQL**。
  - **规则维度抽取**(Q1):聚合词优先于列表词、歧义默认聚合(Q8);group_by 按序匹配(RESPONDENT_TYPE 的"对象类型"
    先于 ORG 的"机构",避免误吞);metric count / "金额·罚款·罚没·总额"→sum_amount(Q6);年过滤 regex + "以来"判 from/eq。
  - **`violation_category` consumed-when-present**(Q2):L2 默认空 → 聚合 over present;含 NULL 桶 → 表注"违规事由未标注
    (L2 默认关)",**不臆造**;L1 维度(年/机构/对象/金额)有真数据。
  - **TABLE content** = 结构化 JSON `{columns, rows[, note]}`(`stream=False`,沿用 R3 Q4);`route_type=statistical`、citations 空。
  - **配置归位**:R6 无新 config(维度/metric 规则固定、`_LIST_CAP` 模块常量)。
- **踩坑**:
  - **集成 PG-only**:R6 不需 Milvus/embedding → gate 仅 PG(比 R3 轻、0.16s)。合成 cases 用**哨兵未来年 2098/2099 + 唯一名**,
    所有测试问句带年过滤 → 经 `func.extract('year')` 与全表其它 cases **隔离**,计数/排序确定(否则全表聚合会被残留数据污染)。
  - **FK 链 fixture**:`cases`→`doc_versions`→`documents`→`import_batches`;直插需按 FK 序 + `s.flush()`(无 relationship,
    SQLAlchemy 仍按 FK 依赖排序,但逐 flush 最稳),反序清(Case→DocVersion→Document→ImportBatch)。`DocVersion` 必填
    `source_format`/`source_hash`/`raw_object_key`(无默认)。
  - **`func.extract('year', date)`** 跨方言:单测只断言编译 SQL 结构/params(postgresql dialect),真值跑留集成连真 PG。
- **未做(SPEC-R6 §0)**:LLM 维度抽取、违规类别字典评审(§6.6 前提,consumed-when-present 不阻塞)、`org_like` 从 NL 抽取
  (sql_builder 支持、dimensions 暂不填)、列表型标题外的下钻链接、占比/多 metric 组合、场景 5 舆情后台报告。
- **Codex 复审修复(3 warning,均实 bug、测试漏覆盖)**:
  - **列表型统计未进 STATISTICAL 路由**:`classify._STATISTICAL` 缺"处罚有哪些"类列表触发词 → "2024年以来的处罚有哪些"
    误落 evidence/R1(R6 单测直调 `answer_stats` 绕过路由,漏检)。修:加列表统计触发词 + golden + `test_router` 回归。
  - **缺可见性过滤**:R6 直聚合 `cases`,未 join `doc_versions` 过滤 `pipeline_status==INDEXED ∧ version_status==effective`
    → 把 META_REVIEW(cases 在 S4 即 upsert)/superseded/upcoming 计入,绕过查询侧 `status=effective` 强过滤。修:聚合+列表
    两路统一 join 可见性条件;集成 fixture 补不可见哨兵断言排除。**集成 fixture 原 `doc_versions` 默认 `REGISTERED` 故须显式置 INDEXED**。
  - **YEAR 聚合 Decimal 序列化崩**:PG `EXTRACT(year)` 返 `Decimal`,`json.dumps` 抛 TypeError(逐年路径无集成测,漏检)。
    修:`cast(extract..., Integer)` + `_fmt` Decimal 兜底 + 逐年集成测。

## R4 多文档列举(第五轮 spec-driven,SPEC/PLAN/TASKS-R4)

- **切片**:R4 实装(替占位)——`route_type=enumerate`:**规则维度抽取**(`listing/dimensions`)→ **枚举模式高 k 检索**
  (`hybrid.retrieve_enumerate`,不激进截断)→ **过滤**(① Milvus 标量预过滤 `chunk_type=clause`+`biz_domain`+`entity_type`,扩
  `milvus_io.search` 加 `extra_expr`;② E1 义务 PG 后过滤 `clause_tags.is_obligation`)→ **去重+按 `doc_version` 聚合** →
  **TABLE**(制度名/文号/命中条款/页码/状态)+ **citations[]** 四级锚点(`listing/r4_listing`)。**全程零 LLM**。
  新增 `query/query/listing/`(dimensions/r4_listing)。**八路仅剩 R5 占位**。
- **决策**:
  - **过滤范围(AskUserQuestion 已定)**:Milvus 标量 + **E1 义务**(query 侧首次消费 `clause_tags`)。E1(零-LLM **默认开**)
    有真数据 → 义务过滤有效;E2 `entity_type`(默认关)+ `biz_domain` 走 **consumed-when-present**。
  - **防注入(红线)**:`build_milvus_expr` 字段名只来自白名单 `_ALLOWED_EXPR_FIELDS`(chunk_type/biz_domain/entity_type)→
    `array_contains_any`;值经 `json.dumps` 转义(纵深);raw user 串在 `dimensions.extract_enum_spec` 即被**词典过滤**
    (`extract_terms` 只返词典成员),绝不到 expr。`test_r4_listing` 断言恶意 query 文本不进 spec/expr。
  - **`milvus_io.search` add-only**:加可选 `extra_expr`(append 到 status/corpus 子句),hybrid 与 dense-only 兜底两路都带;
    **`extra_expr=None` 与原行为 byte 等价**(`test_milvus_search_expr` 守不回归 R1/R3/R6)。承重检索层唯一改动。
  - **两道 consumed-when-present 降级**(机制不同):**E1 PG 后过滤可后验** → `is_obligation` 空集 → **降级不过滤 + note**
    (不丢光);**E2 Milvus 预过滤无法后验** → **仅当 query 抽到词典词才加** entity/biz 子句(dict 未注入→不加,避免空数组 over-filter)。
  - **义务意图触发**(Q3):问句含「要求/义务/必须/应当/禁止/不得」→ `obligation_only`;「制度/规定/哪些」**不**触发
    (避免"列出制度"被误缩为只剩义务条款)。
  - **枚举高 k**(Q2):`enumerate_partition_topk/enumerate_topk` 默认 50/50(放大默认 25/8),config 化、⚠ V0 标定;
    `retrieve_enumerate` 独立方法、不改 R1 `retrieve`(零回归)。
  - **`chunk_type=clause` 硬偏好**(Q5):列举=条款,排除 table(可退软偏好,留接缝)。
  - **TABLE content = JSON `{columns, rows, note}`**(沿用 R3/R6),`stream=False`;非空附**不保证穷举外规**边界声明
    (§6.4+§15-③,不向甲方承诺);空结果 → 覆盖感知拒答(`refuse_coverage`,exhausted_scope 非空)。
  - **`fetch_obligation_chunk_ids` 与 cli `_obligation_chunk_ids` 同义**(均查 `clause_tags.tag_type=="is_obligation"`)——
    查询侧不 import cli,独立实现保 DAG;语义一致(presence=义务)。
- **踩坑**:
  - **`listing` 模块级零 pipeline 导入**:`r4_listing` 就地 inline degraded 过滤(不 `from query.retrieve.hybrid import drop_degraded`,
    因 hybrid 模块级拉 pipeline),Retriever/PgIO 经形参注入 → 纯函数 `build_milvus_expr` 可**零栈测**。
  - **`test_dimensions` 基名已被 R6 占**(全仓唯一约定)→ R4 用 `test_listing_dimensions`。
  - **`biz_domain` Milvus 存的是 manifest code**(`[dv.biz_domain]`,如 `["DISCLOSURE"]`),非中文事项名 → 集成验 biz 过滤
    用 code(query 含 code + `biz_terms=[code]`);负例不存在 code → 真 Milvus 0 命中 → 拒答(证 `extra_expr` 真下推)。
  - **E1 集成靠自然打标**:E1 义务 enrichment 在 B 模式 ingest 自动跑(`cli.py:145`)→ 合成 doc_a 第二条含「应当」自动得
    `is_obligation`、doc_b 无标记 → 义务查询断言 doc_b **被剔除**(不依赖手插,稳健于高 k 噪声)。
  - **pymilvus 全局别名顺序**:`test_r4_listing_integration` 按字母序在 r2/r3 后跑,autouse 幂等 `mio.connect()` 重连(沿用 R3 预案)。
- **未做(SPEC-R4 §0)**:LLM 维度抽取;E1 细粒度数值过滤(`deontic_type`/`norm_duration_days` 期限);`entity_type` 真数据强过滤
  (E2 默认关);sparse 发文字号提权(§5.4)、bge-reranker(§5.5);`clause_references` 多跳;穷举外规保证(§15-③ 声明不做);
  Excel 导出(§11)、下钻链接;P-QA/P-CASE 分区(列举只打 P-INT/P-EXT)。
- **Codex 复审修复(2 warning,均实缺陷)**:
  - **图节点丢弃 `state.scene` 抽取项**:`_r4_listing` 未把 N2 已抽的 `matters`/`entity_types` 传 `answer_enumerate` →
    `query ask` 路径永远只下推 `chunk_type`,biz/entity 标量过滤仅在直调测试路径生效(违 T6 验收"复用 state.scene 注入")。
    修:节点转发 `scene.get("matters")`/`entity_types`;dict 接入后图路径自动生效 + `test_graph` 加转发回归。
  - **缺锚点静默成功**:`fetch_anchors` 后未复检,候选 PG 缺锚点(写序不一致)时返 `route_type=enumerate` 但 rows/citations
    空(违 SC1"TABLE+四级 citations"、红线"锚点 PG 权威")。修:`rows` 空 → `refuse_coverage` 降级 + `test_missing_anchors_refuses`。

## R5 判定型路由(第六轮 spec-driven,SPEC/PLAN/TASKS-R5)—— 八路收官

- **切片**:R5 实装(替最后一个占位)——`route_type=judgmental` + `review_required=true`。桥接入口(复用 R3
  `retrieve_cases`→`cited_regulations` 反查外规条款,consumed-when-present)∥ hybrid(内规+外规)→ **三段式硬约束**
  (① 依据条款四级锚点 ② 构成要件框定 ③ AI辅助/人工复核标识,**无 verdict 槽**)→ §9.2 复核接口。**默认零-LLM**。
  新增 `query/query/judge/`(framing/review/r5_judgment)。**八路全实装,无占位**。
- **决策**(AskUserQuestion 2026-06-24):
  - **框定生成 = clause直呈 + LLM toggle**(`judge_constituent_llm` 默认关):② 默认结构化罗列命中条款适用边界(零-LLM);
    开 toggle 时 LLM 抽取适用前提/对象/行为类型(经 `strip_bare_conclusion` 后检)。
  - **不出裸结论(红线)= 形态(无 verdict 槽)+ 代码后检 always-on + §9.2 接口**:`strip_bare_conclusion` 覆盖
    verdict 词(违规/违法/合规/合法)+ 试探性表述(可能违反/疑似违规/涉嫌/倾向于不合规/构成违)→ 替中性"不作判定"。
  - **桥接入口 = 复用 R3**:`resolve_cited_clauses(pg, case_dvids)` 把 `cited_regulations`{doc_no,clause_path} 经
    `bridge.norm_ref` 归一 → `doc_versions.doc_number` 匹配 + `chunks.clause_path_norm` 匹配 → 外规条款 chunk;
    **consumed-when-present** 默认空→`[]`→降级 hybrid-only。
  - **§9.2 多模型复核 = 接口+toggle**(`judge_multimodel_review` 默认关):关→passthrough(always-on 保障靠代码后检+形态);
    开→第二 LLM 校验试探性是否被引用支持,不支持→降"待人工核实"。
- **关键洞察 / 踩坑**:
  - **安全文案有意避开 verdict 词**:`_NEUTRAL`/`_FRAMING_LEAD`/`_REVIEW_NOTICE` 用"不作判定/不作认定结论"等中性
    表述,**不含违规/合规字面** → "输出无裸结论"可被钝断言(`assert 无 verdict 词 in blocks`);query 含"违规"
    不回显进块(框定只引条款身份,不回显问句)。形态无 verdict 槽是结构保障,strip 是 LLM 路径兜底。
  - **strip 只施于 LLM 路径**:clause直呈(默认)是确定性安全构造(只列条款身份),不过 strip;LLM 框定输出过 strip。
    避免把合法文档标题/条款身份误伤(钝过滤宁伤 LLM 输出、不伤确定性构造)。
  - **§9.2 复核逐块施于全部块**:含 ③ 固定标识块;默认关 passthrough 无影响,开时 sane reviewer 对 meta-标识判支持。
  - **`judge` 模块级零 pipeline 导入**:retriever/pg/llm 经形参注入、`drop_degraded` 就地 inline、`resolve_cited_clauses`
    用 `common.pg_models` + `bridge` 归一 → 纯函数 `strip_bare_conclusion`/`build_framing` 零栈可测。
  - **集成复用 `case_stack`**:内规件(三段式依据)+ 处罚案例件(桥接 retrieve_cases);桥接**手插 `cited_regulations`**
    指向内规 doc_number+clause_path_norm 验反查(同 R3/R4 手插-复位);autouse 幂等 `mio.connect()` 重连(R3/R4 预案)。
  - **占位收尾**:`_PLACEHOLDER_NOTE` 清空但 `_placeholder` 节点**保留为防御兜底**(未知 route_type 仍落它)。
- **未做(SPEC-R5 §0)**:§9.2 真 LLM 复核默认开(需 gateway+Kimi,RL-1 真-LLM 闭环另轮)、LLM 构成要件抽取默认开、
  `cited_regulations` L2 生产打标(§15-⑤)、§9.2 触发重生成(降待核实即可)、bge-reranker/sparse 提权/流式。
- **§15-④ 产品形态**:按 §6.5 三段式 demo workaround 实装(`review_required` 人工复核必需 + 代码后检无裸结论 +
  AI 辅助标识),**不向甲方承诺判定结论**,交付标注待甲方(张益)确认。
- **Codex 复审修复(1 critical,实红线缺陷)**:
  - **`R5-NORAW-PASSTHROUGH`**:默认零-LLM 框定 `_clause_passthrough` **回显 doc_title/clause_path 进文本且未过 strip**
    → 标题/路径含 verdict 词(如 `合规管理办法`/`违规处理`)即泄漏裸结论进 `answer_blocks`,踩 SC2 红线
    (实现期我误判"clause直呈是确定性安全构造"——真实存在以"合规/违规"命名的制度)。修:**框定抽象引用所引条款**
    (`所引 N 条条款`,条款身份只在 `citations[]` 结构化承载、不回显进文本)+ **`build_framing` 两路框定都过
    `strip_bare_conclusion`**(always-on 元数据泄漏兜底)+ `test_verdict_token_in_metadata_not_leaked` 回归
    (doc_title=`合规管理办法`/clause_path=`违规处理` → blocks 无 verdict)。**红线本质**:验证真实性 ⊆ citations,
    框定文本不承载可能含 verdict 的元数据。
  - **`R5-REVIEW-LLM-BOOL-VALIDATION`(warning,LLM05)**:§9.2 `_supported` 用 `bool(...get("supported", True))`
    判 LLM 输出——畸形 `{"supported": "false"}`(字符串真值为 True)→ 误判支持放过踩红线表述;且缺键默认 `True`
    **fail open**。修:改 `...get("supported") is True`(**严格 bool True**;缺失/非 bool/字符串 → 判不支持,
    **fail closed** 降"待人工核实")+ `test_review_malformed_bool_fails_closed` 回归(`"false"`/`"true"`/缺键)。

## §5.5 重排(第七轮 spec-driven,SPEC/PLAN/TASKS-RERANK)—— 八路后首个横切增强

- **切片**:`rerank_backend=bge` 时,主 hybrid `retrieve`(R1/R5)对候选池(~50)用 **bge-reranker-v2-m3** cross-encoder
  重排 → `topk`(8)。新增 `query/query/rerank/`(`RerankerClient` Protocol + `NoneReranker` passthrough **默认** +
  `BGEReranker` 本地 **transformers 直载** cross-encoder 懒载 + `make_reranker` factory)。扩 `milvus_io.search` 加 `with_text`(add-only)。
  `Candidate` +`text`(add-only,默认 None)。**`rerank=none`(默认)byte 等价**。
- **决策**(AskUserQuestion 2026-06-25):
  - **文本来源 = Milvus rerank-hop**:扩 `search` `with_text` 输出 Milvus 截断 text(2000)——schema 本就为"检索-重排
    一跳"预留;reranker 内部截 512 token,2000 足够;热路径免 PG 往返(生产意图)。`with_text=False`(默认)与原等价。
  - **应用范围 = 仅主 hybrid `retrieve`(R1/R5)**:`retrieve_enumerate`(R4)/`retrieve_cases`(R3)**不接 reranker**
    —— R4 枚举 §6.4 求召回完整性、不激进截断,与精排 top8 相悖;R3 一案一卡去重。
  - **接缝 idiom**(同 llm/embedding):Protocol + demo 默认(none)+ factory(`make_reranker`)+ 本地懒载。
    **加载失败抛、不静默退化 none**(Q5,避免误以为重排了)。
- **默认零回归三重守护**:① `NoneReranker` passthrough 接在 RRF 序后 → 终态不变;② `with_text=False` 默认(零 text
  开销 + output_fields 与原 `_OUTPUT_FIELDS` 等价);③ `Candidate.text` 末位默认 None → 既有 8-arg 位置构造不破。
- **踩坑 / 测试**:
  - **`_hits(res, fields)` 透传**:`_hits` 原读模块级 `_OUTPUT_FIELDS` → 加 text 须把 output_fields 传入 `_hits`(否则
    text 在 output 里但不进 row);`with_text=False` 传 `_OUTPUT_FIELDS` 守等价。`test_milvus_search_text`(mock)断言。
  - **`rerank` 模块级零 pipeline 导入**:`reranker.py` 候选按 `.text` **鸭子类型**(不引 `Candidate`,Protocol 用 `list`),
    纯函数零栈可测;`Retriever.__init__` 局部导入 `make_reranker`(避 import 期环)。
  - **无本地 reranker 模型也能验承重**:集成注入 **fake reranker**(反转)在真栈跑 → 验 `with_text=True` 返**真 Milvus text**
    + reranker 真应用(`bge_ids == none_ids[::-1]`);真 bge-reranker-v2-m3 模型需 `QUERY_RERANK_MODEL`,缺则 skip(绝不联网)。
  - **`FlagReranker` 不兼容 transformers 5.x**(实测):本机 `transformers 5.12.0` 已移除 tokenizer 的
    `prepare_for_model`,`FlagEmbedding.FlagReranker.compute_score` 调用即 `AttributeError`(BGE-M3 **embedding** 走
    `BGEM3FlagModel` 不受影响,故仅 reranker 中招)。**修**:`BGEReranker` 改 **`transformers` 直载**
    (`AutoModelForSequenceClassification` + `AutoTokenizer`,bge-reranker-v2-m3 = XLM-RoBERTa cross-encoder,输出
    relevance logit)——这正是 FlagReranker 内部所封装、且**零新依赖**(transformers 已在栈)。`_scores(query, texts)`
    为打分接缝(单测 mock,免载 2.3G);实测相关条款 logit 2.616 ≫ 无关 -5.096。模型经 **modelscope** 拉到
    `~/.cache/modelscope/hub/models/BAAI/bge-reranker-v2-m3`(同 BGE-M3,~0.7MB/s 慢、暂存 `._____temp` 后移入)。
    **真模型集成 3/3 passed**(含 `test_rerank_bge_real_model`)。
  - **`zip(scores, candidates, strict=True)`**:分数与候选等长(`_scores` 返 len(texts))→ strict 守不静默丢候选。
- **未做(SPEC-RERANK §0)**:rerank endpoint/网关(§9.1,本地 transformers reranker 同 BGE-M3 workaround)、top-k V0 标定
  (§15,默认 50→8 占位)、`compute_score` 归一阈值、R4/R3 重排、sparse 提权(§5.4)。
- **Codex 复审修复(1 warning,实契约缺口)**:
  - **`QUERY-RERANK-OFFLINE`**:`BGEReranker._load` 调 `from_pretrained` **未带 `local_files_only=True`** → `rerank=bge`
    且模型未缓存时会**联网 HF 下载**,违"绝不联网"rerank 契约(此前仅靠集成 `HF_HUB_OFFLINE` env 防护、非代码强制)。
    修:tokenizer/model 两处 `from_pretrained` 均加 **`local_files_only=True`**(本地缺失→抛,fail closed,同"加载失败
    不退化 none")+ `test_bge_load_forces_local_files_only`(monkeypatch 断言参数传入);实测**去掉 `HF_HUB_OFFLINE` env
    后真模型仍从本地 modelscope 路径加载、集成绿**(代码级离线 enforced)。

---

## §5.4 sparse 精确通道(发文字号提权 + 词典扩展)—— 八路后第二个横切检索增强(2026-06-26,SPEC/PLAN/TASKS-SPARSE)

> worktree `feat/query-docnum-boost`(与另一 Claude Code 的 P0 隔离;同一 `.git` 双工作树)。**全绿**:
> `test_sparse_boost` 20 + `test_query_config` +2;**集成 `test_sparse_boost_integration` 3 passed**(干净栈 + 真 BGE-M3);
> **全 query 模型门 226 passed / 2 skipped 无回归**(R1–R8/rerank/sparse 整路集成 + `test_pg_io` 新种子 inert)。

- **已决(AskUserQuestion)**:① 范围 = 发文字号提权 **+** 词典扩展(新建 `seeds/dict_scenario_terms.csv` v0-draft);
  ② 机制 = **查询层 sparse token 提权**(保持 `RRFRanker`、零 pipeline 改动);③ 应用 = **主 retrieve(R1/R5)**。
- **关键设计 / 取舍**:
  - **RRF 基于秩、无法表达通道权重** → 字面"sparse 权重提升"不能靠重权 RRF。**弃 `WeightedRanker`**(Milvus 2.4 为
    原始加权和,COSINE/IP 量级失配易被 sparse 主导);改**选择性 token 提权**:检出发文字号/全名 span → 重 embed →
    其 lexical 权重按系数**并入 query sparse** → 含该 token 的 chunk sparse 名次升 → RRF 浮顶。等效达意且更稳。
  - **uniform 缩放对 RRF 无效**(秩不变)→ 必须**选择性**(只动命中 span/法言词的 token)。
  - **两机制统一为一个查询层 sparse 增强**(`augment_sparse`):提权=放大发文字号 token;扩展=注入 dict 法言词 token。
    **只动 sparse、不碰 dense**(dense 改写归 HyDE/N1)。**双开关默认关 → 返回 `base_sparse` 同一对象 → byte 等价**;
    开但无命中 → 空集 → 仍等价(`test_augment_noop_*` 守同一性)。
  - **词典 consumed-when-present**:`load_scenario_terms` 缺/空/坏行 → `{}`/跳过;`Retriever.__init__` 仅 `scenario_expand`
    开才读文件(关→{} 免 IO)。dict 内容受 **§15⑥**(业务专家评审)阻塞 → 仅 v0-draft seed,不承诺覆盖率(同 R4 dict 范式)。
- **实现**:`retrieve/sparse_boost.py`(`detect_doc_numbers` regex + `load_scenario_terms` + `_matched_legal_terms` +
  `augment_sparse` 纯函数,embed 注入鸭子类型、零栈可测);`hybrid.retrieve` 经 `_sparse_for` 注入
  (`retrieve_enumerate`/`retrieve_cases` **不动** → R4/R3 不接);`config` +`docnum_boost`/`scenario_expand`(默认 False)+
  两系数(⚠V0)+ `scenario_terms_path`(锚 repo 根)+ 3 env;`seeds/dict_scenario_terms.csv`(v0-draft,源 §3.2)。
- **踩坑 / 核实**:
  - **`to_halfwidth` 只转全角 ASCII(0xFF01–0xFF5E)+ 全角空格** → 全角数字/（）归一,但 **CJK〔〕(U+3014/5)不变**
    → 发文字号 regex 必须**显式含 〔〕**(及 ()（）[]【】)。
  - **`seed_dicts` 不扰**(§7 Ask-first 核实):`PgIO.seed_dicts`(pg_io.py:233)**显式读命名文件**,**非 glob `seeds/*.csv`**
    → 新增 `dict_scenario_terms.csv` 对 `demo up` 灌库 **inert**(仅查询层读)。
  - **worktree 无 .venv**:`PYTHONPATH=<worktree>/{query,pipeline,libs/common}` 复用主 `.venv` 跑单元(`sparse_boost.py`
    仅存于 worktree → import 成功即证 env 解析到 worktree 码)。集成需真模型 + 干净独占栈,与另一 CC 不抢。
  - **提权在小语料是 no-op(实测 off_rank=0)**:§5.1 hybrid(dense+sparse)已把含发文字号 chunk 置顶,RRF 基于秩
    → 已在榜首者无可再升。故**集成只验端到端召回 + 不回归 + 双关 byte 等价**;提权的**严格非无效**(token 注入使目标
    sparse 内积↑)由单元 `test_augment_*_strictly_raises_target_ip` 证;**检索 rank 改善是大语料 / §15 V0 性质**
    (海量近义文档中浮顶精确命中),非小语料可证。
  - **集成 fixture 踩坑(META_REVIEW)**:发文字号嵌正文 → meta L1(`HEAD_BLOCKS=8` 版头内)抽为 doc_number → 与
    manifest 冲突 → 卡 META_REVIEW(非 INDEXED,B 模式不放行)。修:正文用**冒号边界**(`文号:银保监发〔2021〕5号`)
    使文号正则前缀只吃「银保监发」、干净抽出 = manifest `doc_number`(`_norm_dn` 一致)→ 无冲突 → 自动放行。
- **未做(SPEC-SPARSE §0)**:`WeightedRanker` 通道重权 / 检索后提分(决策弃);dense 改写/HyDE(N1);`dict_scenario_terms`
  建 PG 表 + 灌库(GAP #11,§15⑥);提权应用 R4/R2/R3/R6;系数 V0 标定;`dict_intent_routes`/N2 重构;
  **`dict_issuer_codes`(机关代字字典)彻底解决机关简称长尾截短(GAP #13 / §15-V0)**。
- **Codex 复审修复(2 warning,均实缺陷)**:
  - **`QUERY-SPARSE-DOCNUM-SPAN`/`-WHITELIST`(4 轮)**:regex 前缀无左边界 → 口语前缀(请问/这个制度依据/麻烦查一下/
    看看/了解/详见/按…)被卷入提权。1 轮 `_strip_lead` 停词表、2 轮窗口 `{0,12}→{0,6}` 均被指出"黑名单/固定窗口无法
    定义代字边界" → 3 轮改**字符白名单 `_DAIZI`**(机关简称+文种字,口语字不在集合故贪婪不卷入,弃停词);4 轮复审指出
    白名单**缺常见文种字(告/令/函)**致 `公告/令` 文号退化为裸〔年〕号 → **补全全部常见文种字 + 机关简称**
    (`国家税务总局公告〔2019〕32号` 等全提取)。**关键不变式:真实文号必以文种字结尾、文种字全在白名单 → 永不退化为
    裸〔年〕号**。14 例参数化测试(4 轮全部样例)全过;机关简称长尾用字仍可能截短(良性,非裸号),彻底需字典/分词(§15-V0)。
  - **`QUERY-SPARSE-WEAK-INTEGRATION`**:集成把"严格升名次"放宽成"升或持平" → no-op 提权也能过(**实测确为 no-op**:
    小语料 hybrid 已置顶)。修:机制非无效改用**确定性单元 sparse-IP 严格断言**(`test_augment_*_strictly_raises_target_ip`),
    集成改为诚实的端到端召回 + 不回归 + 双关等价(不再伪称"名次升")。
  - 复审后:`test_sparse_boost` 20 + 全 query 模型门 **226 passed / 2 skipped** + ruff 全绿。待 Codex 复审。

## §9.2 Kimi 忠实性复核 —— RL-1 真-LLM 闭环(2026-06-26,SPEC/PLAN/TASKS-REVIEW)

> worktree `feat/query-faithfulness-review`(与 P0 文档管线 `feat/p0-phase2-biz-domain` 双工作树隔离)。
> **接口/toggle/fail-closed/LLM seam 已在 R5 轮实装** → 本切片只**接真复核模型 + 闭环测试**,零接口重写、零 pipeline 改动。
> **全绿**:`test_query_config` +2 / `test_llm_stub` +3 / `test_r5_review` +2(wiring)/ `test_r5_review_integration` 2 skipped(门控);
> **全 query 套件 204 passed / 29 skipped**、ruff 净、无回归。

- **已决(AskUserQuestion,2026-06-26)**:① 复核用**独立 `review_model`(Kimi)**,与主答 `llm_model`(Qwen)分离(§9.1);
  ② 不支持的试探性表述 → **降「待人工核实」**(沿用已实装,**不触发重生成**);③ 范围 = **仅 R5 判定型**。
- **关键设计 / 取舍**:
  - **`make_llm_client(cfg, *, model=None)` add-only**:gateway 用 `model or cfg.llm_model` 建客户端 → 复核传 `review_model`
    即与主答分离;**不传 = 主答模型**(既有 graph/调用零变化)。stub 分支忽略 `model`(零网络)。
  - **复核客户端仅 toggle 开时建**:`r5_judgment.answer_judgment` 内 `review_llm = make_llm_client(qcfg, model=review_model)
    if judge_multimodel_review else llm` → **关 → 不建客户端、`review_tentative` 直通主答 llm(零网络、byte 等价)**;
    `build_framing` 仍用主答 `llm`。`review.py`/`_supported`/fail-closed **不改**(本切片是其互补的真-LLM 层)。
  - **`review_model` 默认 `kimi-2.5`** 为 §9.1 意图占位(真名待甲方网关注册表 §15-①);env `QUERY_REVIEW_MODEL`(query 专属)
    优先于 `OPENAI_REVIEW_MODEL`(通用)。
- **实现**:`config` +`review_model` + 两 env 覆盖;`llm/client.py` `make_llm_client` model 参;`judge/r5_judgment.py` 复核客户端接线
  (+`from query.llm import make_llm_client`);`PROMPTS.md` §9.2 忠实性复核 prompt(镜像 `_supported`,标 fail-closed+默认关);
  新 `query/tests/test_r5_review_integration.py`(门控真闭环)。
- **踩坑 / 核实**:
  - **worktree + editable-install 解析陷阱(关键)**:主 `.venv` 的 `pip install -e` 用 **MetaPathFinder**(`_EditableFinder`,
    `MAPPING={'query': '<主 checkout>/query/query'}`)→ 直接用主 venv 跑会**测到主 checkout 码、非 worktree**。
    所幸 `sys.meta_path` 中默认 **`PathFinder` 先于(append 的)`_EditableFinder`** → `PYTHONPATH=<worktree>/{query,pipeline,libs/common,eval}`
    使 `PathFinder` 先解析到 worktree(实测 `query.__file__` 指向 worktree)。**worktree 跑测试一律带此 PYTHONPATH。**
  - **真模型门控测本地无 key 未执行**(只验**干净 skip**:`QUERY_LLM_BACKEND=gateway`+`OPENAI_API_KEY` 缺 → 2 skipped、零网络)
    → 故 **RL-1 / §9.2 仍诚实记 🟡**(实装+单测+门控就位),**待真 gateway+key 跑绿后翻 ✅**(不在未执行门控测上overclaim 红线)。
- **Codex 复审修复(PR #21,1 warning,实缺陷)**:
  - **`R5-REVIEW-NEEDS-CLAUSE-EVIDENCE`**:初版 `review_tentative` 只喂 `citations`(锚点 `《题名》条号`,**无条文正文**)→
    `_supported` 无从核忠实性,真模型只能凭题名 plausibility 判断、闭环形同虚设(RL-1 是 P0 红线)。**接受 spec-drift**
    (SPEC-REVIEW §0「不改 review_tentative/_supported」前提是接口够用,实则不够——SC2「校验是否被所引条款支持」无条文
    不可达)→ 改 `review_tentative(blocks, clauses, llm)` 喂 **`clauses`(含 `text` 条文原文)**;`_supported` 经
    `_clause_evidence` 拼 `《题名》条号:正文` 每条一行(正文缺失 → `(正文缺失)`,fail-closed 兜底)。`r5_judgment` 传
    已有的 `clauses`(零额外查询)。**回归**:`test_review_prompt_includes_clause_text`(断言条文原文进 prompt)+ 集成测
    改为**基于条文证据**(同题名/条号、条文不支持某表述 → 降级)。`review.py` fail-closed 语义不变。
- **未做(SPEC-REVIEW §0)**:触发重生成 / 全量双跑 / 其他路由复核 / 主答模型切换 / 改 `_supported` fail-closed 语义;
  真 Kimi gateway endpoint 可用性(甲方,§9.1/§15-①)。**待 Codex 复审② + 真 gateway 跑绿。**
- **§15-④ 待外部确认(2026-06-28)**:R5 三段式产品形态接受条件(「给出具体条文」→「综合说明」→「无法回答」)已标注
  **待甲方张益确认**,影响 §15 模块能否最终闭环。确认结果须回填此处。

## N0 多轮上下文归并 + R7 澄清闭环(2026-06-28,SPEC/PLAN/TASKS-N0)

> worktree `feat/query-n0-multiturn`(独立工作树,与他侧隔离)。把 `QueryState.history`(占位)推进到真消费:
> 查询理解前端入口 N0 实装 + 闭合 R7 已知缺口(§6.7「澄清后回 N0 重新归并」)。**全绿**:`test_merge` 13 +
> `test_graph` +6(n0 节点/R7 闭环/单轮 no-op/merge 客户端门控)+ `test_query_config` +2 + `test_query_cli` +4;
> `test_merge_integration` 2 skipped(gate=gateway+key,本地无 key)。**全仓非栈门 672 passed / 50 skipped、ruff 净。**

- **已决(AskUserQuestion,2026-06-28)**:① **N0 LLM 为主、`merge_context` 默认开**——§3.4 指代消解/省略补全本质是
  LLM 友好任务,用户**明确接受其代价**(偏离本仓「默认零 LLM」约定、每轮多一次网关调用、无 key 时降级、默认非 byte 等价);
  ② **入口 = `ask(query, history=None)` 无状态 API + CLI `--history-json`**(调用方维护会话,**不做** `chat` REPL)。
- **关键设计 / 取舍**:
  - **「LLM 为主默认开」与离线确定性的调和**(核心):默认 `llm_backend=stub`(零网络)。故 merge 客户端 `_merge_llm`
    **仅 `merge_context` 开 + gateway 时建**(镜像 §9.2 复核「仅 toggle 开时建」),否则 `None` → `merge_context` 走
    **规则版确定性归并**(= 用户接受的「无 key 降级」)。**LLM 为主**体现在:有真 LLM(gateway)即真改写为主路径,规则版退居
    离线兜底 + fail-safe。`merge_context` try/except:真 LLM 抛/返空 `merged_query` → **回落规则版/原句,绝不阻断查询**。
  - **单轮零回归**:空 history → `merge_context` 短路返原句、`_n0_merge` 返 `{}` → `state.query` 不变 → 既有单轮全链路
    **byte 等价**(440+/672 既有测试不受影响)。「默认非 byte 等价」仅指**多轮带 history**(本就是新行为)。
  - **R7 闭环 = 跨请求无状态**(非图内环):clarify 返回 → 调用方带 history(原问 + clarify 问)重问 → **下一请求入
    `n0_merge` 节点**把原问 + 澄清答归并 → 重路由到真实答路径。「回到 N0」= 下一请求的入口节点,**不建 LangGraph cycle**——
    守 §0.3「不进 plan→retrieve→reason 的 agentic 循环」。`test_r7_closure_changes_routing` 用 `_n0_merge`+`route_only` 模拟
    (单轮「它呢」→CLARIFY;多轮归并后离开 CLARIFY),零栈。
  - **状态契约零改**:N0 输出**写回 `state.query`**(归并后自足问句),下游 `understand`/检索/生成读它、**零改**;原句多轮时
    可从 `history` 复得。**不新增状态字段**(守 `state.py`「加节点永不改状态契约」),只消费既有 `history` + 改写 `query`。
- **实现**:`understand/merge.py`(`_rule_merge` R7 闭环+代词/省略顺承 + `MERGE_SYSTEM`/`build_merge_user`/`parse_merged`
  + `merge_context` 纯函数,鸭子类型 `llm`,零栈可测);`graph.py` `n0_merge` 节点(`START→n0_merge→understand`)+ `__init__`
  建 `_merge_llm` + `ask(query, history=None)`;`config` +`merge_context`(默认 True)/`merge_model`(None→复用 `llm_model`)+ 2 env;
  `cli.py` `--history-json`(畸形 JSON/非数组 → `typer.BadParameter`);`PROMPTS.md` §3.4 条目。
- **踩坑 / 核实**:
  - **`_COREF` 子串 vs `router._PRONOUN_ONLY` 整句相等**:router 的 `_PRONOUN_ONLY` 是**整句相等**的歧义判据(触发 R7
    澄清);N0 顺承问「是否**含**需补全的指代」用**子串**,且词表更全(它/该/这条/那条/上面那条…)——**相关但不同的概念**。
    故 merge.py **仅复用 `_MIN_LEN`**(过短阈值,真共享),`_COREF` 另立并注释关系(非「另起黑名单」,语义本就不同)。
  - **规则版顺承粒度 = 最近 user 整句拼接**(`f"{最近user问} {当前}"`):确定性、提升召回(主题 + 当前问句一并送检索);
    更细的名词短语抽取/指代**替换**靠 gateway 真 LLM。务实版,同 §5.7/§8.1 范式。子串「呢」过宽故 `_COREF` **不含裸「呢」**
    (避免自足问句「…在哪呢」误触顺承污染上轮主题)。
  - **RTM 116 基线不可加行**:差点为 N0 加 `N0-coref`/`N0-ellipsis` 两行 → 破坏「116 条原子需求」计数不变式。**撤回**,
    细节并入既有 `N0` 行证据;N0 ❌→🟡、R7🟡→✅,摘要 ✅51→52 / ❌33→32 / 🟡31 不变。
  - **worktree editable-install 解析陷阱**(同 REVIEW 轮):主 `.venv` 的 `_EditableFinder` 会把 `query` 解析到主 checkout;
    `PYTHONPATH=<wt>/{query,pipeline,libs/common,eval}` 使 `PathFinder` 先解析到 worktree(实测 `query.__file__` 指 worktree)。
  - **真-LLM 门控本地无 key 未执行**(只验干净 skip:gateway+`OPENAI_API_KEY` 缺 → 2 skipped、零网络)→ 故 N0/N0-coref/
    N0-ellipsis **诚实记 🟡**(实装+单测+门控就位),**待真 gateway+key 跑绿翻 ✅**(不在未执行门控测上 overclaim)。
- **未做(SPEC-N0 §0)**:N1 HyDE / N3 问题分解(同前端、另切片,§15-①⑦);图内 LangGraph 环 / agentic 多跳;`chat` REPL;
  会话持久化/服务端 session(无状态,调用方维护 history);Web 工作台接线;`dict_intent_routes`/N4 重构;`merge_model` 真名
  (§9.1/§15-①);规则版深度指代消解(靠真 LLM)。**待 Codex 复审 + 真 gateway 跑绿。**

## N1 HyDE 查询改写(假设性法言 → dense 检索)(2026-06-29,SPEC/PLAN/TASKS-N1)

> worktree `feat/query-n1-hyde`(独立工作树,与 ref-r4 他侧隔离;从含 N0 合并的 origin/main 切)。查询理解前端 N1 从 ❌
> 推进到实装:口语问句 → LLM 生成假设性法言 → `embed(原问+法言)` 作 **dense 向量**(HyDE,Gao et al. 2022/2023)。**全绿**:
> `test_hyde` 17(纯函数 5 + `_dense_for`/接线 7 + 门控建客户端等)+ `test_query_config` +2;`test_hyde_integration` 1 skipped
> (gate=gateway+key,本地无 key);**全 query 套件 245 passed / 31 skipped 无回归。**

- **已决(AskUserQuestion,2026-06-28)**:① **HyDE 默认开**(`hyde` 默认 `True`,对齐设计 §3 节点链「默认 on」+ N0 默认开范式);
  ② **注入点 = Retriever 内 dense 接缝**(镜像 §5.4 `_sparse_for` / §5.5 rerank,**不**走图 N1 节点 / 不改 `state.query`)。
- **关键设计 / 取舍**:
  - **为何 Retriever 内接缝、不走图 N1 节点**(关键):HyDE 只改 **dense 向量**,**绝不能污染 classify/route**(路由基于真实
    口语问句,而非编造法言)。若像 N0 那样改写 `state.query`,classify/route 会拿到假设性法言 → 误路由。故 HyDE 必须在
    dense 嵌入处(`retrieve()` 内)落地、不碰 `state.query`——与 §5.4 sparse_boost / §5.5 rerank 同为「Retriever 内检索增强
    接缝」范式,而非前端节点。`state.rewrites` 字段保留占位(HyDE 文本是检索内部态,不进 graph state)。
  - **HyDE 专管 dense、sparse 留原问**:dense 文本 = `f"{query}\n{passage}"`(§3.1「假设性法言与原始问句一同送入 dense」);
    sparse 仍走 `_sparse_for`(原问 + §5.4 dict)。**理由**:§7.1 污染兜底 + 法言 sparse 扩展归 §5.4 dict 桥接(口语→法言),
    分工干净——避免编造法言污染**精确 sparse 匹配**。`retrieve()` 多一次 embed(原问供 sparse + 原问+法言供 dense),HyDE 固有。
  - **「默认开」与离线确定性的调和**(同 N0 范式):默认 `llm_backend=stub`(零网络),HyDE **无规则版兜底**(必须 LLM 生成
    法言,不像 N0 有确定性规则归并)。故 `hyde_llm` **仅 hyde 开 + gateway 时建**(`_build_hyde_llm`);**stub/无 key →
    `hyde_llm=None` → `_dense_for` 返 `emb.dense`(原问 dense)→ 默认 byte 等价、零网络**。「默认开」仅在配 gateway 时活。
    LLM 抛/返空 → `hyde_dense_text` None → `_dense_for` 回落 `emb.dense`(§3.1 N1-fail,绝不阻断检索)。
  - **仅主 retrieve(R1/R5)**:`retrieve()` 用 `_dense_for`;`retrieve_enumerate`(R4)/`retrieve_cases`(R3)**不动**(同 §5.4
    sparse 提权范式)。`test_enumerate_does_not_hyde`/`test_cases_does_not_hyde` 断言 `llm.calls==0` + 仅 embed 原问。
  - **污染兜底(§7.1)**:HyDE **不产出 `clause_id`**;即便编错法言,最终答案仍只引检索上下文带 `clause_id` 者(引用注入)
    → 错误法言不污染答案。这是「默认开 HyDE」可接受的前提(错召回靠覆盖自检/拒答兜,错答靠引用注入杜绝)。
- **实现**:`retrieve/hyde.py`(`HYDE_SYSTEM`/`build_hyde_user`/`parse_passage`/`hyde_dense_text` 纯函数,鸭子类型 `llm`,零栈
  可测);`retrieve/hybrid.py` `_build_hyde_llm`(模块级,可单测)+ `Retriever.__init__(... , hyde_llm=)` + `from_config` 建 +
  `_dense_for(query, emb)` + `retrieve()` 用 `dense=self._dense_for(...)`;`config` +`hyde`(默认 True)/`hyde_model`(None→复用)
  + 2 env;`PROMPTS.md` §3.1 条目。
- **踩坑 / 核实**:
  - **`_build_hyde_llm` 提为模块级函数**(非 inline 在 `from_config`):`from_config` 连真栈(EmbeddingClient/Milvus),单测跑不动;
    把「仅 hyde 开+gateway 建客户端」逻辑提为模块级 `_build_hyde_llm(qcfg)` → `test_build_hyde_llm_only_gateway_and_on`
    monkeypatch `query.llm.make_llm_client` 直测(stub→None、gateway+on→建、gateway+off→None),零栈。
  - **`_dense_for` 失败不额外 embed**:`hyde_dense_text` 返 None(LLM 抛/空)→ `_dense_for` 直接返 `emb.dense`,**不再 embed**
    (`test_dense_for_fallback` 断言 `fe.texts==[]`)→ 回落零额外开销。
  - **默认开却记 🟡(诚实姿态)**:`hyde=True` 但真生成门控本地无 key 未执行(只验干净 skip)+ §13 V0 第5组 A/B 未跑(召回
    收益 hit@10 未验证)→ N1 记 🟡、N1-decision ❌(默认值/配额待实测);**N1-fail ✅**(fail-safe 回落确定性可测、不依赖 LLM)。
    不在「默认开」上 overclaim 召回收益——默认 stub 实为 no-op,真收益待 gateway+V0。
  - **worktree editable-install 解析陷阱**(同 N0/REVIEW):`PYTHONPATH=<wt>/{query,pipeline,libs/common,eval}` 使 `PathFinder`
    先于主 venv `_EditableFinder` 解析到 worktree(实测 `query.__file__` 指 worktree)。
- **未做(SPEC-N1 §0)**:N3 问题分解(另切片);改 sparse 通道(法言 sparse 归 §5.4 dict);HyDE 进 R3/R4;图 N1 节点/改
  `state.query`;**§13 V0 第5组 A/B 实验 / 术语断层率统计 / 配额折算 / 默认值终定 / 桶触发降级**(V0 未跑);Langfuse trace HyDE
  文本;`hyde_model` 真名(§9.1/§15-①)。**待 Codex 复审 + 真 gateway 跑绿 + V0 标定。**

## N3 问题分解(复合问句拆子查询 → 并行检索再综合)(2026-06-29,SPEC/PLAN/TASKS-N3)

> 同 worktree `feat/query-n1-hyde`(续在 N1 之上,N1+N3 后统一交审)。查询理解前端 N3 从 ❌ 推进到实装:复合问句 → LLM
> 一次性拆为子查询 → `retrieve()` fan-out 检索 → 候选并集综合(plan-execute 拆分)。**查询理解前端 N0/N1/N3 三节点收官**。
> **全绿**:`test_decompose` 19(纯函数 7 + fan-out/接线 12)+ `test_query_config` +2;`test_decompose_integration` 2 skipped
> (gate,本地无 key);**全 query 套件 260 passed / 32 skipped 无回归**(含 retrieve 重构)。

- **已决(AskUserQuestion,2026-06-29)**:① **注入点 = Retriever 内 decompose+fan-out 接缝**(镜像 N1;不走图 N3 节点);
  ② **decompose 默认开**(仅复合问句触发,对齐设计 §3 节点链 + N0/N1 默认开范式)。
- **关键设计 / 取舍**:
  - **为何 Retriever 内 fan-out、不走图节点**(同 N1 理由):拆子查询影响的是**检索**(每子查询检索→候选并集),route_type
    由 `understand()` 对**原问**判一次(复合「…是否违规」→ R5);decompose **不重路由、不改 `state.query`**。若走图节点改写
    query 会污染路由。故落 `retrieve()` 内——与 §5.4/§5.5/N1 同为「Retriever 内检索增强接缝」。`state.rewrites` 仍占位。
  - **retrieve() 重构抽 `_search_candidates`(零行为变更)**:把原 retrieve() 的「分区检索+合并(含 HyDE dense/sparse)」抽为
    `_search_candidates(query) -> dict[chunk_id, Candidate]`;`retrieve()` 改 `for sq in _subqueries_for(query)` 并集→rerank(原问)/topk。
    **单查询时 `_subqueries_for` 返 `[query]` → 并集=单份 → 与原 retrieve byte 等价**(既有 `test_hyde`/检索集成不回归,260 passed 验证)。
  - **综合 = 候选并集(覆盖),非多答拼接**:各子查询候选按 `chunk_id` 并集(保最高分)→ 生成层**零改**(候选集覆盖各子约束
    更全)。⚠ 子查询间分数尺度不同 → 并集求**覆盖完整性**为主,最终序由 max-score + rerank(原问)兜(务实版,精排 V0)。
    decompose 价值是「每子约束都有候选」,非精确排序。
  - **与 N1 HyDE 自然组合**:`_search_candidates` 内调 `_dense_for`(HyDE)/`_sparse_for`(§5.4)→ **每子查询各自走 HyDE**
    (子查询口语→假设性法言→dense)。三层(decompose→HyDE→sparse)在 retrieve 内分层组合、互不耦合。
  - **「默认开」与离线确定性**(同 N1):`decompose_llm` **仅 decompose 开+gateway 建**(`_build_decompose_llm`);stub/无 key →
    `None` → `_subqueries_for` 返 `[query]` → byte 等价、零网络。**仅复合**(LLM 拆 >1)才 fan-out;单跳/失败/返空 → `[query]`。
  - **§0.3 不进 agentic 循环(硬边界)**:`decompose_subqueries` **一次性**拆分(单次 LLM 调用、返扁平列表)、`retrieve` 一轮
    fan-out、**无 re-retrieve / 无迭代推理**;`decompose_max_sub`(默认 4)封顶 fan-out 成本(复合 ×子查询数 ×分区 ×HyDE)。
- **实现**:`retrieve/decompose.py`(`DECOMPOSE_SYSTEM`/`build_decompose_user`/`parse_subqueries`/`decompose_subqueries` 纯函数,
  鸭子类型 `llm`,零栈可测);`retrieve/hybrid.py` `_build_decompose_llm` + `__init__(... , decompose_llm=)` + `from_config` 建 +
  `_subqueries_for` + 抽 `_search_candidates` + `retrieve()` fan-out;`config` +`decompose`(默认 True)/`decompose_model`/`decompose_max_sub`(4)
  + 2 env;`PROMPTS.md` §3.3 条目。
- **踩坑 / 核实**:
  - **重构零回归靠「单查询=单份并集」**:retrieve() 改 fan-out 后,单查询路径必须与原逐字等价 —— `_subqueries_for(None)`→`[query]`
    → 循环跑一次 `_search_candidates` → 并集即原 merged dict → sort/rerank/topk 不变。**先跑既有 `test_hyde`(其 `test_retrieve_uses_hyde_dense`
    走 retrieve)+ 全 query 260 passed 确认零回归**,再加 fan-out 用例。
  - **fan-out 单测用 spy `_search_candidates`**:`test_retrieve_fans_out_union` monkeypatch `_search_candidates` 返 per-子查询 dict
    (q1→A、q2→B)→ 验 retrieve 调 2 次 + 候选并集 {A,B},无需真 milvus 行为。`_build_decompose_llm` 同 N1 提模块级直测。
  - **默认开却记 🟡**(同 N1 诚实姿态):decompose=True 但真拆分门控本地无 key 未执行 + §13 V0(复合占比/拆分质量)未跑 → N3
    记 🟡;**N3-noloop 保 🟡**(一次性拆分实装+测,但「不循环」是架构保证、无专门反例测,不破例标 ✅)。**§3-degrade 翻 ✅**
    (N0/N1/N3 fail-safe 回落全测,前端节点全可降级)。不在「默认开」上 overclaim 拆分收益。
- **未做(SPEC-N3 §0)**:子查询重路由 / agentic 迭代 / re-retrieve(§0.3);decompose 进 R3/R4;子查询级独立答复拼接;
  **§13 V0 复合占比/拆分质量评估 / 配额折算 / 默认值终定**(V0 未跑);Langfuse trace 子查询;`decompose_model` 真名(§9.1/§15-①);
  子查询并集的跨查询分数归一(精排 V0)。**待 Codex 复审 + 真 gateway 跑绿 + V0 标定。**

## §9.3 Langfuse 全链路观测(trace 接缝)(2026-06-29,SPEC/PLAN/TASKS-OBSERVE)

> worktree `feat/query-observe-langfuse`(独立工作树)。P3 横切首块:查询全链路 trace(查询理解→检索→生成),HyDE/子查询/
> route_type 进 trace 供 §13 V0 分析。**全绿**:`test_observe` 13(Noop/make_tracer/Langfuse/contextvar/fail-safe + Retriever event
> + ask trace)+ `test_query_config` +1;`test_observe_integration` 1 skipped(gate);**全 query 275 passed / 34 skipped 无回归**。

- **已决(AskUserQuestion,2026-06-29)**:① **MVP 范围 = 图层 trace + Retriever 内 HyDE/子查询**(设计 §9.3 全量进 trace)。
- **关键设计 / 取舍**:
  - **observe 默认关**(区别于 N0/N1/N3 默认开):观测**外发外部服务**(Langfuse),无 design「默认开」依据、守本仓「默认零网络」;
    `NoopTracer` 默认 → 全 no-op、byte 等价。这是「默认开/关」的判据分水岭:**增益型查询能力默认开**(有离线兜底),**外发基建默认关**。
  - **单一 tracer + module-level contextvar 串联**(关键):HyDE 文本/N3 子查询是 **Retriever 内部态**、不在 QueryState,要进 ask()
    开的同一条 trace,靠 ①`QueryAgent.from_config` 建**一个** tracer 传 `Retriever.from_config(tracer=)` + 自身;② module-level
    `_current` contextvar:`ask()` 的 `trace()` 进入 set、退出 reset,`Retriever.event()` 读 `_current` 挂事件。**无当前 trace
    (Noop / 未开)→ event no-op**。这样图层与 Retriever 事件落同一条 trace,而 Retriever 零「graph state」耦合。
  - **只读旁路 + fail-safe**:tracer **绝不**改 state/检索/答复/控制流(SC8:开/关 observe → result 必一致);LangfuseTracer 所有
    langfuse 调用 try/except **吞**(建 trace 失败 → 退化 noop span;event/flush 失败 → 吞)→ **观测绝不阻断查询**(observe 是增益非依赖)。
  - **langfuse 可选 extra + 懒导入**:`pyproject [observe]=langfuse>=2,<3`;`LangfuseTracer` 内 `from langfuse import Langfuse` 懒导入 →
    默认 noop 路径**不装 langfuse**(`import query.observe` 不拉 langfuse,实测)。`make_tracer`:observe+creds 且 langfuse 装 → Langfuse,
    缺 langfuse → 退化 Noop。
  - **离线安全 make_tracer**(同 offline-gate 范式):observe 开 + `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`(env)齐 → Langfuse,否则 Noop;
    creds 仅 env 绝不入库(同 `OPENAI_API_KEY`)。
- **实现**:`observe.py`(`Tracer` Protocol / `NoopTracer` / `LangfuseTracer`(contextvar + flush + fail-safe)/ `make_tracer`);`config`
  +`observe`(默认 False)+ env;`graph.py` `QueryAgent +tracer` + `from_config` 建并传 + `ask` 包 `trace`;`hybrid.py` `Retriever +tracer`
  + `_dense_for`/`_subqueries_for` 发 event;`pyproject [observe]` extra。
- **踩坑 / 核实**:
  - **候选数不在 state**:`ask()` 的 `invoke` 返终态 state 有 query/scene/route_type,但 `state.candidates` 节点未回写(检索在
    `_evidence` 内、结果不进 state)→ **trace metadata 去掉「候选数」**(诚实,只记 state 真有的归并句/scene/route_type);候选数若要进
    trace 需 Retriever 再发 event(留后续)。
  - **Codex 复审修复(1 warning,QUERY-OBSERVE-TRACE-RESULT)**:初版 trace `output` 只写 `route_type`,缺 SPEC §6/SC3 要求的
    **result 摘要** → 开 Langfuse 也回放不出本次实际输出、削弱 §13 A/B。修:`_result_summary(result)` 模块级助手返**安全摘要**
    (route_type + answer_blocks/citations 计数 + confidence/review_required/ai_label/exhausted_scope **标志**,**不含答复正文**避
    PII/体积),`ask` 用作 trace `output`;`test_ask_records_trace` 断言摘要字段。候选数仍未进(state 无),余同。
  - **fake tracer 双用**:`_CaptureTracer.trace` 用 `@contextmanager` yield self(span=self,`update` 记 `self.updates`)+ `event`
    记 `self.events` → 同一桩既测 ask trace(T5)又测 Retriever event(T4)。`make_tracer` 选 Langfuse 用 `monkeypatch.setitem(sys.modules,
    "langfuse", fake_mod)` 注入 fake `Langfuse`(免装真 langfuse)。
  - **worktree 解析陷阱**(同前):`PYTHONPATH=<wt>/{query,...}` 使 PathFinder 先于主 venv `_EditableFinder` 解析到 worktree。
- **未做(SPEC-OBSERVE §0)**:深层 per-stage span 树(检索/重排/生成/复核各 span + 耗时);敏感词/SSO/操作日志/AI 页脚(§9.3 余项);
  §13 V0 分析逻辑;采样率/PII 脱敏/保留(运维);候选数/更多字段进 trace。**待 Codex 复审 + 真 Langfuse 跑绿。**

## 阶段 B-API —— 制度查询 HTTP API(前端接缝,SPEC/PLAN/TASKS-API;参考产品原型 V3)

> B 轨:把原型「审计 AI 原型 V3」四交互面(对话流式 / 结构化四-Tab / 会话历史 / 导出·推荐·上传)落成
> FastAPI + SSE 接缝。**独立 worktree `feat/query-api`(从 origin/main 开)**,离线写码+单测,栈验证留合并门。
> 详见 `SPEC-API.md`(§13 决策记录 8 项)/ `PLAN-API.md` / `TASKS-API.md`。

- **决策 8 项(§13)**:HTTP=FastAPI;match_score 归一%直显;附件只存不消费;鉴权 stub+导出点 403;会话标题 LLM 概括(默认关→首问截断);
  功能2 独立会话表;导出 xlsx;**先 gateway 真流式再 SSE**(T10→T11)。
- **契约加法保 §10 byte 等价(踩坑)**:`QueryResult +structured/+meta`,但**默认时 `to_dict` 缺省省略这两键**(`structured=None`+`meta={}`
  不加键)——否则 `test_contract` 的「恰 8 键」断言破、CLI `query ask` 输出变。命中项可选字段同样缺省省略(零臆造,承 `CaseCard`)。
- **四-Tab 装配(§4)分区口径**:`retrieve()` 候选按 `corpus_type` 分 **P-INT→命中制度(按 dvid 去重)+ 命中条款(逐 chunk)** /
  **P-EXT→监管规则**;`retrieve_cases()` P-CASE→相关案例。**监管规则/相关案例无「匹配度」列**(原型无)→ 两个 Hit 无 `match_score`
  字段(T2 一度误传致 `TypeError`,修正)。`match_score`=候选集内 min-max 归一;⚠-data(theme/关联内规/违规主题)缺失即省略、
  ⚠-model(摘要走截断/卡片/引用建议)LLM 默认关缺省空。装配在 **API 边界层 `api/structured.py`,不进 graph 节点**。
- **会话表落 `common.pg_models`(踩坑)**:`QueryConversation`/`QueryMessage` 加进 common(全仓单一 Base metadata + 根 Alembic 单链),
  **非 query 自建 Base**——否则双迁移头。迁移是 **0012**(实际最新 0011,非 PLAN 假设的 0008)。单向只读红线:query 只写 `query_*` 表。
- **真流式与结构化引用的张力(T10 核心)**:LLM 输出是结构化 JSON `{answer,cited_ids}`,与 token 流式 + 「裸结论需全文判定」冲突。
  决策**两次调用**:`chat_json` 取忠实引用(与同步 `generate_evidence` 一致、红线安全,无引用→**流式前**降级拒答)+ `llm.stream` 真流式
  答复正文。`pipeline.llm_client +stream`(httpx SSE,add-only,共享)。答复红线=prompt 约束(§7.1)+ 最终 `sanitize_answer` 兜底
  (**流式中途无法回撤**,故 prompt 为主防线)。
- **SSE 编排(T11)**:`accepted→route→structured(四-Tab 一次)→answer_delta*→citations→done`;evidence 走 `generate_evidence_stream`
  真流式喂 delta,其余路由 `agent.ask` 全量、答复块作 delta;异常兜底 `error` 事件(不静默)。**流式路径与 graph 非流式路径并存**
  (复用 classify/resolve_scope/retrieve,不改 graph 节点)。同一 `messages` 端点 **Accept 分支**:`text/event-stream`→SSE,否则同步 JSON
  (同契约,One-Version)。
- **ruff bugbear**:FastAPI DI 默认值(`Depends()/Query()/File()`)触 B008 → 仿 `typer.Argument` 先例加进 `extend-immutable-calls`。
- **离线可测边界**:契约/装配纯函数/错误语义/端点(TestClient+fake svc)/xlsx 读回/SSE 序列(fake+monkeypatch)全离线绿(330 passed);
  **alembic apply/check、所有 `_integration`(含真流式 gateway 门)留合并前全仓门**(并行栈协调,不贸然打共享栈)。
- **未做 / 留合并门**:match_score 归一窗口标定;附件检索侧消费(下一迭代);真 Casbin 六类权限点 + 操作日志 + AI 页脚落地;真流式
  首 token<3s 验证;theme/关联内规/违规主题 依赖 clause_tags 打标·clause_references·案例 L2(未落即省略)。

## N2+N4 意图识别接 LLM(场景+八路路由,DeepSeek v4)(2026-06-30,分支 `feat/query-intent-llm`,commit `ab4a58f`,**未合并**)

> 背景:业务方给了两份真实业务问句集(`东方/提问方式.docx` 18 条 + `东方/应用场景.docx` 5 条,合 23 条),要求把 N0/N2/N4
> 的 LLM 接缝真正接上并实测识别正确率(此前 N0 归并接缝已就绪,N2 场景分类 / N4 八路路由此前是纯规则、无 LLM 接缝)。

- **flash vs pro 选型(实测,非拍脑袋)**:定稿 22 问上,规则基线 45.5%(10/22,几乎全是"…吗/合规吗/是否违反要求"判定句被
  误判 evidence)、**flash 100%(22/22,2.26s)**、pro 95.5%(21/22,3.50s,错 P9 列举→evidence)。上一轮(校对前 23 问)两者
  打平 87%,但 pro 在明显判定句 P10 上栽了(flash 对)。**结论:N0/N2/N4 全用 `deepseek-v4-flash`;pro 留给主答生成
  (R1/R5)**——意图本质是分类任务,flash 够、更快。一次 LLM 调用同出 scene+route(避免双往返);matters/entity 仍守规则
  词典,不让 LLM 乱造 entity_type。
- **黄金集校对是业务方拍板,非模型算出来的**:`应用场景.docx` 里 S1(上市公司控股子公司 PE 与关联方 PE 监管认定)、
  S3(并购重组换股辨析)、S4(会计估计变更辨析)三条是专业辨析题,两模型也互有分歧。业务方最终拍板:**S4 舍去不用**
  (不进 golden);**S1、S3 都定为 `evidence`(R1)**(判定型 judgmental 与拒答 refuse 都被排除)——与作者初稿一致但是
  业务方明确认可后才定稿,不是从正确率数字推出来的。
- **非显然踩坑:`temperature=0` 不能让推理模型确定性稳定**。给共享 `pipeline.llm_client` 加 add-only `temperature`
  参数并给意图/归并客户端钉 0 后,重跑两次仍有差异(flash run1 21/22、run2 20/22;pro 两轮各错不同题)。原因:
  `deepseek-v4-flash/pro` 是**推理模型**,每次都带 `reasoning_tokens`,思维链本身是采样出来的(叠加 MoE 路由/批处理抖动),
  `temperature=0` 只压掉一部分方差。**残留抖动只落在 3 个本就边界的题(S1/S3/P9),其余 19/22 明确项跨轮完全稳定**。
  要彻底消抖需要「多数票」(多次调用取众数),**评估过但未做**,记为后续。
- **待续 / open**:
  - `feat/query-intent-llm`(commit `ab4a58f`)是**独立分支,未合并**——它是在 `fix/clause-tree-law-conventions`(条款树/
    解析线)工作期间并行做的,业务方明确"不管另一分支",两条线互不影响,合并时机待业务方后续指示。
  - 多数票消抖机制未实现。
  - 模型门控回归测试 `test_intent_integration.py` 本地真 gateway 验证过(12 个稳定明确项全对),但**尚未过 Codex 复审**。

## audit-biz 边界契约:query 侧待改动发现(2026-07-01,来自姊妹仓 audit-biz Track0 SPEC-BOUNDARY)

> 姊妹仓 audit-biz(Java,新建于 `~/Projects/audit-biz`,承接 v0.4 后端设计的对外服务)起草 v0.4 §8 边界契约(biz↔audit-ai
> REST/SSE)时读了本仓 `query/query/contract.py` 以对齐 §10 输出契约,过程中发现一处**架构张力**,记于此供 Track B 排期时用。

- **发现**:`contract.py` 现 `Citation` 是 audit-ai **自己回查 PG 装配满**(`doc_title`/`doc_no`/`clause_path`/`page_start`/
  `page_end`/`version`/`status` 全填,MVP 阶段 audit-ai 即自身"后端");但 v0.4 §8.2 定 audit-ai 应**无状态**,边界只回轻量
  `clause_id`/`chunk_id`,完整回查装配移到 biz 侧(Java 收口)。这是 v0.4 设计**已定**的约束,不是重开讨论——只是这次落地
  contract-first SPEC 时才显式碰到,此前 MVP 实装未对齐。
- **待办(Track B / Task B3,尚未实装)**:给 `Citation` 加"轻量引用模式"(只出 `clause_id`/`chunk_id`,完整字段可选/可关),
  配合起 FastAPI 包裹现有 `query`/`pipeline` 域函数暴露 `/retrieve`(+`/generate`,其余 `/compare`/`/ocr`/`/ingest-batch` 后续)。
  本会话只在 audit-biz 侧完成了字段对照表(Checkpoint A 已冻结,三列:`contract.py` 产出 → 边界 v1 → biz 装配后),本仓
  代码**未改动**。
- **顺带核实(现状,非新决策)**:`query/` 已有前端向 HTTP/API 层(阶段 B-API `query/query/api/*`,PR #39 合并),但**尚无 v0.4 §8 的 biz↔ai 边界端点**(`/retrieve`、`/generate`);`understand/router.py` 是语义路由,非 web 路由;
  `route_type`(8 值)/`review_required`/`exhausted_scope` 均已在 `contract.py` 就位,边界可直接复用无需新增字段;Langfuse
  trace 现按内部 name 建、未接外部 `request_id`——biz 若要关联 trace,只需在边界调用时注入 `request_id`,不需 query 侧改动。
