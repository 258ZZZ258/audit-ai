# Plan: 制度查询智能体 HTTP API(B 轨 · 前端接缝)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-API.md`(已批准,§13 决策记录 8 项已定)。
> 延续本仓范式:**薄壳 over 域纯函数 / PG 权威 / Milvus 投影 / 单向只读 / 加法演进 / 默认零-LLM**。
> **零 graph 域改动**(structured 在 API 边界装配,不进节点)、**契约加法**(`QueryResult` 只加 `structured`/`meta`)、
> **PG add-only**(新增 `query_*` 会话表,迁移 0008)、**新依赖仅 `fastapi`+`uvicorn`**。

## 0. 架构决策(承 §13,PLAN 定型)

- **A1 HTTP=FastAPI**:`query/query/api/` 新子包(`app.py` 路由 + `service.py` 域装配 + `serializers.py` + `sse.py` + `errors.py` + `auth.py` stub)。原生 SSE/multipart/pydantic 校验;沿用 pipeline web 的「薄壳/PG 权威/只读」模式,仅换框架。
- **A2 契约加法**:`StructuredResult`/`TabPayload`/`*Hit`/`DigestCard` dataclass 落 `contract.py`(纯可序列化);`QueryResult +structured/+meta`(默认 `None`/`{}`,CLI 输出 byte 等价)。**装配逻辑落 `api/structured.py`(读 PG+检索),不进 graph 节点**。
- **A3 会话表落 `common.pg_models`**:`QueryConversation`/`QueryMessage` 加进 `libs/common/common/pg_models.py`(全仓单一 Base metadata + 根 Alembic 单迁移链;common 仍零上层依赖——声明式表不引入环)。迁移 **0008**(add-only)。表**只服务功能1**,`agent_type` 恒 `institution_query`;功能2 另建表(§13-6)。
- **A4 装配口径**:`match_score` = 候选集内检索融合分 min-max 归一 → `0–1` float(前端直显 %);⚠-data 字段(theme/related_internal/violation_theme/related_regulations)**缺失即省略**;⚠-model 字段(summary 走截断兜底 / core_issue / insight / citation_advice / digest / insights / 会话 title)LLM 开关**默认关**→ 缺省 `null`/`[]`/首问截断。案例要素复用 `case/case_card.py::CaseCard`(逐字 PG、零臆造)。
- **A5 流式顺序**:**同步-JSON 全 API 先落地(Phase A–E)** → **真流式生成(Phase F,SSE 前置)** → **SSE 端点(Phase G)**。同步 API 不依赖流式,先可用;`answer_delta` 由真流式喂,不做伪流式。
- **A6 鉴权**:`api/auth.py` stub 接缝(角色上下文 + 导出权限点),放行但把 401/403 语义 + 操作日志位定好;导出无权 → 403。真 Casbin/SSO 后续。
- **A7 附件**:`POST /uploads` 只存 + 发 `upload_id`;检索侧**不读附件内容**(§13-3)。

## 1. 组件与依赖

```
contract.py            +StructuredResult/TabPayload/RegulationHit/ClauseHit/RegulatoryRuleHit/CaseHit/DigestCard
   ▲  (纯 dataclass,零栈)   +QueryResult.structured: StructuredResult|None=None  +QueryResult.meta: dict={}
   │
api/structured.py      assemble_structured(result, cands, pg, retriever, qcfg) → StructuredResult
   ▲  (API 层装配)          ├─ 命中制度/条款 ← citations + cands 分 + PG 回查(doc_versions/chunks/clause_tags)
   │                        ├─ 监管规则 ← 外规候选 + clause_references(空→省略 related_internal)
   │                        ├─ 相关案例 ← attach_cases 结果 / CaseCard(逐字 PG;L2 缺→省略)
   │                        └─ match_score min-max 归一;⚠-model 默认 None
   │
common.pg_models       +QueryConversation +QueryMessage    ·   alembic/versions/0008_query_sessions.py (add-only)
   ▲
session/store.py       create/get/list(page,size,q)/delete/append_message   (over PgIO;分页+标题搜索)
   ▲
api/{errors,serializers,auth,service}.py + app.py(FastAPI)   统一错误体 + 状态码 + 序列化 + 鉴权 stub + 域装配
   ▲
api 端点(垂直切片,同步优先):
   conversations(CRUD/list/detail) · messages(ask 同步 JSON) · clauses/{id} · suggestions · uploads · export(xlsx)
   ▲
generate 真流式(llm.stream + generate_evidence_stream)   ← SSE 前置(Phase F,§7.2)
   ▲
api/sse.py + messages(Accept: text/event-stream)   accepted→route→structured→citations→answer_delta*→done / error / keep-alive
```

**复用零改**:`graph.py::QueryAgent.ask/route_only`、`generate/anchors.py`(`fetch_anchors`/`fetch_parent_text` → clauses 端点 + 结构化回查)、`case/case_card.py`+`case/r3_case.py::attach_cases`(相关案例)、`retrieve.hybrid`、`refuse.*`、`llm`(stub/gateway)、`PgIO`、`common.pg_models`(既有表)。**graph 域纯函数一字不改**。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — 契约扩展(纯函数,零栈;全单元)
- `contract.py` 加 `StructuredResult`/`TabPayload`/四 `*Hit`/`DigestCard`(`to_dict` 全覆盖);`QueryResult +structured(默认 None)+meta(默认 {})`,`to_dict` 加法输出。
- **检查点 A**:`test_api_contract` 绿——新类型序列化;**§10 byte 等价**(`structured=None`/`meta={}` 时既有 8 字段 `to_dict` 输出不变)、`RouteType`/既有字段不动。零栈零模型。

### Phase B — 结构化装配(API 层,真栈回查)
- `api/structured.py::assemble_structured`:citations + 检索候选分 + PG 回查装配四 Tab;`match_score` min-max 归一;⚠-data 缺失省略;⚠-model 默认 None;案例复用 `CaseCard`。
- **检查点 B**:`test_structured_assembly`(fake pg/retriever)+ `test_structured_assembly_integration`(真栈:四 Tab 字段追溯 PG、案例逐字、⚠ 字段缺省省略、归一 0–1)。gate=PG+Milvus+BGE-M3;未起 skip。

### Phase C — 会话持久化(PG 表 + 迁移 + store)
- `common.pg_models +QueryConversation/QueryMessage`;`alembic revision --autogenerate` → 0008(add-only)→ `upgrade` → `alembic check` 无漂移 + `ruff --fix/format alembic/versions`。
- `session/store.py`:create/get/list(page/size/`q` 标题 ILIKE 搜索/分页)/delete(级联 messages)/append_message(user+assistant + `result_json`/`hit_counts`)。
- **检查点 C**:`test_session_store`(CRUD + 分页 + 搜索 + 级联删,真 PG;未起 skip);`alembic check` 无漂移。

### Phase D — FastAPI 骨架 + 错误语义 + 序列化
- `pyproject.toml +fastapi/+uvicorn`;`api/app.py`(FastAPI + lifespan 建 `QueryAgent.from_config`/`PgIO`)、`api/errors.py`(统一错误体 + 状态码映射 §9)、`api/serializers.py`、`api/auth.py`(stub)、`api/service.py`(域装配)、`GET /healthz`。
- **检查点 D**:`test_api_errors`(TestClient:错误体单一形状;404/413/415/422/500 状态码;`healthz`)。零真栈(域 mock)。

### Phase E — 端点垂直切片(同步优先)
- **E1 会话端点**:`POST/GET(list 分页+`q`)/GET(detail:元信息+系统摘要+`hit_counts` 统计卡)/DELETE /conversations`。→ `test_api_conversations`。
- **E2 问答端点(同步 JSON)**:`POST /conversations/{cid}/messages`(`Accept: application/json`):校验 `query≤2000`(422)→ `QueryAgent.ask`(带会话 history)→ `assemble_structured` → 落 user+assistant 消息 → 返 `QueryResult(+structured+meta)`。→ `test_api_ask`。
- **E3 条款回查**:`GET /clauses/{clause_id}`(`fetch_anchors`+`text`+`fetch_parent_text`;404 不存在)。→ `test_api_clauses`。
- **E4 推荐+上传**:`GET /suggestions`(config 驱动 `[query.suggestions]`)、`POST /uploads`(multipart 白名单 415 / ≤50MB 413,只存发 `upload_id`)。→ `test_api_suggestions`/`test_api_uploads`。
- **E5 导出**:`POST /conversations/{cid}/messages/{mid}/export`(xlsx 模板填充 + AI 标识页脚;`auth` 导出点无权 403 + 操作日志位)。→ `test_api_export`。
- **检查点 E**:E1–E5 各 `test_api_*` 绿(TestClient + 域 mock;导出模板断言页脚/占位);会话+问答一条走通(同步)。

### Phase F — 真流式生成(SSE 前置,§7.2;模型门)
- `llm/client.py`(+`stub.py`)加 `stream(...)` API;`generate/r1_evidence.py` 加 `generate_evidence_stream(...)`(引用约束不变,逐 token 产出 answer;citations/structured 仍一次算)。
- **检查点 F**:`test_stream_generate`(stub 逐块产出确定性)+ `test_stream_generate_integration`(gateway+key 真流式,首 token 计时留痕;无 key skip)。**门控⏳待真 gateway 跑绿(诚实 🟡)**。

### Phase G — SSE 端点
- `api/sse.py` 事件编排;`messages` 端点 `Accept: text/event-stream` 分支 → `accepted→route→structured→citations→answer_delta*→done`(+`error`/15s `keep-alive`/硬超时);`answer_delta` 由 Phase F 喂;落库同 E2。
- **检查点 G**:`test_api_sse`(TestClient 读 SSE:事件序列 + evidence/refuse/clarify/judgmental 分支 + error)+ `test_api_sse_integration`(真栈端到端:structured 先到、逐字、done 耗时)。gate 同上。

### Phase H — 收尾 + 全仓门
- `query_devlog.md`(API 决策/踩坑)、`GAP.md`(§5.9 前端/§7.2 流式/§11 导出/§9 权限 翻档)、`RTM.md`(新增 API 组挂 test_id + 覆盖摘要重算)、`docs/devlog.md`(加阶段 B-API);全仓全量 + ruff 全绿、DAG 无环。
- **检查点 H**:全仓非模型门 + 本轮模型门集成绿;ruff 全绿;`fastapi`/`uvicorn` 装入 -e 链。

## 3. 并行 vs 串行

A(契约叶子)→ B(装配,依赖 A)∥ C(会话表,独立 A/B)→ D(骨架,依赖 A+错误)→ E(端点:E1 依赖 C+D;E2 依赖 B+C+D+E1;E3/E4 依赖 D;E5 依赖 C+D+E2)→ **F(真流式,独立于 A–E,可与 E 并行)** → G(SSE,依赖 E2+F)→ H(收尾+全仓门)。
**关键路径**:A→B→D→E2→(F)→G。**同步 API(A–E)不被 F 阻塞**——F 只挡 SSE(G)。会话表 C 可与契约 A/B 并行起步。

## 4. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 真流式模型门 + 首 token<3s 未验(§7.2)| **同步 API 先落地不依赖流式**(A5);F 门控集成、无 key skip、真跑前 RTM 记 🟡(诚实);SSE(G)排 F 后 |
| R2 | 契约加法破 §10 byte 等价 | T1 断言 `structured=None`/`meta={}` 时既有 8 字段 `to_dict` **逐字不变**;CLI `query ask` 回归 |
| R3 | 会话表迁移 × 并行 worktree 共享栈 | add-only 0008;**全仓门留合并时在对齐 code+schema 上跑**(CLAUDE.md worktree 约定);autogenerate 后 `alembic check` 无漂移 |
| R4 | 新依赖 fastapi/uvicorn(3.11)| 标准 wheel,无 grpcio/torch 类坑;装入 -e 链;TestClient 免起真服务 |
| R5 | match_score 归一窗口口径 | 默认**候选集内 min-max**;契约字段恒 `0–1` float,窗口取法可调不破契约 |
| R6 | ⚠-data/model 字段被误当"已实装" | §12 分档为准:缺失**省略**、LLM 默认关缺省 None;`test_structured_assembly` 断言缺省省略、零臆造 |
| R7 | SSE 代理断连 / 长检索 | 15s `keep-alive` 注释帧 + 硬超时(⚠ 可配 60s)→ `error` 事件;中途异常不静默(落失败态) |
| R8 | 鉴权 stub 被当真安全 | `auth.py` 明标 stub;导出点 403 语义先在、操作日志位先留;RTM 权限记 🟡/❌(诚实) |
| R9 | 测试基名撞名(prepend 模式)| 全用 `test_api_*`/`test_structured_*`/`test_session_*`/`test_stream_*` 前缀,已核未占用 |

## 5. 可追溯(SPEC-API / v1.5 → 组件)

| 设计能力 | 组件 | 红线 |
|---|---|---|
| §5.9 输出契约加法(structured/meta)| `contract.py` | byte 等价、前端无关化 |
| 四-Tab 结构化(§4)| `api/structured.py` | 追溯 PG、案例逐字、⚠ 缺省省略 |
| 四级锚点/条款回查(§7.3)| `generate/anchors.py`(复用)| PG 权威、非 Milvus 截断 |
| 会话持久化(原型历史)| `common.pg_models`+`session/store.py` | add-only、单向只读、query 自有域 |
| §7.2 流式(首 token<3s)| `generate` 真流式 + `api/sse.py` | 真流式喂、无伪流式 |
| §6.7 导出 Excel | `api/export_xlsx.py` | xlsx、AI 标识页脚、导出权限点 |
| §9 权限/AI 标识 | `api/auth.py`(stub)+ `ai_label` | 恒真、导出 403 语义、单向只读 |
| 无编造/无裸结论 | 复用 R1/R5 生成 + 拒答 | structured 拒答给最接近命中、不硬凑 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–H)· [x] 并行(同步 API 不被流式阻塞)· [x] 风险(含 byte 等价 / 迁移 / 流式门)· [x] 可追溯
- [ ] **人工复核批准**
