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
