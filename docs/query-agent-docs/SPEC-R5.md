# Spec: R5 判定型路由(三段式硬约束 + 不出裸结论 + 案例桥接入口 + §9.2 复核接口)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。**P0 红线核心**(GAP backlog #1)。八路**最后一路收官**。
> 延续 MVP/R2/R3/R4/R6 范式(纯函数 + 节点薄封装、零 LLM 默认、consumed-when-present)。上游设计:
> `制度查询智能体_技术框架设计_v1_0.md` §6.5 / §8.3 / §8.4 / §9.2 / §7.4 / §10。本文件只述 R5 增量。
> **§15-④ 产品形态**:按 §6.5 三段式作 **demo workaround** 实装(人工复核必需 + 代码后检无裸结论),
> 交付标注**待甲方(张益)确认**,**不向甲方承诺判定结论**。
> **已决(2026-06-24,AskUserQuestion)**:构成要件框定=**clause直呈 + LLM toggle(默认关)**;不出裸结论=
> **形态(无 verdict 槽)+ 代码后检 always-on + §9.2 复核接口+toggle(默认关)**;桥接入口=**复用 R3 桥接**。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **R5 路由实装**(替占位):`route_type=judgmental` + `review_required=true`。触发 = N2 `BEHAVIOR` scene → `JUDGMENTAL`(已分类/路由)。检索 = ① **桥接入口**(复用 R3:`retrieve_cases(behavior)` → 命中案例 `cited_regulations` → 反查/定位外规条款,**consumed-when-present** 默认空→降级)∥ ② **hybrid 检索**(内规+外规,复用 R1)。**三段式硬约束输出**(§8.3,**无 verdict 槽**):① 依据条款(四级锚点 `citations`)② **构成要件框定**(clause直呈;LLM 抽取适用前提/对象/行为类型 toggle 默认关)③ "AI 辅助判断,建议人工复核"标识。**不出裸结论(红线)**:形态无 verdict 槽 + **代码后检 always-on**(扩 `sanitize`:verdict 词 + 试探性表述→中性/降"待核实")。**§9.2 多模型复核接口 + toggle(默认关)**。空/不足→覆盖拒答。graph JUDGMENTAL→r5_judgment → **八路全实装**。 |
| **不做** | §9.2 真 LLM 复核默认开(toggle 默认关;真复核需 gateway+第二模型,RL-1 真-LLM 闭环留 §9.2 单独轮)。LLM 构成要件抽取默认开(toggle 默认关,默认 clause直呈)。`cited_regulations` L2 生产打标(consumed-when-present 默认空,§15-⑤)。§9.2 触发**重生成**(降"待核实"即可,重生成留后续)。bge-reranker(§5.5)/sparse 提权(§5.4)/流式(§7.2)/Excel 导出。多标签优先级裁决细化(router 已含 判定>统计>…)。 |

## 1. Objective

让**判定型(行为合规/违规咨询)**问句以**形态隔离裸结论**(§6.5/§8.3):**绝不答"违规/合规"**,只给
① 依据条款 ② 构成要件框定 ③ 人工复核标识(§0.1-1 红线核心)。

成功 = behavior 问句 → `route_type=judgmental` + `review_required=true` 契约,三段式块,**绝不出违规/合规
裸结论**(形态无 verdict 槽 + 代码后检覆盖 verdict 词与试探性表述),条款逐字命中四级锚点;桥接入口
consumed-when-present(默认空→hybrid-only);§9.2 复核接口可开;默认零-LLM(stub)。

## 2. Tech Stack(增量)

- 复用 `query/` 既有:`contract`(`RouteType.JUDGMENTAL`/`review_required` **已存在**)/`state`/`graph`/
  `understand.classify`(`SceneType.BEHAVIOR` 已分类)/`understand.router`(judgmental 已路由)/
  `retrieve.hybrid`(R1 混合检索)/`case`(`retrieve_cases` + `bridge.norm_ref`)/`generate`(`anchors` +
  `citation_inject` + `sanitize_answer`/`select_faithful`)/`refuse.coverage_refusal`/`llm`(stub/gateway)。
- 复用 `pipeline` 脊柱:`Retriever` + `PgIO`(外规条款定位回查)+ `common.pg_models`(Chunk/DocVersion/Case)。
- 新增 `query/query/judge/`:`framing.py`(三段式构成要件框定 + 不出裸结论后检)+ `review.py`(§9.2 复核接口)+
  `r5_judgment.py`(编排)。
- `config` +`judge_constituent_llm`(默认关)/`judge_multimodel_review`(默认关)。
- **零新依赖、默认零-LLM(stub)、零契约改动**(`review_required` 已存在)。

## 3. Commands

```bash
demo up                                       # R5 集成需 PG + Milvus + 本地 BGE-M3(同 R1/R3/R4)
query ask "二维码介绍开户是否违规"             # → route_type=judgmental 三段式(无裸结论,人工复核框)
query ask "见底到顶的隔墙是否合规"             # → 同上;桥接默认空→hybrid-only
.venv/bin/python -m pytest query/tests/test_framing.py query/tests/test_r5_judgment.py \
  query/tests/test_r5_judgment_integration.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/judge/
  __init__.py
  framing.py     # 三段式:build_framing(clause直呈;LLM抽取 toggle)+ strip_bare_conclusion(扩 sanitize:verdict+试探性)
  review.py      # §9.2 多模型复核接口:review_tentative(blocks, llm, qcfg) —— toggle 关→passthrough,开→第二 LLM 校验
  r5_judgment.py # answer_judgment(query, retriever, pg, llm, qcfg) → QueryResult(judgmental, review_required=True)
                 # 含 bridge 入口 resolve_cited_clauses(pg, cases)(consumed-when-present)
query/query/graph.py   # JUDGMENTAL → r5_judgment 节点(替 placeholder,删最后一个 _PLACEHOLDER_NOTE)
query/query/config.py  # +judge_constituent_llm / judge_multimodel_review
query/tests/
  test_framing.py                 # 纯单元:三段式结构(无 verdict 槽)、clause直呈、LLM toggle、不出裸结论后检(verdict+试探性)
  test_r5_judgment.py             # 单元(fake retriever/pg/llm):judgmental+review_required、桥接 consumed-when-present、空→拒答、无裸结论
  test_r5_judgment_integration.py # 连真栈(PG+Milvus+BGE-M3):behavior问句三段式真数据、四级锚点、断言无裸结论、桥接手插验入口
docs/query-agent-docs/SPEC-R5.md / PLAN-R5.md / TASKS-R5.md
```

## 5. Code Style

沿用既有(中文 docstring、`from __future__ import annotations`、frozen dataclass、纯函数 + 节点薄封装)。
**三段式无 verdict 槽**(blocks 只承载 依据/框定/标识,无"判定"字段);不出裸结论后检扩 `sanitize_answer` 词表:

```python
_VERDICT = ("违规", "违法", "合规", "合法")              # 复用 R1 sanitize 口径
_TENTATIVE = ("可能违反", "疑似违规", "涉嫌", "倾向于不合规", "构成违")  # R5 §9.2 试探性表述
_NEUTRAL = "相关依据见所引条款原文;是否构成违规须人工对照构成要件判断(本系统不作判定)。"

def strip_bare_conclusion(text: str) -> str:
    """含 verdict / 试探性表述 → 替中性'待人工核实'(保留引用),守红线(形态外的 always-on 兜底)。"""
    return _NEUTRAL if any(t in text for t in (*_VERDICT, *_TENTATIVE)) else text
```

## 6. Testing Strategy

- **单元(零栈零模型)**:
  - `framing`:三段式结构(① citations ② 框定 ③ 标识)、clause直呈框定、LLM 抽取 toggle 开/关、**断言无 verdict 槽**(结构无"判定"字段)。
  - `strip_bare_conclusion`(**红线核心**):verdict 词("违规/合规")+ 试探性("可能违反/疑似违规/涉嫌/倾向于不合规")→ 替中性;纯中性/依据文本不动。
  - `review`:toggle 关→passthrough;开→第二 LLM(fake)校验试探性是否被引用支持,不支持→降"待核实"。
  - `r5_judgment`(fake retriever/pg/llm):`route_type=judgmental` + `review_required=true`、三段式块、桥接 consumed-when-present(cited 空→hybrid-only)、空→覆盖拒答、**默认无裸结论**。
- **集成(gate = PG + Milvus + 本地 BGE-M3,同 R1/R3/R4)**:behavior 问句 → 三段式真数据、四级锚点 PG 权威、**断言输出无违规/合规裸结论**、桥接**手插 `cited_regulations`** 验入口(同 R3 手插-复位)。
- **红线断言**:任何路径输出**不含违规/合规裸结论**(verdict + 试探性后检);`review_required=true`;条款逐字命中四级锚点;默认零-LLM。

## 7. Boundaries

- **Always**:三段式**无 verdict 槽**;**代码后检 always-on**(verdict + 试探性→中性/待核实);`review_required=true`;四级锚点 **PG 回查**;桥接 **consumed-when-present**;默认**零-LLM(stub)**;**不向甲方承诺判定结论**(AI 辅助 + 人工复核必需)。
- **Ask first**:改 `contract` / PG schema(**预期零改动**,`review_required` 已存在;纯只读 + 新增 `judge` 子包);新增依赖;§9.2 真复核默认开。
- **Never**:出"违规/合规"**裸结论**(任何路径);臆造条款 / 四级锚点;LLM 自由生成**绕过三段式**结构;§9.2 关时仍声称已复核。

## 8. Success Criteria(可测)

1. behavior 问句 → `route_type=judgmental` + `review_required=true` 的 §10 契约,三段式(① 依据条款 `citations` ② 构成要件框定 TEXT ③ "AI 辅助判断,建议人工复核"标识 TEXT)。
2. **不出裸结论(红线)**:输出**绝不含"违规/合规"裸结论**;`strip_bare_conclusion` 覆盖 verdict 词 + 试探性表述("可能违反/疑似违规/涉嫌/倾向于不合规")→ 替中性/降"待核实";`test_framing` + 集成断言。
3. **构成要件框定**:clause直呈(命中条款适用边界结构化呈现);LLM 抽取 toggle(**默认关→clause直呈**,开→适用前提/对象/行为类型,consumed-when-present)。
4. **桥接入口**:复用 R3 `retrieve_cases` + `cited_regulations` 反查外规条款(**consumed-when-present**:默认空→降级 hybrid-only);手插 `cited_regulations` 集成验机制。
5. **§9.2 复核接口**:toggle(**默认关**→代码后检+形态保障;开→第二 LLM 校验试探性是否被引用支持,不支持→降"待核实")。
6. 四级锚点 **PG 权威**;条款逐字命中;**默认零-LLM(stub)**。
7. graph JUDGMENTAL→r5_judgment(替 placeholder,删最后一个占位);**八路全实装(无 placeholder)**;router 回归。
8. R5 集成(PG+Milvus+BGE-M3)绿;全仓全量 + ruff 全绿;**DAG 无环**(`query → pipeline → common`)。

## 9. Open Questions(已决 3 项 + 默认待 gate 确认)

| # | 事项 | 处置(✅=AskUserQuestion 已定 / 默认待确认) |
|---|---|---|
| **框定生成** | 构成要件框定(§6.5②) | ✅ **clause直呈(零-LLM 默认)+ LLM 抽取 toggle(`judge_constituent_llm` 默认关)**。 |
| **红线落实** | 不出裸结论 + §9.2 | ✅ **形态无 verdict 槽 + 代码后检 always-on(扩 sanitize 覆盖试探性)+ §9.2 复核接口+toggle(`judge_multimodel_review` 默认关)**。 |
| **桥接入口** | behavior→R5 入口(§6.5 首步) | ✅ **复用 R3 `retrieve_cases` + `cited_regulations` 反查外规条款**(consumed-when-present,默认空→hybrid-only)。 |
| Q1 | 三段式 block 形态 | 默认:`citations[]`=① 依据条款四级锚点;`answer_blocks`=[TEXT ② 框定, TEXT ③ AI辅助/人工复核标识];`review_required=true`。不新增 BlockType。 |
| Q2 | 试探性表述词表 | 默认 `("可能违反","疑似违规","涉嫌","倾向于不合规","构成违")` + 复用 R1 verdict `("违规","违法","合规","合法")`;⚠ 钝兜底,宁过滤勿漏(§9.2 精确版留 toggle)。 |
| Q3 | §9.2 不支持的处置 | 默认**降"待核实"/改中性**(不触发重生成,重生成留后续)。 |
| Q4 | 集成 fixture | 默认 PG+Milvus+BGE-M3,behavior 问句;桥接**手插 `cited_regulations`**(仿 R3/R4),验入口后复位空。 |
| Q5 | 充分性/拒答 | 默认:检索空/无忠实条款→`refuse_coverage`(同 R1/R4 红线兜底,不出空 judgmental)。 |

## 10. 与 §15-④ / §6.5 / §9.2 的关系

- **§15-④ 产品形态**:按 §6.5 三段式作 **demo workaround** 实装(`review_required` 人工复核必需 + 代码后检无裸结论
  + AI 辅助标识),**不向甲方承诺判定结论**;交付标注**待甲方(张益)确认**是否满足业务期望(验收口径)。
- **§9.2 真 LLM 复核 / `cited_regulations` L2 生产 / LLM 构成要件抽取**:toggle **默认关**(consumed-when-present),
  留接缝;真-LLM 闭环(RL-1 🟡→✅)另轮(§9.2 主答 Qwen3.5 + 复核 Kimi 真接,需 gateway)。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§7 红线 always-on 代码后检、§8 SC2 不出裸结论、§9 框定/红线/桥接 + §10 §15-④ 产品形态 demo workaround)
