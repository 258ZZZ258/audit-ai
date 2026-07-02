# Spec: 制度查询智能体 HTTP API 设计规格(B 轨 · 前端接缝)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**(批准后才进 Phase 2 PLAN / TASKS,再进实现)。
> 上游设计:`docs/制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`(§5.9 输出契约 / §6.7 导出 / §9 横切)。
> 产品原型:`/Users/apple/东方/制度查询/制度查询智能体页面`(审计 AI 原型 V3,6 张页面图)。
> 既有实现:`query/query/`(R1–R6 八路已落地,`QueryAgent.ask` 端到端;详见 `query_devlog.md` / `GAP.md`)。
> **本文只设计 API 契约与接缝,不落代码**;命名/错误/校验按生产 v1.5 保真,不以 demo 放水。
> **决策已定**(见 §13 决策记录):HTTP=**FastAPI**;匹配度=**归一%直显**;附件=**只存不消费**;鉴权=**stub 接缝+导出点 403**;会话标题=**LLM 概括(开关默认关→回落首问截断)**;功能2=**独立会话表**;导出=**xlsx 默认**;流式=**先落 gateway 真流式,再上 SSE**。

---

## 0. 切片边界(本轮做什么 / 不做什么)

| | 范围 |
|---|---|
| **做** | ① 对话问答核心的 HTTP 封装(八路路由 + 答复正文 + 四级引用),**REST + SSE 流式**;② **结构化四-Tab 结果契约**(命中制度 / 命中条款 / 监管规则 / 相关案例 + 匹配度 / 适用主题 / 摘要 / 引用建议 / 要求提炼 / 案例启示);③ **会话与历史持久化**(新增 PG `query_*` 表,列表 / 分页 / 搜索 / 详情 / 统计卡 / 复制摘要);④ 导出查询报告(§6.7)、推荐问题、随问文件上传;⑤ §10 契约**加法演进**、错误语义、边界校验、命名 / 版本约定 |
| **不做(本轮)** | 前端页面实现(genesis-ui 侧);制度**比对**智能体(功能2,原型侧栏可见但页面不在本包);Casbin/SSO 真实鉴权(**留接缝 + stub**,设计标明权限点);富集字段的**模型侧实装**(本轮只定契约与来源分档 §12,LLM 提炼默认关);限流 / P95 压测(§12 容量)只在契约留位;WebSocket(SSE 已够,双工非必需) |

**为何这样切**:v1.5 §5.9 的输出契约是**前端无关化**的 `answer_blocks[]+citations[]+route_type`,已在 `contract.py` 落地;原型 V3 的四-Tab 是**更富的渲染层**,当前契约不承载。本轮把「差集」补成稳定 API 契约,**加法保真、零破坏**,让前端可对着契约独立开发。

---

## 1. Objective

**构建什么**:`query` 包新增一层 **HTTP API(thin shell over `QueryAgent`)**,把原型 V3 的四个交互面——对话问答(流式)、结构化结果四-Tab、会话历史、导出/推荐/上传——落成**契约优先、向后兼容**的 REST + SSE 接口。域逻辑仍在 `query.graph` / `query.*` 纯函数,API 层只做**参数校验 → 调域函数 → 回查富集 → 契约序列化 → SSE 编排**,沿用 `pipeline/pipeline/web` 的**薄壳 over 域函数 / PG 权威 / 单向只读**模式(框架换 FastAPI,§13-1)。

**成功长相**:
- 前端只消费本 spec 定义的 JSON/SSE 契约即可渲染原型全部页面,**无需知道后端如何检索**。
- 一次 R1 依据型提问:SSE 先推 `structured`(四-Tab 表格,~2s)→ 逐字推 `answer_delta` → `done`(耗时 / 计数)。四-Tab 每条命中都可四级回溯(条款→文档→页码→版本),案例要素**逐字来自 PG**(§6.3 红线)。
- 无依据提问:`route_type=refuse` + `exhausted_scope` 非空,**绝不编造字号/条号、绝不出「违规/合规」裸结论**;结构化结果给「最接近命中」而非硬凑四-Tab。
- 历史会话:68 条可分页 / 按标题搜索 / 看详情 + 统计卡 + 复制摘要,均从 `query_*` 权威表读。

---

## 2. 设计原则(接口硬约束)

1. **契约优先**:先定 dataclass + JSON 形状,实现随之。契约 = 文档,`to_dict()` 产出稳定形状。
2. **加法演进,绝不破坏**(Hyrum's Law + 项目 add-only 基因):§10 `QueryResult` 只**加**可选字段(`structured` 等),既有 `route_type/answer_blocks/citations/confidence/ai_label/review_required/exhausted_scope/export_enabled` 一字不改;PG 新表 add-only(不碰 corpus 权威表)。CLI `query ask` 输出 byte 等价(structured 默认 `null`)。
3. **命名一致 > 通用惯例**:JSON 字段沿用既有 `contract.py` 的 **snake_case**(`route_type`/`clause_id`/`doc_no`…),**不改 camelCase**——与已被消费的 §10 契约一致优先于泛化风格。REST 路径用复数名词、无动词。
4. **单一错误语义**:所有端点同一错误体 `{"error":{"code","message","details?}}` + 一致状态码(§9);SSE 内错误走 `event: error`。不混用「有的抛异常、有的返回 null」。
5. **边界校验**:仅在 API 入口校验外部输入(query≤2000 字、分页界、上传白名单+尺寸、附件引用存在);内部纯函数信任类型,不重复校验。
6. **版本化**:路径前缀 `/api/query/v1`;破坏性变更走 `/v2`,不在 v1 内改字段语义。
7. **红线继承**(v1.5 §9 + 项目 CLAUDE.md):单向只读(**绝不回写任何源系统 / 制度权威表**);`ai_label` 强制;导出含 AI 标识页脚;判定型 `review_required=true` 前端渲染人工复核框;零编造引用 / 零裸结论。

---

## 3. API 总览(资源与端点)

Base path:`/api/query/v1`。资源:`conversations`(会话)、其下 `messages`(问答轮)、`clauses`(条款回查)、`exports`(导出)、`suggestions`(推荐问题)、`uploads`(附件)。

| 方法 | 路径 | 用途 | 原型对应 |
|---|---|---|---|
| `POST` | `/conversations` | 新建会话(新会话) | 「新会话」按钮 |
| `GET` | `/conversations?page=&page_size=&q=` | 历史会话列表(分页 + 标题搜索) | 历史会话弹窗左栏 |
| `GET` | `/conversations/{cid}` | 会话详情(元信息 + 系统摘要 + 统计卡 + 消息) | 历史会话详情 |
| `DELETE` | `/conversations/{cid}` | 删除会话(清空会话) | 「清空会话」/删除 |
| `POST` | `/conversations/{cid}/messages` | **提问**(SSE 流式或同步 JSON) | 「发送」 |
| `GET` | `/conversations/{cid}/messages/{mid}` | 取单轮完整结果(历史回看) | 「查看详情」 |
| `POST` | `/conversations/{cid}/messages/{mid}/export` | 导出查询报告(§6.7) | 「导出查询报告内容」 |
| `GET` | `/clauses/{clause_id}` | 条款回查:原文 / 详细释义 / 完整定义 | 「查看原文」「详细释义 >>」「完整定义 >>」 |
| `GET` | `/suggestions?agent_type=` | 首页推荐问题(配置驱动) | 「推荐问题」四条 |
| `POST` | `/uploads` | 随问附件上传(PDF/Word/Excel ≤50MB) | 「可上传文件」 |

**约定**:`{cid}`/`{mid}` = ULID;列表端点一律分页(§7);写端点幂等性见各节。

---

## 4. 结构化四-Tab 结果契约(核心新增)

原型右栏「制度查询结果」四 Tab。定义 `StructuredResult`(新 dataclass,`query/query/contract.py` 加法),字段**逐列对齐原型**。每 Tab 用 `TabPayload{total, items}`(`total` 驱动「命中制度(3)」计数)。

```python
@dataclass
class TabPayload:                 # 泛型语义:items 元素类型见各 Tab
    total: int                    # Tab 计数(命中制度(3) 的 3)
    items: list[dict]

@dataclass
class StructuredResult:
    regulations: TabPayload       # 命中制度 (items: RegulationHit)
    clauses: TabPayload           # 命中条款 (items: ClauseHit)
    regulatory_rules: TabPayload  # 监管规则 (items: RegulatoryRuleHit)
    cases: TabPayload             # 相关案例 (items: CaseHit)
    citation_advice: list[str]    # 条款引用建议(命中条款 Tab 下)
    regulatory_digest: list[dict] # 监管要求提炼卡片(监管规则 Tab 下,DigestCard)
    case_insights: list[dict]     # 案例启示摘要卡片(相关案例 Tab 下,DigestCard)
```

### 4.1 `RegulationHit`(命中制度)

| JSON 字段 | 类型 | 原型列 | 来源(§12 分档) |
|---|---|---|---|
| `seq` | int | 序号 | API 层排序赋号 |
| `doc_id` / `doc_version_id` | str | (联动键) | `doc_versions` |
| `title` | str | 制度名称 | `doc_versions.title` ✅ |
| `match_score` | float 0–1 | 匹配度(%) | 检索融合分 min-max 归一 → 前端直显 0–100%(决策已定;归一窗口口径见 §12) |
| `doc_no` | str? | 制度编号 | `doc_versions.doc_number` ✅ |
| `publish_date` | date? | 发布日期 | `doc_versions.issue_date` ✅ |
| `effective_date` | date? | 生效日期 | `doc_versions.effective_date` ✅ |
| `issuing_dept` | str? | 发布部门 | `doc_versions.issuer` ✅ |
| `clause_excerpt` | str | 条款内容(节选) | `chunks.text` 截断 ✅ |
| `version` / `status` | str? | (版本/状态角标) | `doc_versions.issue_date` / `version_status` ✅ |

### 4.2 `ClauseHit`(命中条款)

| JSON 字段 | 类型 | 原型列 | 来源 |
|---|---|---|---|
| `seq` | int | 序号 | API 排序 |
| `clause_id` | str | (查看原文键) | = `chunk_id` ✅ |
| `clause_title` | str | 条款名称 | `chunks.clause_path` 末级 / `breadcrumb` ✅ |
| `clause_path` | str? | (面包屑) | `chunks.clause_path` ✅ |
| `doc_title` / `doc_id` | str | 所属制度 | `doc_versions.title` ✅ |
| `match_score` | float | 匹配度 | 融合分 min-max 归一 → 直显 0–100% |
| `summary` | str | 条款摘要 | `chunks.text` 截断(默认)/ LLM 提炼(开关)⚠ |
| `theme` | str? | 适用主题 | `clause_tags`(deontic/tag_value)/ E2 `entity_type` ⚠(未打标则空) |

### 4.3 `RegulatoryRuleHit`(监管规则,外规)

| JSON 字段 | 类型 | 原型列 | 来源 |
|---|---|---|---|
| `seq` | int | 序号 | API 排序 |
| `clause_id` / `doc_id` | str | (查看键) | 外规 `chunks`/`doc_versions` ✅ |
| `title` | str | 规则名称 | `doc_versions.title` ✅ |
| `issuing_body` | str? | 发布机构 | `doc_versions.issuer` ✅ |
| `doc_no` | str? | 文号 | `doc_versions.doc_number` ✅ |
| `publish_date` | date? | 日期 | `doc_versions.issue_date` ✅ |
| `core_requirement` | str | 核心监管要求 | `chunks.text` / E1 义务抽取 ✅/⚠ |
| `related_internal` | list[str] | 关联内部制度 | `clause_references` 指代表反查 ⚠(Q5 空表 TODO) |
| `theme` | str? | 适用主题 | `clause_tags` ⚠ |

### 4.4 `CaseHit`(相关案例)

| JSON 字段 | 类型 | 原型列 | 来源 |
|---|---|---|---|
| `seq` | int | 序号 | API 排序 |
| `case_id` / `doc_version_id` | str | (键) | `cases` ✅ |
| `title` | str | 案例名称 | `doc_versions.title` ✅ |
| `regulator` | str? | 监管机构 | `cases.penalty_org` ✅ |
| `penalty_date` | date? | 处罚日期 | `cases.penalty_date` ✅ |
| `violation_theme` | str? | 违规主题 | `cases.violation_category`(L2)⚠(默认空则省略) |
| `related_regulations` | list[str] | 关联制度 | `cases.cited_regulations`(L2)⚠ |
| `core_issue` | str? | 核心问题 | LLM 提炼(开关)/ 占位 ⚠(cases 无此列) |
| `insight` | str? | 启示要点 | LLM 提炼(开关)/ 占位 ⚠ |

> **红线**:案例要素**逐字来自 PG `cases`/`doc_versions`**,复用 `case/case_card.py::CaseCard`;L2/LLM 字段缺失时**省略、零臆造**(与既有 `CaseCard.to_content` 一致)。`core_issue`/`insight` 若未开 LLM 提炼 → 缺省 `null`,前端隐藏该列,**不硬凑**。

### 4.5 `DigestCard`(监管要求提炼 / 案例启示摘要卡片)

```
{ "tag": "盾", "title": "客户适当性评估", "body": "应充分了解客户……" }
```

`tag` = 卡片角标短字(原型「盾/查/迹」「评/留/更」);默认由 LLM 提炼(开关关时列表为空 `[]`,前端隐藏卡片区)。

---

## 5. §10 契约的加法演进

`QueryResult`(`contract.py`)**新增两个可选字段**,其余不动:

```python
@dataclass
class QueryResult:
    # …既有 8 字段不变…
    structured: StructuredResult | None = None   # 新增:四-Tab(API 层回查富集后填;CLI 默认 None)
    meta: dict = field(default_factory=dict)      # 新增:{elapsed_ms, total_hits, hit_counts}
```

- `structured` 由 **API 边界层**填充(从 `citations` + `attach_cases` 结果 + 检索候选分 + PG 回查装配),**不进域纯函数**——保持 `graph.py` 节点纯净、CLI 输出等价。
- `hit_counts = {regulations, clauses, regulatory_rules, cases}`,供会话统计卡与列表冗余。
- 拒答/澄清:`structured=null` 或仅含「最接近命中」,`export_enabled` 随 `route_type` 决定(拒答默认可导出但标注无依据)。

---

## 6. 对话问答 SSE 协议(`POST /conversations/{cid}/messages`)

### 6.1 请求

```
POST /api/query/v1/conversations/{cid}/messages
Accept: text/event-stream            # 缺省则回同步 JSON(见 6.4)
Content-Type: application/json
{
  "query": "客户风险等级更新不及时的相关案例有哪些?",   // ≤2000 字,超则 422
  "attachments": ["<upload_id>"],                       // 可选,引用 /uploads 产物
  "include_superseded": false,                          // 可选,放开历史版本过滤
  "corpus": "internal|external|null"                    // 可选,限定语料
}
```

多轮:服务端按 `cid` 取该会话历史消息,组 `history` 传 `QueryAgent.ask(query, history=…)`(N0 归并已实装),**前端不必自带 history**。

### 6.2 SSE 事件序列(有序、每事件一 `data` JSON)

| event | data | 时机 |
|---|---|---|
| `accepted` | `{conversation_id, message_id}` | 立即(写入 user 消息后) |
| `route` | `{route_type, review_required}` | 路由判定后 |
| `structured` | `StructuredResult`(§4) | 检索 + 回查 + 富集完成(**一次**,原型表格) |
| `citations` | `{citations:[Citation…]}` | 四级锚点就绪(可与 structured 合并) |
| `answer_delta` | `{text:"…"}` | 答复正文分块,**重复多次**(§7.2 首 token<3s 目标) |
| `done` | `{message_id, elapsed_ms, total_hits, hit_counts, ai_label, review_required, exhausted_scope, export_enabled}` | 收尾,前端渲染「检索完成 耗时 Xs 共 N 条」 |
| `error` | `{error:{code,message}}` | 任一阶段失败(传输级) |

- **流式落地顺序(决策已定)**:先在生成侧落 **gateway 真 token 流式**(§7.2,GAP P3;OpenAI 兼容网关真流式 → `generate` 逐 token 产出),**再**上 SSE 端点——`answer_delta` 由真流式喂,**不做伪流式过渡**。故 SSE 端点的 PLAN 任务**依赖**「真流式生成」前置任务先绿。`contract.py` 已有 `stream` 字段占位,本轮赋真语义。
- 拒答/澄清路由:`route` → `answer_delta`(拒答话术 / 澄清问句)→ `done`(带 `exhausted_scope`),`structured` 省略或仅「最接近命中」。

### 6.3 SSE 心跳与超时

长检索期间每 15s 发 `: keep-alive` 注释帧防代理断连;服务端硬超时(⚠ 可配,默认 60s)→ `event: error{code:"UPSTREAM_TIMEOUT"}`。

### 6.4 同步降级(非 SSE)

`Accept: application/json` 时,一次性返回 `QueryResult.to_dict()`(含 `structured`/`meta`),便于导出、自动化测试、无 SSE 客户端。**同契约、同字段**,仅传输方式不同(One-Version:不分裂两套数据形状)。

---

## 7. 会话与历史持久化

### 7.1 新增 PG 表(add-only,`query_` 前缀,Alembic 迁移;**不碰 corpus 权威表**)

```
query_conversations
  id            ULID  PK
  title         str?           # 会话标题:LLM 概括(开关,默认关 → 回落首问截断)(原型「融资融券客户适当性制度依据」)
  agent_type    str            # 恒 institution_query(制度查询);功能2 制度比对**另建独立会话表**,不复用本表(决策已定)
  asker_role    str?           # 提问角色(审计人员…),来自鉴权上下文
  created_at / updated_at  ts
  message_count int
  last_hit_counts jsonb?       # {regulations,clauses,regulatory_rules,cases} 冗余(列表/统计卡快速展示)

query_messages
  id            ULID  PK
  conversation_id  FK -> query_conversations.id  (index)
  seq           int            # 轮内序
  role          str            # user | assistant
  content       text           # user=问句;assistant=答复摘要(系统摘要)
  route_type    str?           # assistant 带
  result_json   jsonb?         # 完整 §10+structured 契约快照(历史回看/复制摘要/导出的权威源)
  hit_counts    jsonb?         # 该轮四类计数(统计卡)
  elapsed_ms    int?
  ai_label      bool
  created_at    ts
```

> `result_json` 是**查询产物快照**,非制度权威数据;query 域自有,单向只读红线不受影响。会话表随 `demo up` 的 alembic 一并建。

### 7.2 端点契约

**列表**(分页 + 搜索,§skill 分页统一形状):
```
GET /conversations?page=1&page_size=20&q=<标题关键词>
200 {
  "data": [ {"id","title","agent_type","asker_role","created_at","message_count","last_hit_counts"} … ],
  "pagination": {"page":1,"page_size":20,"total_items":68,"total_pages":4}
}
```

**详情**(原型右侧详情面板):
```
GET /conversations/{cid}
200 {
  "id","title","agent_type","asker_role","created_at",
  "user_question": "…",          // 首/最近用户问题
  "summary": "…",                // 系统摘要(assistant 答复摘要)
  "hit_counts": {"regulations":3,"clauses":8,"regulatory_rules":2,"cases":4},  // 四张统计卡
  "messages": [ {"id","seq","role","content","route_type","created_at"} … ]
}
```

**复制摘要** = 前端取 `summary` 到剪贴板(无独立端点)。**查看详情** = `GET messages/{mid}` 拿 `result_json` 全量。

### 7.3 新会话 / 清空会话

- `POST /conversations {agent_type?}` → 建空会话返回 `id`。
- `DELETE /conversations/{cid}` → 删会话(级联删 `query_messages`)。原型「清空会话」= 删当前会话消息或建新会话(前端二选一,契约都支持)。

---

## 8. 导出 / 推荐问题 / 条款回查 / 文件上传

### 8.1 导出(§6.7)

```
POST /conversations/{cid}/messages/{mid}/export   { "format": "xlsx" }   // 默认且本轮唯一:xlsx
→ 200  文件流(Content-Disposition: attachment),模板复用报告/导出服务(§13.5)。
```
**默认格式 xlsx(决策已定)**,对齐 v1.5 §6.7/§13.5「Excel 导出复用报告/导出服务 + 模板库」;docx 留 `format` 参数位,本轮不实装。模板占位:问题 / 答复摘要 / 依据条款(四级定位)/ 相似案例 / 路由类型 / 导出人 / 导出时间 / **AI 内容标识页脚**。导出动作**过 Casbin 导出权限点 + 写操作日志**(本轮留接缝 stub;无权 → 403)。

### 8.2 推荐问题

```
GET /suggestions?agent_type=institution_query
200 { "items": ["客户适当性管理的监管要求有哪些?", "持续管理的留痕要求是什么?", … ] }
```
配置驱动(`config/` 新增 `[query.suggestions]` 或 yaml),可按 `agent_type` 返回不同集;**不硬编码进代码**。

### 8.3 条款回查(联动 / 查看原文)

```
GET /clauses/{clause_id}
200 {
  "clause_id","doc_title","doc_no","clause_path","page_start","page_end","version","status",
  "text": "<条款全文>",            // chunks.text(权威,非 Milvus 截断)
  "parent_text": "<节级父块全文>"  // 供证,fetch_parent_text(§5.6),无则 null
}
```
复用 `generate/anchors.py::fetch_anchors` / `fetch_parent_text`。原型「查看原文」「详细释义 >>」「完整定义 >>」「查看更多 >>」均打此端点(前端按需展开)。

### 8.4 文件上传

```
POST /uploads   (multipart/form-data, field=file)
201 { "upload_id","filename","size","content_type" }
```
校验:content-type 白名单 **PDF/Word/Excel**(415 不符);尺寸 ≤50MB(**413** 超限,按 Content-Length 预拒不入内存,镜像 pipeline web `_PayloadTooLarge`)。`upload_id` 在提问 `attachments` 引用。**MVP 语义**:附件仅作提问上下文附着(检索侧消费策略列后续),本轮只定上传/引用契约。

---

## 9. 错误语义与状态码(统一)

**统一错误体**(所有端点 + SSE `error` 事件):
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "查询超过 2000 字", "details": {} } }
```

| 状态码 | code 例 | 场景 |
|---|---|---|
| 400 | `MALFORMED_REQUEST` | JSON 解析失败 / 缺必填 |
| 401 | `UNAUTHENTICATED` | 未登录(鉴权接缝) |
| 403 | `FORBIDDEN` | 无权限(导出权限点等,Casbin) |
| 404 | `NOT_FOUND` | 会话 / 消息 / 条款不存在 |
| 413 | `PAYLOAD_TOO_LARGE` | 上传超 50MB / 请求体超限 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 上传非 PDF/Word/Excel |
| 422 | `VALIDATION_ERROR` | query>2000 字 / 分页越界 / 附件不存在 |
| 429 | `RATE_LIMITED` | 限流(§12 预留) |
| 500 | `INTERNAL_ERROR` | 内部错误(**不泄细节**,详情进日志/trace) |

**推进可靠性契约**(继承 CLI 口径):SSE 中途 stage 异常**不静默成功**——发 `error` 事件 + 该消息落库标 `route_type` 失败态,不写半截 `structured`。

---

## 10. 校验与红线(边界)

- **仅边界校验**:query≤2000、`page/page_size` 上界(page_size ≤ 100 ⚠)、上传白名单 + 尺寸、`attachments` 引用存在、`corpus ∈ {internal,external,null}`。内部纯函数信任类型。
- **单向只读**:API 绝不回写任何源系统 / corpus 权威表;仅写 query 自有 `query_*` 会话表。
- **AI 标识**:响应 `ai_label` 恒 `true`;导出含固定 AI 标识页脚(§9.3)。
- **判定型**:`route_type=judgmental` → `review_required=true`,前端渲染「AI 辅助判断,人工复核」框(v1.5 CP-007)。
- **无编造 / 无裸结论**:引用只来自检索上下文 `clause_id`;拒答给 `exhausted_scope`;结构化字段缺失即省略,不用 LLM 兜任何「依据类」字段(§12 已分档)。

---

## 11. 命名与版本约定

- **路径**:`/api/query/v1/` + 复数资源名,无动词(`/conversations` 而非 `/getConversations`)。
- **JSON 字段**:snake_case(与 `contract.py` 既有契约一致);枚举值小写(`route_type` 沿用 `evidence/change/case/…`);布尔 `is_*/has_*/*_enabled/*_required`(沿用 `export_enabled`/`review_required`)。
- **日期**:ISO-8601 字符串(`date` → `YYYY-MM-DD`);`elapsed_ms` 整数毫秒。
- **分页**:`{data, pagination:{page,page_size,total_items,total_pages}}`,全列表端点一致。
- **演进**:只加可选字段;破坏性变更 → `/v2`。

---

## 12. 富集来源分档(诚实口径 · 生产保真)

**判据**:✅ = PG 现成回查即得;⚠-model = 需 LLM 提炼(开关,默认关 → 缺省 `null`/`[]`,前端隐藏);⚠-data = 依赖尚未落地数据(打标 / 指代表),缺失即**省略**,不占坑不臆造。

| 分档 | 字段 | 处置 |
|---|---|---|
| ✅ 现成 | title / doc_no / issue_date / effective_date / issuer / clause_path / text 节选 / status;案例 penalty_org / penalty_date;四级锚点 | 直接回查填充 |
| ✅-score(已定) | `match_score` 匹配度 | 检索融合分 **min-max 归一 → 前端直显 0–100%**(决策已定,贴原型 95%/92%)。⚠ 剩实现细节:归一窗口取「本次候选集内 min-max」还是「全局固定锚」,PLAN 定;契约字段恒 `0–1` float |
| ⚠-data | `theme` 适用主题 / `related_internal` 关联内规 / 案例 `violation_theme` / `related_regulations` | 依赖 clause_tags 打标 / clause_references 指代表(Q5 空表)/ 案例 L2;**未落地即省略该列** |
| ⚠-model | `summary` 条款摘要(可截断兜底)/ `core_issue` / `insight` / `citation_advice` / `regulatory_digest` / `case_insights` / 会话 `title`(LLM 概括) | LLM 提炼开关;**默认关** → 摘要走截断、标题回落首问截断、卡片/引用建议缺省空前端隐藏;**绝不用 LLM 生成依据类事实** |

> 这张表是「不放水」的落地保证:原型好看的富集字段,**哪些真、哪些占位**一目了然,交付时按档实装,不以「demo 够用」蒙混。

---

## 13. 决策记录(已定 · 2026-07-01 门控澄清)

| # | 决策项 | **已定** | 影响 / 落地口径 |
|---|---|---|---|
| 1 | HTTP 层技术选型 | **FastAPI/Starlette** | 原生 SSE(StreamingResponse)/ multipart / pydantic 校验 / async;新增 `fastapi`+`uvicorn` 依赖(3.11 兼容)。取代原「stdlib 或轻框架 ⚠」 |
| 2 | `match_score` 匹配度口径 | **归一百分比直显** | 融合分 min-max 归一 → 前端直显 0–100%(贴原型)。归一窗口(候选集内 vs 全局锚)= 实现细节,PLAN 定 |
| 3 | 附件上传消费策略 | **本轮只存不消费** | 只定上传 / `upload_id` 引用契约;文件存下、检索侧**不读附件内容**。消费(上下文/临时索引)列下一迭代 |
| 4 | Casbin 鉴权接入时机 | **stub 接缝 + 导出点 403** | 设计鉴权接缝(角色上下文、导出权限点),用 stub 放行;401/403 语义 + 操作日志位定好,真 Casbin/SSO 后续增量接 |
| 5 | 会话标题生成 | **LLM 概括(开关,默认关)** | 默认关 → 回落**首问截断**(确定性、零 LLM);开关开 → LLM 概括。列 §12 ⚠-model |
| 6 | 功能2(制度比对)会话表 | **另建独立表** | `query_*` 会话表**只服务功能1**;功能2 落地时单独建表(其双栏对比/差异清单形态差异大)。本表 `agent_type` 恒 `institution_query` |
| 7 | 导出默认格式 | **xlsx(Excel)** | 对齐 v1.5 §6.7/§13.5;`format` 参数留位,docx 本轮不实装 |
| 8 | 首答流式实现顺序 | **先真流式,再 SSE** | 先落 gateway 真 token 流式生成(§7.2),再上 SSE 端点(`answer_delta` 由真流式喂),**不做伪流式**。PLAN 中 SSE 任务依赖真流式任务前置 |

> 残留实现级 TODO(不阻塞契约,PLAN/实现阶段定):match_score 归一窗口取法;附件消费迭代;Casbin 真策略与六类权限点全接;真流式的网关模型与首 token<3s 验证。

---

## 14. 验收(设计层 · 门控清单)

- [ ] 每个端点有 typed 请求/响应形状(§3–§8),错误体单一(§9)。
- [ ] §10 `QueryResult` 仅**加法**(structured/meta),既有 8 字段 + CLI 输出 byte 等价。
- [ ] 四-Tab 每字段可追溯到 §12 来源分档(✅/⚠-*),⚠ 字段有明确缺省与省略规则(零臆造)。
- [ ] SSE 事件序列覆盖 evidence / refuse / clarify / judgmental 四类路由,含 error/keep-alive;`answer_delta` 由 **gateway 真流式**喂(SSE 任务依赖真流式前置任务先绿,不做伪流式)。
- [ ] PG 新表 add-only、`query_` 前缀、不碰 corpus 权威表;迁移随 `demo up` 生效。
- [ ] 分页 / 命名 / 日期 / 版本 约定全端点一致(§11)。
- [ ] 红线断言可测:无编造引用 / 无裸结论 / ai_label 恒真 / 判定型 review_required / 单向只读。

---

## 15. 与既有代码的接缝(不改域,薄壳封装)

- **HTTP 层**:**FastAPI/Starlette**(决策已定;原生 SSE / multipart / pydantic 校验 / async,取代 pipeline web 的 stdlib 路线——本 API 面比 demo 工作台重)。新增 `fastapi`+`uvicorn` 到 `query/pyproject.toml`(3.11 兼容,无 grpcio/torch 类坑)。新目录 `query/query/api/`(`app.py` FastAPI 路由 + `service.py` 域函数装配 + `serializers` 契约序列化 + `sse.py` 事件编排)。
- **域复用,零改**:`graph.py::QueryAgent.ask/route_only`(问答/路由)、`generate/anchors.py`(四级回查 / 父块供证 / 条款回查端点)、`case/case_card.py`(案例卡)、`case/r3_case.py::attach_cases`(相关案例 Tab 数据)。四-Tab 装配 = **新 API 层函数**,读 `citations` + 检索候选 + PG,**不入 graph 节点**。
- **会话持久化**:新增 `query/query/session/`(`store.py` over PG `query_*` 表 + 域函数);`messages` 端点在 `ask` 前后落库。
- **配置**:`config/settings.toml` 新增 `[query.api]`(host/port/超时/上传上限/推荐问题)、`[query.enrich]`(summary/digest/insight LLM 开关,默认关)。⚠ 集中,不硬编码。
- **测试**(交实现阶段):契约序列化单测(structured/meta 加法后 §10 byte 等价)、SSE 事件序列单测、会话 CRUD + 分页/搜索集成、四-Tab 富集分档(⚠ 字段缺省省略)golden、边界校验(2000 字 / 413 / 415 / 422)。

---

> **下一步(门控)**:本 spec 批准后 → `planning-and-task-breakdown` 出 PLAN-API / TASKS-API(端点、契约、会话表迁移、SSE、导出各拆任务,标 RTM)→ 逐任务 TDD 落地 → 交 Codex 审。**未批准不进实现。**
