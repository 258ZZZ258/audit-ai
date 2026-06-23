# Spec: R3 相似案例 + 案例桥接(case 分区检索 + 要素回填 + 附挂到 R1)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md P1(backlog #4 / 依赖资产 #9)。延续 MVP 切片
> 的包/范式/基础设施(见 `SPEC.md`)与 R2 范式(见 `SPEC-R2.md`),本文件只述 R3 增量。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §6.3 / §2(`cases` 资产)/ §10。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | (a) **R3 路由实装**(替占位):`route_type=case` —— case 分区(P-CASE)语义检索 → 按 `doc_version_id` 去重(一案一卡)→ PG `cases` **要素回填** → CASE_CARD 卡片块 + §10 契约。<br>(b) **附挂通道**(§6.3 V1.4 后置):R1 **依据查询充分答复**尾部追加 top-N 相关案例卡片(**语义检索 ∪ 精确反查**)。<br>(c) **精确反查桥接原语**(§6.3 CP-007):`cases.cited_regulations` ↔ 外规条款的反查纯函数(**consumed-when-present**)。**全程零 LLM**。 |
| **不做** | **桥接-as-入口**(behavior 咨询型问句的检索入口 → R5 主答上下文):R5 仍占位、受 §15-④ 阻塞,本轮不做。<br>L2 `cited_regulations` **生产**(默认关;只**消费**已有值,缺失诚实降级)。<br>`chunk_type=case_summary` 主命中面**强过滤**(`milvus_io.search` 未输出 `chunk_type`,GAP #12 → 暂以"一案一卡"去重替代)。<br>bge-reranker(案例检索默认 `none`/RRF 序)。R6 统计型 cases SQL(另路由)。violation_category/cited_regulations **缺失时的 LLM 补抽**。 |

## 1. Objective

两件事:
1. 用户直接问"**有没有类似处罚案例**"(`SceneType.CASE` → `RouteType.CASE`)→ 走 case 分区语义检索 →
   要素回填 → **案例卡片**输出(标题 + 处罚机构 + 日期 + 当事人 + 处罚类型 + 金额;`cited_regulations`/
   `violation_category` 有则附,无则省)。
2. 用户做**依据查询**(R1)且答复充分 → 答复尾部**附挂** top-N 相关案例卡片(语义检索 ∪ 精确反查),
   标注"相关案例参考",**不构成案例分析**(§2 边界)。

成功 = 案例型问句返回 `route_type=case` 契约(含 ≥1 CASE_CARD,要素来自 PG `cases` 权威 L1 字段);R1
充分答复在 `cited_regulations` 存在的 fixture 下尾挂**精确反查**到的案例卡、在默认(空)路径下尾挂**语义检索**到的
案例卡;`cited_regulations` 缺失时**诚实降级**(无精确反查、不臆造引用),全程零 LLM。

## 2. Tech Stack(增量)

- 复用 `query/` 既有:`contract`(`BlockType.CASE_CARD` **已存在**、`RouteType.CASE` 已定义)/`state`/`graph`
  (LangGraph)/`understand.router`(case 已分类)/`retrieve.hybrid.Retriever`/`generate.anchors`。
- 复用 `pipeline` 脊柱:`milvus_io.search(corpus="P-CASE")`(case 分区检索)/`PgIO.get_case` /
  `PgIO.get(DocVersion, dvid)`(标题/文号/状态权威回查)。**零新依赖、零 LLM。**
- 新增 `query/query/case/`:`case_card.py`(纯函数组卡)+ `bridge.py`(精确反查纯函数)+ `r3_case.py`(编排)。
- 数据:PG `cases`(L1 要素:penalty_org/doc_number/penalty_date/respondent/respondent_type/penalty_type/
  amount_wan;L2 字段 violation_category/cited_regulations **默认空**)+ `doc_versions`(标题/文号/status)。

## 3. Commands

```bash
demo up                                       # R3 集成需真栈(PG + Milvus;检索用 BGE-M3)
query ask "有没有类似的处罚案例"               # → route_type=case 契约(案例卡片)
query ask "费用报销发票3个月的规定在哪"        # → route_type=evidence + 尾挂相关案例卡(附挂通道)
.venv/bin/python -m pytest query/tests/test_case_card.py query/tests/test_bridge.py query/tests/test_r3_case.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/case/
  __init__.py
  case_card.py     # build_case_card(case_row, doc_meta) → AnswerBlock(CASE_CARD);纯函数,只用已落字段
  bridge.py        # 精确反查纯函数:cases_for_clauses(cited_index, clause_keys) / norm_ref(...) —— consumed-when-present
  r3_case.py       # answer_case(query, retriever, pg, qcfg) → QueryResult:case 检索→去重→回填→卡片→契约
                   # + attach_cases(result, query, citations, retriever, pg, qcfg) → 附挂(供 graph._evidence 调)
query/query/retrieve/hybrid.py   # Retriever.retrieve_cases(query) → list[Candidate](corpus="P-CASE" 分区)
query/query/graph.py             # CASE → r3_case 节点(替 placeholder);evidence 节点充分答复后按开关附挂
config/settings.toml [toggles]   # attach_cases(默认 on)+ attach_topk(默认 3);案例检索分区配额复用 partition_topk
query/tests/
  test_case_card.py              # 纯单元:卡片组装(present/absent 字段、不臆造)
  test_bridge.py                 # 纯单元:精确反查(命中/未命中/cited_regulations 空 → 降级)
  test_r3_case.py                # 单元(纯函数编排部分:去重一案一卡、空命中→明示无案例)
  test_r3_case_integration.py    # 连真栈:ingest 案例件 → query ask 案例问句 → route_type=case 卡片;
                                 #          + 手插 cited_regulations fixture → R1 附挂精确反查验证
docs/query-agent-docs/SPEC-R3.md / PLAN-R3.md / TASKS-R3.md
```

## 5. Code Style

沿用既有(中文 docstring、`from __future__ import annotations`、frozen dataclass 承载、纯函数 + 节点薄封装)。
卡片组装为纯函数,只读 PG 已落字段、缺失字段省略不臆造:

```python
@dataclass(frozen=True)
class CaseCard:
    doc_version_id: str
    title: str | None          # doc_versions 权威
    penalty_org: str | None
    penalty_date: str | None   # ISO
    respondent: str | None
    penalty_type: str | None
    amount_wan: float | None
    violation_category: str | None         # L2,默认 None → 省略
    cited_regulations: list[str]           # L2,默认 [] → 省略;present 时供精确反查/展示

def build_case_card(case_row, doc_meta) -> AnswerBlock:
    """case 行 + 文档元数据 → CASE_CARD 块(content 为结构化 JSON 字符串)。缺失字段省略,零臆造。"""
```

## 6. Testing Strategy

- **单元(零栈零模型)**:
  - `case_card`:present/absent 字段组装;L2 空字段省略;不臆造引用。
  - `bridge`:`cited_regulations` 命中精确反查(同一外规条款 → 命中 cases)/未命中/**空 cited_regulations → 降级返回 []**;归一键匹配(`norm_ref`)。
  - `r3_case`:多 chunk 同案 → **去重一案一卡**;case 分区零命中 → 明示"未检索到相似案例"(不报错、不臆造)。
- **集成(gate 同 MVP:模型 + PG + Milvus + soffice)**:
  - ingest 一件处罚决定书(P-CASE)→ `cases` L1 要素入库 → `query ask` 案例问句 → 契约 `route_type=case` 含卡片(要素=PG 权威)。
  - **附挂**:`query ask` 依据问句(充分)→ 默认路径尾挂**语义**案例卡;**手插**一行 `cited_regulations`(仿 R2 手插 revision_notes)→ R1 citation 命中外规条款 → 尾挂**精确反查**案例卡。
- **红线断言**:卡片要素逐字来自 PG `cases`/`doc_versions`(不来自 Milvus 截断文本、不来自 LLM);`cited_regulations` 空时**无精确反查、无臆造外规引用**;附挂仅**真实命中**、零命中则不挂(不硬凑)。

## 7. Boundaries

- **Always**:R3 **零 LLM**(检索 + 回填 + 卡片机械组装);卡片/标题从 PG 权威回查;只用**已落**字段,L2 缺失则省略;附挂仅挂真实命中的案例卡;case 分区检索 `status==effective` 前置(复用 `milvus_io`);degraded 块不入卡片引用。
- **Ask first**:改 `common` 契约 / PG schema(本切片应**纯只读消费** + 新增 `[toggles]`,**预期零契约改动**);改动 R1 既有 evidence 生成/引用核心逻辑(附挂应为**追加 block**、不改既有块);新增依赖。
- **Never**:LLM **补抽** violation_category/cited_regulations 或**臆造**外规引用(§2 桥接精确反查红线);把案例当**案例分析**输出结论(§2 边界:仅"口语↔法言"桥接 + 依据附挂,不分析);回写源系统。

## 8. Success Criteria(可测)

1. `query ask "<案例问句>"` → `route_type=case` 的 §10 契约,含 ≥1 `CASE_CARD`(要素=PG `cases` L1 字段 + `doc_versions` 标题)。
2. **一案一卡**:同案多 chunk(case_summary + case_section)命中 → 去重为单卡;`test_r3_case` 绿。
3. **要素保真**:卡片字段逐字来自 PG;L2 字段(violation_category/cited_regulations)默认省略、**有值才展示**;`test_case_card` 绿。
4. **精确反查**:`cited_regulations` present → R1 citation 外规条款命中 → 附挂对应案例卡;**absent/空 → 降级语义-only、无臆造引用**;`test_bridge` 绿。
5. **附挂**:R1 充分答复尾部追加 top-N(默认 3)案例卡(语义 ∪ 精确反查);零命中**不挂**;附挂为**追加 block**,既有 evidence/citation 块不变。
6. **拒答不附挂**:覆盖感知拒答(`refuse_coverage`)答复**不**附挂案例(避免给拒答配案例);定位本切片只在 sufficient evidence 分支附挂。
7. **零 LLM**:默认路径零 LLM/网络调用(stub 都不需要 —— R3 检索 + 回填机械)。
8. R3 集成端到端(真栈案例件)绿;全仓全量 + ruff 全绿;DAG 无环(`query → pipeline → common`)。

## 9. Open Questions(Q1–Q4 已人工决策 2026-06-23,锁定如下)

| # | 事项 | 处置(✅=已定 / 默认) |
|---|---|---|
| Q1 | 附挂默认开/关 + top-N | ✅ `[toggles] attach_cases=on` + `attach_topk=3`;仅**充分 evidence** 答复附挂、零命中不挂、可关。 |
| Q2 | 附挂触发边界(§6.3"纯依据查询精确依据已足不走桥接") | ✅ `SceneType` 粗判:`definition`(概念判断型)**不**附挂;`evidence` 默认附挂。因果辨析等细化留后续。 |
| Q3 | 精确反查 match key(`cited_regulations` JSONB 条目 ↔ 外规条款身份) | ✅ 定义 `norm_ref`(发文字号/文号 + `clause_path_norm` 归一)为匹配契约 + fixture 验证;**真实 JSONB shape 随 L2 对齐落地校准**(§15-⑤ 待确认)。不依赖未建的 `clause_references` resolver。 |
| Q4 | CASE_CARD `content` 形状 | ✅ 沿用 `AnswerBlock.content: str` → 承载**结构化 JSON 字符串**(卡片字段),前端解析渲染;零契约改动。 |
| Q5 | case 分区检索配额 | 默认:复用 `partition_topk`;`chunk_type=case_summary` 主命中面偏好留后续(milvus 未输出 chunk_type,GAP #12 → "一案一卡"去重替代)。 |
| Q6 | `cited_regulations`/案例引用是否进 `citations`(四级) | 默认:present 且能解析到外规 chunk 时,精确反查外规条款**可**进 `citations`(四级回查);默认空路径不加。 |

## 10. 与文档 §15 待确认项的关系

- **§15-⑤**(案例库是否含"引用外规条款"结构化字段):`cases.cited_regulations` 列**已建**(schema 承诺),
  L2 默认关 → 默认空。本切片**不被阻塞**:实装"consumed-when-present"机制 + fixture 验证;真实 JSONB
  对齐 shape 随 L2 落地按 Q3 校准。**不向甲方承诺穷举/分析**(§2 边界)。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§8 红线断言、§9 默认处置 Q1/Q2/Q3)
