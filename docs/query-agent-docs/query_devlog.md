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
