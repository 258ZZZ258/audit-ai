# Plan: 制度查询智能体 MVP —— 技术实现计划

> 状态:**Phase 2 / PLAN —— 已批准,进入 Phase 3 TASKS**。
> 依据:`docs/query-agent-docs/SPEC.md`(Phase 1 已批准)。切片 = R1 依据查询 + 覆盖感知拒答 + 八路路由/契约骨架。
> **已拍板决策**:① 编排采用 **LangGraph**(节点纯函数对冲锁定风险);② 充分性判据**接口按 §8.1 保真、实现先务实**;③ 总原则见 §2.5(设计保真接口 + `QueryState` 预定义)。

---

## 1. 组件与依赖图

```
            config.py ───────────────┐
                │                     │
   contract.py  │      llm/client.py + llm/stub.py   (接缝, QUERY_LLM_BACKEND)
       │        │              │
       ▼        ▼              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ retrieve/hybrid.py     understand/classify.py(N2)            │
  │   (复用 pipeline:        understand/router.py(N4,8路骨架)    │
  │    milvus_io 混合检索 +        │                              │
  │    embedding_client)          │                              │
  │      │                        │                              │
  │      ▼                        │                              │
  │ retrieve/sufficiency.py(§8.1)│                              │
  └──────┼────────────────────────┼──────────────────────────────┘
         │                        │
         ▼                        ▼
  generate/anchors.py(§7.3 PG四级回查,复用 common.pg_models)
  generate/citation_inject.py(§7.1 引用ID注入 prompt)
  generate/r1_evidence.py(R1 主路径编排)
  refuse/coverage_refusal.py(§8.2)
         │
         ▼
  graph.py(LangGraph 装配:router → {r1 / clarify / refuse / R2–R6 占位})
         │
         ▼
  cli.py(`query` typer thin shell)
```

**依赖方向硬约束**:`query → pipeline → common` 无环;`pipeline`/`common` 在 import 期**绝不**依赖 `query`(Phase A 检查点用 import 探针守)。

**复用点(不重造)**:
| 复用 | 来源 | 用途 |
|---|---|---|
| 混合检索 dense+sparse + RRF + `status=effective` + dense-only 兜底 | `pipeline.index.milvus_io` | `retrieve/hybrid.py` |
| 查询向量化(BGE-M3 dense+sparse 一次产出) | `pipeline.index.embedding_client.LocalBGEM3Client` | `retrieve/hybrid.py` |
| 权威条款回查(全文/锚点/版本) | `common.pg_models.Chunk` / `DocVersion` | `generate/anchors.py` |
| OpenAI 兼容 LLM 客户端 | `pipeline.llm_client`(PR#4) | `llm/client.py` gateway 后端 |
| 接缝工厂 idiom(ABC + `from_config` + env 后端) | `embedding_client` / `parsing/factory` / `orchestration` | `llm/`、`rerank` 接缝 |
| 集成测试造件(ingest 一小件到真栈) | 根 `conftest.py`(`unique_docx`/`ingest_index`) | `tests/test_r1_integration` |

---

## 2. 实现顺序(分阶段 + 检查点)

> 每阶段 TDD:先写该阶段的红线/契约断言测试,再实现到绿。检查点不过不进下一阶段。

### Phase A —— 地基与契约(串行,最先)
- 建包 `query/`(pyproject 镜像 eval)、根 `pyproject` 增 `pythonpath`/`testpaths`/`known-first-party`。
- `config.py`(读 `config/settings.toml [query]`:topk、分区配额、充分性阈值、`llm_backend`、`rerank_backend`)。
- `contract.py`(§10 契约 dataclass + 序列化 + 校验)。
- `llm/client.py`(LLMClient ABC + `from_config`)+ `llm/stub.py`(零网络确定性:从上下文**选前 N 个 clause_id**,使引用注入可被测)。
- **检查点 A**:`pip install -e query` 成功;`query --help` 可跑;`test_contract` 绿;`ruff check .` 0 报;**DAG 无环探针**(`python -c "import pipeline"` 不触发 import query)。

### Phase B —— 检索与回查脊柱(可与 C 并行)
- `retrieve/hybrid.py`:查询→`embedding_client` 向量化→`milvus_io` 混合检索(内规∥外规分区配额各 top25,§5.2)→过滤位 `status`/`perm_tag`(预留)/`entity_type`/`biz_domain`(§5.3)。
- `generate/anchors.py`:命中 `chunk_id` → PG 回查四级锚点(`clause_path`/`doc_version_id`/`page_start/end`/`version+status`),父块供证(§5.6 `parent_chunk_id`)。
- **检查点 B**:`test_r1_integration`(连真栈,栈未起 skip):用 `ingest_index` 造一小件入库 → 查询返回带 `clause_id` 的命中 + 四级锚点回查正确;hybrid 失败 dense-only 兜底标记生效。

### Phase C —— 路由与理解骨架(可与 B 并行)
- `understand/classify.py`:N2 场景类型/涉及事项/entity_type(MVP 规则 + 词典前置匹配;LLM 可选)。
- `understand/router.py`:N4 八路(R1/R7/R8 实装;R2–R6 输出正确 `route_type` 但走诚实占位)。置信度低 → R7;多标签优先级(§4.3)。
- **检查点 C**:`test_router` golden 绿(R1/R7/R8 正确;R2–R6 正确打标且不裸答不报错)。

### Phase D —— R1 生成 + 引用注入 + 充分性(依赖 A+B)
- `retrieve/sufficiency.py`:N5 覆盖语境判据(§8.1,MVP 务实版:事项分区高召回后有无命中)。
- `generate/citation_inject.py`:§7.1 上下文每块注入 `clause_id`,prompt 强约束"只引用带 clause_id 的内容"。
- `generate/r1_evidence.py`:retrieve→sufficiency→(充分)citation_inject→LLM→anchors→contract。
- **检查点 D**:`test_citation_faithfulness`(引用 clause_id ⊆ 上下文)绿;`无裸结论`正则断言绿;R1 端到端(stub LLM)产出合法契约。

### Phase E —— 覆盖感知拒答(依赖 B 的 sufficiency + contract)
- `refuse/coverage_refusal.py`:§8.2 话术 + `exhausted_scope`(已穷尽事项分区)+ 最接近 N 条。
- **检查点 E**:`test_coverage_refusal` 绿(`route_type=refuse` + `exhausted_scope` 非空 + 话术含"未检索到…明确禁止性规定")。

### Phase F —— 编排装配 + CLI(依赖 C+D+E)
- `graph.py`:LangGraph 装配 router → {r1_evidence / clarify(R7)/ refuse(R8)/ R2–R6 占位};节点为纯函数,LangGraph 仅做边路由(便于无 LangGraph 时降级为 dict 派发)。
- `cli.py`:`query ask` / `query route`(thin shell over 域函数)。
- **检查点 F**:`query ask "<R1问句>"` 端到端产出契约;`query route` 打印判定;**全量 `pytest -q` 绿且默认零网络**;`ruff check .` 0 报。

---

## 2.5 可拓展性原则(已拍板,贯穿所有阶段)

> 决定二次开发是"增量插拔"还是"推倒重来"的根本——**设计保真的接口 + 占位的实现**,而非简化的接口。完整设计的每个增量(R2–R6 / HyDE / 案例桥接 / 多模型复核)目标形态 = **往既有图上挂节点 + 填 handler**,几乎不碰已有代码。

1. **编排建在 LangGraph 上(设计原生底座)**。完整设计是有状态/带环/可并行/流式的多节点图(R7→N0 环、混合检索∥案例桥接、N0 多轮、§9.2 生成后复核)。骨架若建在 dict 派发上,路由变多节点 DAG 时要重写编排层。**对冲锁定**:节点一律写成**纯函数**(不 import LangGraph,独立可测),`graph.py` 只装配边——真要换底座,纯函数照搬。
2. **`QueryState` 共享状态一次定全**。LangGraph 共享状态在骨架阶段就容纳完整设计要用的字段,**以后加节点永不改状态契约**:
   ```python
   @dataclass
   class QueryState:
       query: str                      # 原始问句
       history: list[dict]             # 多轮上下文(N0,占位)
       rewrites: list[str]             # HyDE/分解产物(N1/N3,占位)
       scene: dict | None              # N2 场景/事项/entity_type
       route_type: str | None          # N4 八路判定
       candidates: list[dict]          # 检索/重排候选(带 clause_id)
       exhausted_scope: list[str]      # §8 已穷尽事项分区
       citations: list[dict]           # 四级锚点(PG 回查)
       review: dict | None             # §9.2 多模型复核结果(占位)
       answer_blocks: list[dict]       # §10 契约 answer_blocks
   ```
3. **能力位先占满,实装可后补**(本切片必须做满,R2–R6=填 handler):
   - 路由器**现在就分满 8 类**(非只认 3 类);
   - 输出契约**现在就上 §10 全字段**;
   - `sufficiency` **接口按 §8.1 保真**(入参带涉及事项标签、出参带 `exhausted_scope`),实现先务实(biz_domain 分区高召回命中与否)——升级判据**不动调用方**;
   - 检索**现在就支持分区配额**(§5.2)与全过滤位(§5.3)。
4. **每个外部/可替换依赖都走接缝**(LLM / rerank / embedding):gateway、bge-reranker 后补时 drop-in,不改业务。

---

## 3. 并行 vs 串行

```
A(地基)──┬── B(检索/回查) ──┐
          └── C(路由/理解) ──┤
                              ├── D(R1生成,需A+B)──┐
                              │                      ├── F(编排+CLI)
                              └── E(拒答,需B+contract)┘
```
- **A 必须最先**(其余全依赖契约/配置/接缝)。
- **B 与 C 可并行**(检索脊柱 vs 路由骨架,互不依赖)。
- **D 依赖 A+B**;**E 依赖 B(sufficiency)+ contract**;D 与 E 可并行。
- **F 最后**(汇聚 C+D+E)。

---

## 4. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | **LangGraph 新依赖**(审批/学习成本/对骨架偏重)| **已拍板:采用 LangGraph**(设计原生底座,§2.5-1)。节点写成**纯函数**、独立可测、不 import LangGraph,`graph.py` 只装配边——锁定风险已对冲,真要换底座纯函数照搬 |
| R2 | **无重排模型**(bge-reranker 本地未必有)| `rerank=none` 默认用 RRF 融合序;reranker 为可选接缝;golden 按 RRF-only 基线标定;§5.5 top50→top8 待 reranker |
| R3 | **dev 无已入库语料** → R1 集成测试无数据 | 复用 `ingest_index`/`unique_docx` 造一小件入真栈;为 query golden 提供 ingest helper |
| R4 | **§8.1 充分性判据依赖 E2 事项分区**,E2 覆盖可能稀疏 | **已拍板:接口按 §8.1 保真**(出参 `exhausted_scope`、入参事项标签),实现先务实(biz_domain 分区高召回命中与否);升级判据**不动调用方**(§2.5-3)。devlog 标注简化差异;拒答话术仍诚实 |
| R5 | **stub LLM 让引用注入测试失真** | stub 设计为"从上下文确定性选前 N 个 clause_id",真实**走通注入契约**而非空跑 |
| R6 | **DAG 成环**(query 被 pipeline 误 import)| Phase A 检查点 import 探针 + ruff;CI 守 |
| R7 | **`confidence` 口径未定**(spec Q8)| 默认置检索融合分归一 ⚠,不参与任何闸门;待标定 |
| R8 | **契约/schema 漂移诱惑**(R1 想加字段)| 本切片纯只读消费,预期零契约改动;若确需改 → 回 spec(Ask first)|

---

## 5. 可追溯性(组件 → 红线 / 成功标准)

| 红线(SPEC §1/§8) | 承载组件 | 验证(SPEC §8 成功标准)|
|---|---|---|
| 无编造引用 | `citation_inject` + `anchors` + stub 选择式 | SC2 `test_citation_faithfulness` |
| 无裸结论 | `router`(判定型不入 R1)+ R1 prompt 约束 | SC4 无裸结论正则断言 |
| 可解释拒答 | `coverage_refusal` + `sufficiency` | SC3 `test_coverage_refusal` |
| 四级可回溯 | `anchors`(PG 回查)| SC1 契约 citations 四级齐全 |
| 默认零 LLM/网络 | `llm/stub` 默认后端 | SC6 默认 pytest 零网络 |
| DAG 无环 | 包结构 + 依赖方向 | SC7 import 探针 |

---

## 6. 验证清单(进入 Phase 3 TASKS 前)

- [ ] 组件与依赖图清晰、复用点明确 —— ✅ §1
- [ ] 实现顺序 + 每阶段检查点 —— ✅ §2
- [ ] 并行/串行边界 —— ✅ §3
- [ ] 风险与缓解 —— ✅ §4
- [ ] 红线 ↔ 组件 ↔ 验证可追溯 —— ✅ §5
- [x] 可拓展性原则(设计保真接口 + QueryState)—— ✅ §2.5
- [x] **人工复核批准** —— ✅ 已批准(LangGraph 采用、充分性接口保真),进入 Phase 3 TASKS
