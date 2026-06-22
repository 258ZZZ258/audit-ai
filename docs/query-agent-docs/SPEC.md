# Spec: 制度查询智能体 MVP(R1 依据查询 + 覆盖感知拒答 + 八路路由/输出契约骨架)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**(批准后才进 Phase 2 PLAN)。
> 上游设计:`docs/制度查询智能体_技术框架设计_v1_0.md`(v1.0,功能1)。本 spec 是其**可实现切片**,不复述全文。
> 消费的语料资产由 V1.6 摄取管线产出(本仓 `pipeline`),本切片**只读消费**。

---

## 0. 切片边界(本次做什么 / 不做什么)

| | 范围 |
|---|---|
| **做** | R1 依据查询**端到端**;覆盖感知拒答(§8);**八路路由骨架**(R1 实装 / R7 澄清纯对话 / R8 兜底拒答实装,R2–R6 为诚实占位);统一 JSON 输出契约(§10 全字段);引用 ID 注入式生成(§7.1)+ 四级锚点 PG 回查(§7.3) |
| **不做(本切片)** | HyDE(N1)、案例桥接通道(§6.3)、R2 变更 / R3 案例 / R4 列举 / R5 判定 / R6 统计的**实装**(仅留路由占位)、多模型复核(§9.2)、多轮上下文归并(N0)的完整实现、前端、导出、Casbin/SSO/敏感词、Langfuse 全链路 |

**为何先做 R1+拒答+骨架**:这是文档三条红线(无编造引用 / 无裸结论 / 可解释拒答)的**最小承载切片**,且只依赖**已验证存在**的上游资产,复用 `pipeline` 已有的混合检索脊柱。R2–R8 的实装在此骨架上增量扩展。

---

## 1. Objective

**构建什么**:一个 Chatbox 型、同步流式的**制度查询智能体 MVP**,把审计/合规人员的口语问句转成对 `audit_corpus` 的混合检索,经充分性自检后**只用检索上下文中带 `clause_id` 的内容**生成带四级引用的回答;依据不足时给**覆盖感知拒答**而非编造。

**用户**:审计部 / 合规部人员(普通员工 / 主管 / 总经理三级权限,本切片权限**预留不实装过滤**,与摄取侧 `perm_tag` 写入但不过滤一致)。

**成功长相**:对一条 R1 依据型问句("费用报销发票 3 个月的规定在哪"),系统返回统一 JSON 契约,`citations[]` 每条都能四级回溯(条款→文档→页码→版本)且 `clause_id` 必在检索上下文内;对无依据问句返回 `route_type=refuse` + `exhausted_scope`,**绝不出现编造发文字号/条号,绝不出"违规/合规"裸结论**。

---

## 2. Tech Stack

- **语言/运行时**:Python 3.11(`.venv`,与本仓一致;`setuptools<81` 钉)。
- **新包**:`audit-query`(import 名 `query`,成员 `query/query/`),镜像 `eval/` 的打包方式。
- **依赖方向(DAG 无环)**:`query → pipeline → common`。`query` 复用 `pipeline` 的检索/嵌入/Milvus I/O 与 `common` 的契约;**不得反向被 pipeline import**。
- **编排**:LangGraph(运行时状态机,§1.2)——节点 = N0–N4/路由/检索/生成/拒答,边 = 条件路由。
- **检索(复用本地真栈,不重造)**:
  - `pipeline.index.milvus_io`:dense+sparse 混合检索 + `RRFRanker` + 默认 `status=="effective"` 过滤 + hybrid 失败 dense-only 兜底(`retrieval_mode` 标记)。
  - `pipeline.index.embedding_client`:`EmbeddingClient` ABC + `LocalBGEM3Client`(查询向量化,dense+sparse 一次产出)。
  - 权威回查:`common.pg_models`(`Chunk` 全文 + 四级锚点 + `parent_chunk_id`;`DocVersion` 版本/状态)。
- **LLM(可配置工厂,默认 stub)**:复用/扩展 `pipeline.llm_client`(OpenAI 兼容 `chat_json`)。新接缝 `query.llm.LLMClient`(Protocol/ABC + `from_config`),`QUERY_LLM_BACKEND` 选后端:**默认 `stub`(零网络、确定性回显,供测试)**,`gateway`=OpenAI 兼容网关(Qwen3.5 主答)。与摄取侧"LLM 默认全关"一致。
- **重排(可选接缝)**:`query.rerank` Protocol;**默认 `none`(直接用 RRF 融合序)**,`bge`=bge-reranker-v2-m3(需本地模型,门控 skip)。§5.5 的 top50→top8 待 reranker 落地。
- **配置**:复用 `config/settings.toml`(新增 `[query]` 段:topk、分区配额、充分性阈值、`llm_backend`、`rerank_backend`)。⚠ 可调值集中此处,绝不硬编码。

---

## 3. Commands

```bash
# 安装(开发,沿用本仓 -e 链;新增 query 包)
pip install -e libs/common && pip install -e pipeline && pip install -e eval \
  && pip install -e query && pip install -e ".[dev]"

# 起停本地真栈(复用现有 demo;含 pg+milvus、alembic upgrade、seed)
demo up            # 检索/回查依赖真栈
demo down          # 收栈(保留卷)

# 新 CLI(本切片入口;thin shell over 域函数)
query ask "费用报销发票3个月的规定在哪"            # R1 端到端,打印契约 JSON
query ask "<q>" --corpus internal|external --topk 8 --json
query route "<q>"                                  # 仅打路由判定 + 置信度(调试)

# 测试(沿用根 pyproject 配置;query/tests 纳入 testpaths)
.venv/bin/python -m pytest -q                       # 全量(含 query)
.venv/bin/python -m pytest query/tests -q           # 仅 query
PIPELINE_EMBEDDING_MODEL=<本地BGE-M3目录> HF_HUB_OFFLINE=1 \
  .venv/bin/python -m pytest query/tests -q         # 含真向量检索集成

# Lint(沿用 E/F/I/UP/B,行宽 100;known-first-party 增 query)
.venv/bin/ruff check .
```

---

## 4. Project Structure

```
query/                         # 新包 audit-query(镜像 eval/)
  pyproject.toml               # name=audit-query, deps=[audit-pipeline]
  query/                       # import 根
    __init__.py
    graph.py                   # LangGraph 装配:节点 + 条件边(运行时状态机 §1.2)
    understand/                # 查询理解前端(§3)
      router.py                # N4 八路意图路由(轻量分类;骨架:R1/R7/R8 实装)
      classify.py             # N2 场景/事项/entity_type(MVP:规则+词典,LLM 可选)
      __init__.py             # N0 归并 / N1 HyDE / N3 分解 —— 本切片留 stub
    retrieve/
      hybrid.py               # 调 pipeline.milvus_io 混合检索 + 分区配额(§5.2)+ 过滤(§5.3)
      sufficiency.py          # N5 充分性自检 / 覆盖语境判据(§8.1)
    generate/
      citation_inject.py      # §7.1 引用 ID 注入式 prompt 构造
      anchors.py              # §7.3 四级锚点从 PG 回查注入
      r1_evidence.py          # R1 主路径编排
    refuse/
      coverage_refusal.py     # §8.2 覆盖感知拒答话术 + exhausted_scope
    contract.py               # §10 统一输出契约 dataclass + 序列化
    llm/
      client.py               # LLMClient Protocol/ABC + from_config(QUERY_LLM_BACKEND)
      stub.py                  # 默认:零网络确定性回显
    config.py                 # 读 config/settings.toml [query] 段
    cli.py                    # `query` typer CLI(thin shell)
  tests/
    golden/                   # 路由 golden set + R1 引用 golden(准入门)
    test_router.py
    test_citation_faithfulness.py
    test_coverage_refusal.py
    test_contract.py
    test_r1_integration.py    # 连真栈,栈未起则 skip

docs/query-agent-docs/
  SPEC.md                     # 本文件
  PLAN.md / TASKS.md          # Phase 2/3 产出
  query_devlog.md            # 开发记忆(决策/踩坑),纳入 CLAUDE.md 模块索引
```

根 `pyproject.toml` 增量:`pythonpath`/`testpaths` 加 `query`/`query/tests`;`[tool.ruff.lint.isort] known-first-party` 加 `query`。

---

## 5. Code Style

沿用本仓既有风格:中文 docstring/注释、`from __future__ import annotations`、类型标注齐全、dataclass 承载契约、纯函数 + 接缝 ABC、⚠ 标可调值。示例(接缝 + 工厂,镜像 `embedding_client`/`parsing/factory`):

```python
from __future__ import annotations

from abc import ABC, abstractmethod

from query.config import QueryConfig


class LLMClient(ABC):
    """主答/分类 LLM 接缝。默认 stub(零网络),网关后端 OpenAI 兼容。"""

    @abstractmethod
    def chat_json(self, system: str, user: str) -> dict: ...

    @classmethod
    def from_config(cls, cfg: QueryConfig) -> "LLMClient":
        """按 ``QUERY_LLM_BACKEND``(默认 ``stub``)返回实现。"""
        backend = cfg.llm_backend
        if backend == "stub":
            from query.llm.stub import StubLLMClient
            return StubLLMClient()
        if backend == "gateway":
            from pipeline.llm_client import OpenAICompatClient  # 复用 PR#4 客户端
            return OpenAICompatClient.from_config(cfg)
        raise ValueError(f"未知 QUERY_LLM_BACKEND: {backend!r}(stub | gateway)")
```

---

## 6. Testing Strategy

- **框架**:pytest(沿用根 `pyproject` 配置);测试共置 `query/tests/`,共享 fixtures 复用根 `conftest.py`,集成测试连真栈、栈未起 `pytest.skip`。
- **测试层级与关注点**:
  | 层级 | 覆盖 | 网络/栈 |
  |---|---|---|
  | 单元 | 路由分类、契约序列化、引用注入 prompt 构造、拒答话术 | 无(LLM 用 stub) |
  | golden | **路由 golden set**(问句→正确 route_type,准入门)+ **R1 引用 golden**(问句→应命中条款/四级锚点)| 无(检索可 mock 或固定 fixture) |
  | 集成 | R1 端到端连真 PG+Milvus(`demo up` 后),含真混合检索 + PG 回查 | 真栈;模型门控 skip |
- **红线断言(硬性)**:
  - **引用真实性**:回答 `citations[].clause_id` ⊆ 检索上下文注入的 `clause_id` 集合(`test_citation_faithfulness`)。
  - **无裸结论**:R1/拒答输出**不含**"违规/合规"判定词(正则断言);判定型问句路由到占位而非裸答。
  - **可解释拒答**:无依据问句 → `route_type=refuse` + `exhausted_scope` 非空。
- **覆盖期望**:红线相关路径(注入/回查/拒答/路由)接近全覆盖;LLM stub 保证默认套件零网络可跑。
- **提交前**:`ruff check .` 0 报 + 全量 pytest(模型门控无模型时 skip);新 golden 纳入回归。

---

## 7. Boundaries

- **Always(总是)**:
  - 引用只能来自检索上下文中带 `clause_id` 的块;四级锚点一律从 PG `chunks`/`doc_versions` 回查(不用 Milvus 截断 `text`)。
  - 检索默认 `status=effective` 过滤;`query` 不被 `pipeline`/`common` 反向 import(DAG 无环)。
  - 可调值入 `config/settings.toml [query]`;LLM 默认走 stub(零网络);提交前跑 ruff + pytest。
- **Ask first(先问)**:
  - 改动 `common` 契约 / PG schema / Milvus schema(本切片**应为纯只读消费,预期零契约改动**;若需改先回到 spec)。
  - 新增第三方依赖(LangGraph 除外,已在 stack 决策内)、改 CI、引入新模型。
  - 实装任何 R2–R6 路由(超出本切片,需新 spec/任务)。
- **Never(绝不)**:
  - 让 LLM 凭记忆生成发文字号/条号;输出"违规/合规"裸结论;回写任何源系统(单向只读红线)。
  - 默认路径发起真实 LLM/网络调用;删除失败测试或绕过红线断言。

---

## 8. Success Criteria(可测、具体)

1. `query ask "<R1问句>"`(`demo up` 后)返回合法 §10 契约 JSON,`route_type=evidence`,`citations[]` ≥1 且每条四级锚点字段齐全。
2. `test_citation_faithfulness` 通过:回答引用的 `clause_id` 全部 ∈ 检索上下文(零编造)。
3. `test_coverage_refusal` 通过:构造无依据问句 → `route_type=refuse` + `exhausted_scope` 非空 + 含"未检索到…明确禁止性规定"话术。
4. `test_router` 通过:R1/R7/R8 三类 golden 问句路由正确;R2–R6 问句进诚实占位(`route_type` 正确但标"本切片暂未实装",不裸答、不报错)。
5. `test_contract` 通过:契约含 `route_type/answer_blocks/citations/confidence/ai_label/review_required/exhausted_scope/export_enabled` 全字段且类型正确。
6. 默认 `pytest -q` 全绿且**零网络**(LLM=stub);设本地 BGE-M3 后集成测试连真栈跑通 R1。
7. `ruff check .` 0 报;`query` 入 `known-first-party`、依赖 DAG 仍无环(`pipeline` import 期不依赖 `query`)。

---

## 9. Open Questions(需人工/甲方输入;多为 v1.0 §15 P0)

| # | 事项 | 影响 | 本切片默认处置 |
|---|---|---|---|
| Q1 | 网关轻量小模型(路由/分类用)是否可用(§15-①)| 路由/分类是 LLM 还是规则 | **默认规则+词典分类,LLM 可选**;不阻塞 |
| Q2 | embedding endpoint 是否暴露 dense+sparse 双输出(§15-②)| gateway 检索后端可行性 | 本切片检索**走本地 BGE-M3 真栈**,endpoint 留桩 |
| Q3 | R5 判定型"不出裸结论"产品形态(§15-④,P0)| R5 验收口径 | 本切片 R5 **仅占位**,不实装;红线靠 R1/拒答守 |
| Q4 | 缺失查询侧资产:`dict_scenario_terms`/`dict_intent_routes` 未建 | HyDE/事项桥接/路由样例库 | 本切片**不依赖**(HyDE/桥接不做;路由用内置种子样例)|
| Q5 | `clause_references` 空表、`ref_resolver` 未实现(本会话已建表标 TODO)| R1/R2 多跳确定性拦截 | 本切片 R1 **不依赖多跳**;表存在即可,数据后补 |
| Q6 | 重排模型 bge-reranker-v2-m3 本地是否可得 | §5.5 top50→top8 | 默认 `rerank=none`(用 RRF 序),reranker 可选接缝 |
| Q7 | LangGraph 作为新依赖是否批准 | 编排实现 | spec 默认采用(可换轻量自研状态机,待定)|
| Q8 | 输出契约 `confidence` 的来源/口径 | 契约字段语义 | 默认置检索融合分归一 ⚠,待标定 |

---

## 10. 验证清单(进入 Phase 2 前)

- [ ] 六大块齐全(Objective/Commands/Structure/Style/Testing/Boundaries)—— ✅ 本文件
- [ ] 成功标准具体可测 —— ✅ §8
- [ ] 边界三档清晰 —— ✅ §7
- [ ] spec 落盘 —— ✅ `docs/query-agent-docs/SPEC.md`
- [ ] **人工复核批准** —— ⏳ 待你确认(尤其 §0 切片边界、§9 Open Questions 的默认处置)
