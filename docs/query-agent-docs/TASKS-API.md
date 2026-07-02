# Tasks: 制度查询智能体 HTTP API(B 轨)—— 任务分解

> 状态:**Phase 3 / TASKS —— 待人工复核批准**。依据 `SPEC-API.md` + `PLAN-API.md`(已批准,§13 决策 8 项已定)。
> 约定:每任务 ≤5 文件、TDD(先失败测试后实现)、含验收+验证。**测试基名全仓唯一**(全用 `test_api_*`/`test_structured_*`/`test_session_*`/`test_stream_*` 前缀,已核未占用)。
> **契约加法(structured/meta)、PG add-only(0008)、graph 域零改、默认零-LLM、单向只读。** 真栈 gate=**PG+Milvus+本地 BGE-M3**;流式/LLM gate=**gateway+key**(无则 skip)。
> **同步 API(T1–T9)不依赖流式;真流式(T10)是 SSE(T11)前置。**

- [ ] **T1:契约扩展(structured/meta 加法,纯 dataclass)** — Phase A
  - Acceptance:`contract.py` 加 `TabPayload`/`StructuredResult`/`RegulationHit`/`ClauseHit`/`RegulatoryRuleHit`/`CaseHit`/`DigestCard`(字段严格对齐 SPEC §4,`to_dict` 全覆盖、日期 ISO、缺省省略);`QueryResult +structured: StructuredResult|None=None` +`meta: dict=field(default_factory=dict)`,`to_dict` 加法输出。
  - Verify:`pytest query/tests/test_api_contract.py`——新类型序列化;**§10 byte 等价**(`structured=None`+`meta={}` 时既有 8 字段 `to_dict()` 与基线逐字相等);枚举/既有字段不动。零栈零模型。
  - Files:`query/query/contract.py`、`query/tests/test_api_contract.py`。 Dependencies:None。 Scope:S。

- [ ] **T2:结构化四-Tab 装配(API 层 + 集成)** — Phase B
  - Acceptance:`api/structured.py::assemble_structured(result, cands, pg, retriever, qcfg) → StructuredResult`:命中制度/条款(citations + 候选分 + PG 回查 doc_versions/chunks/clause_tags)、监管规则(外规候选;`related_internal` 依赖 clause_references,空→省略)、相关案例(复用 `case_card.CaseCard` 逐字 PG;L2 缺→省略)、`citation_advice`/`digest`/`insights`(⚠-model 默认 None/[]);`match_score` 候选集内 **min-max 归一 0–1**。
  - Verify:`pytest query/tests/test_structured_assembly.py`(fake pg/retriever:四 Tab 计数/字段、归一 0–1、⚠-data 缺失省略、⚠-model 默认空、案例逐字);`pytest query/tests/test_structured_assembly_integration.py`(真栈:字段追溯 PG)。gate=PG+Milvus+BGE-M3;未起 skip。
  - Files:`query/query/api/__init__.py`、`query/query/api/structured.py`、`query/tests/test_structured_assembly.py`、`query/tests/test_structured_assembly_integration.py`。 Dependencies:T1。 Scope:M。

- [ ] **T3:会话持久化(PG 表 + 迁移 0008 + store)** — Phase C
  - Acceptance:`common.pg_models +QueryConversation`(id/title/agent_type 恒 institution_query/asker_role/created_at/updated_at/message_count/last_hit_counts)`+QueryMessage`(id/conversation_id FK/seq/role/content/route_type/result_json/hit_counts/elapsed_ms/ai_label/created_at);autogenerate → `0008_query_sessions`(**add-only**);`session/store.py`:create/get/list(page/page_size/`q` 标题 ILIKE)/delete(级联 messages)/append_message。
  - Verify:`pytest query/tests/test_session_store.py`(真 PG:CRUD + 分页 + 标题搜索 + 级联删;未起 skip);`alembic upgrade head` + `alembic check` **无漂移**;`ruff check --fix alembic/versions && ruff format alembic/versions`。
  - Files:`libs/common/common/pg_models.py`、`alembic/versions/0008_query_sessions.py`、`query/query/session/__init__.py`、`query/query/session/store.py`、`query/tests/test_session_store.py`。 Dependencies:None(表独立)。 Scope:M。

- [ ] **T4:FastAPI 骨架 + 错误语义 + 序列化 + 鉴权 stub** — Phase D
  - Acceptance:`query/pyproject.toml +fastapi/+uvicorn`;`api/app.py`(FastAPI + lifespan 装 `QueryAgent.from_config`/`PgIO`/`store`)、`api/errors.py`(统一错误体 `{"error":{"code","message","details?}}` + 状态码 400/401/403/404/413/415/422/429/500)、`api/serializers.py`、`api/auth.py`(stub:角色上下文 + 导出权限点、放行)、`api/service.py`(域装配)、`GET /healthz`。
  - Verify:`pytest query/tests/test_api_errors.py`(FastAPI TestClient:错误体单一形状;404/413/415/422/500 映射;`healthz` 200)。零真栈(域 mock)。
  - Files:`query/pyproject.toml`、`query/query/api/app.py`、`query/query/api/errors.py`、`query/query/api/auth.py`、`query/tests/test_api_errors.py`(serializers/service 随 app.py 或并入 ≤5)。 Dependencies:T1。 Scope:M。

### 检查点:T1–T4(地基)
- [ ] `test_api_contract`/`test_structured_assembly`/`test_session_store`/`test_api_errors` 绿;`alembic check` 无漂移;`fastapi`/`uvicorn` 装入 -e 链;§10 byte 等价 + CLI `query ask` 回归绿。

- [ ] **T5:会话端点(CRUD/list/detail)** — Phase E1
  - Acceptance:`POST /conversations`(新会话)、`GET /conversations?page=&page_size=&q=`(分页 + 标题搜索,`{data,pagination}`)、`GET /conversations/{cid}`(元信息 + 系统摘要 + `hit_counts` 四统计卡 + messages)、`DELETE /conversations/{cid}`(级联)。`page_size≤100`(422 越界)。
  - Verify:`pytest query/tests/test_api_conversations.py`(TestClient + store mock/真 PG:分页形状、`q` 搜索、详情统计卡、404、page_size 越界 422)。
  - Files:`query/query/api/routes_conversations.py`、`query/query/api/service.py`、`query/tests/test_api_conversations.py`。 Dependencies:T3、T4。 Scope:S。

- [ ] **T6:问答端点(同步 JSON)** — Phase E2
  - Acceptance:`POST /conversations/{cid}/messages`(`Accept: application/json`):校验 `query≤2000`(422)+ `attachments` 引用存在(422)+ `corpus∈{internal,external,null}`→ 取会话 history → `QueryAgent.ask(query, history)` → `assemble_structured` → 落 user+assistant 消息(`result_json`/`hit_counts`/`elapsed_ms`)→ 返 `QueryResult(+structured+meta)`;中途 stage 异常**不静默**(落失败态 + 非 2xx)。
  - Verify:`pytest query/tests/test_api_ask.py`(TestClient + agent/store mock:evidence 返 structured 四 Tab + citations;`query>2000`→422;拒答路由 structured 省略/最接近命中;消息落库序;异常非静默)。
  - Files:`query/query/api/routes_messages.py`、`query/query/api/service.py`、`query/tests/test_api_ask.py`。 Dependencies:T2、T3、T4、T5。 Scope:M。

- [ ] **T7:条款回查端点(联动/查看原文)** — Phase E3
  - Acceptance:`GET /clauses/{clause_id}` → `fetch_anchors`(四级锚点)+ `chunks.text`(全文)+ `fetch_parent_text`(节级父块,无则 null);不存在 → 404。**权威 PG,非 Milvus 截断**。
  - Verify:`pytest query/tests/test_api_clauses.py`(TestClient + pg mock:字段齐全、parent 缺 null、404)。
  - Files:`query/query/api/routes_clauses.py`、`query/tests/test_api_clauses.py`。 Dependencies:T4。 Scope:S。

- [ ] **T8:推荐问题 + 文件上传端点** — Phase E4
  - Acceptance:`GET /suggestions?agent_type=`(config `[query.suggestions]` 驱动,不硬编码);`POST /uploads`(multipart:content-type 白名单 PDF/Word/Excel 否则 **415**;`Content-Length>50MB` 预拒 **413** 不入内存;存文件发 `{upload_id,filename,size,content_type}`,**只存不消费**)。
  - Verify:`pytest query/tests/test_api_suggestions.py`(config 驱动、agent_type 分集);`pytest query/tests/test_api_uploads.py`(白名单 415、超限 413、正常 201 发 upload_id)。
  - Files:`config/settings.toml`、`query/query/api/routes_misc.py`、`query/tests/test_api_suggestions.py`、`query/tests/test_api_uploads.py`。 Dependencies:T4。 Scope:S。

- [ ] **T9:导出端点(xlsx + AI 页脚 + 导出权限点)** — Phase E5
  - Acceptance:`POST /conversations/{cid}/messages/{mid}/export {format:"xlsx"}` → 从 `result_json` 填模板(问题/答复摘要/依据条款四级/相似案例/路由/导出人/时间)+ **固定 AI 标识页脚**;过 `auth` 导出权限点(stub 放行,无权 → **403** + 操作日志位);返文件流(Content-Disposition)。
  - Verify:`pytest query/tests/test_api_export.py`(TestClient + store mock:xlsx 字节头 + 页脚/占位断言;无权 403;消息不存在 404)。
  - Files:`query/query/api/routes_export.py`、`query/query/api/export_xlsx.py`、`query/tests/test_api_export.py`。 Dependencies:T3、T4、T6。 Scope:M。

### 检查点:T5–T9(同步 API 全通)
- [ ] `test_api_conversations`/`test_api_ask`/`test_api_clauses`/`test_api_suggestions`/`test_api_uploads`/`test_api_export` 绿;新建会话→提问→拿四 Tab→查看原文→导出 xlsx 一条**同步链路**走通;§9 错误语义一致。

- [ ] **T10:真流式生成(SSE 前置,§7.2)** — Phase F
  - Acceptance:`llm/client.py`(+`stub.py`)加 `stream(...)` API(gateway 真 token 流 / stub 确定性逐块);`generate/r1_evidence.py` 加 `generate_evidence_stream(query, cands, pg, llm, ...)`:**引用约束不变**(只选不生成、四级锚点一次算),answer 正文逐 token 产出。
  - Verify:`pytest query/tests/test_stream_generate.py`(stub:逐块产出确定性、引用约束不破);`pytest query/tests/test_stream_generate_integration.py`(gateway+key:真流式 + 首 token 计时留痕;无 key skip)。**门控⏳待真 gateway 跑绿(RTM 记 🟡)**。
  - Files:`query/query/llm/client.py`、`query/query/llm/stub.py`、`query/query/generate/r1_evidence.py`、`query/tests/test_stream_generate.py`、`query/tests/test_stream_generate_integration.py`。 Dependencies:None(独立于 API,可与 E 并行)。 Scope:M。

- [ ] **T11:SSE 端点** — Phase G
  - Acceptance:`api/sse.py` 事件编排;`messages` 端点 `Accept: text/event-stream` 分支 → `accepted→route→structured→citations→answer_delta*→done`(+ `error` / 15s `keep-alive` 注释帧 / 硬超时 ⚠可配);`answer_delta` 由 T10 真流式喂;落库同 T6;拒答/澄清/判定型分支正确。
  - Verify:`pytest query/tests/test_api_sse.py`(TestClient 读 SSE:事件序列 + evidence/refuse/clarify/judgmental 分支 + error + keep-alive);`pytest query/tests/test_api_sse_integration.py`(真栈端到端:structured 先到、逐字、done 耗时/计数)。gate=PG+Milvus+BGE-M3(+ 流式 gateway 无 key 降级 stub)。
  - Files:`query/query/api/sse.py`、`query/query/api/routes_messages.py`、`query/tests/test_api_sse.py`、`query/tests/test_api_sse_integration.py`。 Dependencies:T6、T10。 Scope:M。

- [ ] **T12:收尾(devlog/GAP/RTM/时间轴)+ 全仓门** — Phase H
  - Acceptance:`query_devlog.md` 记 API 决策(FastAPI、契约加法、会话表落 common、match_score 归一、附件只存不消费、鉴权 stub、真流式先于 SSE)与踩坑;`GAP.md`(§5.9 前端接缝 / §7.2 流式 / §11 导出 / §9 权限 翻档 ✅/🟡);**`RTM.md`** 新增 API 需求组挂 test_id(§5.9-struct/会话/§7.2 流式/§11 导出/§9-AI标识 → ✅/🟡,权限/真流式记 🟡)、覆盖摘要重算;`docs/devlog.md` 加阶段 B-API;全仓全量 + ruff 全绿、DAG 无环。
  - Verify:`.venv/bin/python -m pytest -q`(干净栈;本轮集成需 PG+Milvus+BGE-M3,**提交前模型门控全量**);`.venv/bin/ruff check .`。
  - Files:`docs/query-agent-docs/query_devlog.md`、`docs/query-agent-docs/GAP.md`、`docs/query-agent-docs/RTM.md`、`docs/devlog.md`。 Dependencies:T1–T11。 Scope:S。

## 依赖与并行
T1 → {T2 依赖 T1;T3 独立;T4 依赖 T1} → T5(T3+T4)→ T6(T2+T3+T4+T5)→ {T7 依赖 T4;T8 依赖 T4;T9 依赖 T3+T4+T6} → **T10 独立(可与 T2–T9 并行)** → T11(T6+T10)→ T12(全仓门)。
**关键路径**:T1→T2→T4→T6→(T10)→T11→T12。**同步 API(T1–T9)不被 T10 阻塞**;会话表 T3 与契约 T1/T2 并行起步;T10 真流式独立并行,只挡 T11。

## 覆盖 SPEC-API §14 验收
- V1 契约加法 byte 等价 → T1;V2 四-Tab 追溯来源分档 + ⚠ 缺省省略 → T2;V3 会话 add-only/query_ 前缀/不碰 corpus + 迁移随 demo up → T3;V4 SSE 四路由 + error/keep-alive + 真流式喂 → T10/T11;V5 分页/命名/日期/版本一致 → T5/T8;V6 错误体单一 + 状态码 → T4(+各端点);V7 红线可测(无编造/无裸结论/ai_label 恒真/判定型 review_required/单向只读)→ T2/T6/T9/T11;V8 全仓门 + RTM 覆盖 → T12。

## 验证清单(进 Phase 4 前)
- [x] 任务离散 ≤5 文件 · [x] 各带验收+验证 · [x] 按依赖排序(同步 API 不被流式阻塞)· [x] 覆盖 §14 验收(V1–V8)· [x] T12 同步更新 RTM · [x] 测试基名全仓唯一
- [ ] **人工复核批准**
