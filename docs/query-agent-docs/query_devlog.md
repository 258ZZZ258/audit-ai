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
  AI 辅助标识),**不向甲方承诺判定结论**,交付标注待甲方(张益)确认。待 Codex 复审。
