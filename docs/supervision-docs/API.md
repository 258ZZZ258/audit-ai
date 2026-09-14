# 监督元数据与提取调用

本地启用：将 `config/supervision.env.example` 复制为仓库根目录 `.env.local`，填写模型密钥和内部服务令牌后，运行 `tools/start-supervision-api.ps1`。令牌须与 Pi 的 `AUDIT_AI_INTERNAL_TOKEN` 相同，Pi 同时设置 `AUDIT_AI_BASE_URL`。真实 `.env.local` 不提交到仓库。

2026-09-10 补充：facts 新增 factType（FINDING/RECTIFICATION/ACCOUNTABILITY/LITIGATION/UNSPECIFIED），整改进展复述历史问题不得作为新增问题，问责决定独立处理。旧结果未提供时为 UNSPECIFIED，消费方应重新抽取歧义旧记录。

`POST /v1/supervision/verify-fields` 使用相同内部令牌；请求 claims 数组（1–8条），每条 id、field、value（最多4000字符）、evidence（完整引用上下文，最多32000字符）。响应 verdicts 中逐条返回 id、supported 布尔值、reason。支持忠实概括，但必须核对主体、金额、否定和完成程度。证据不足为 false。ID不完整、重复或非法响应为422，模型关闭503、调用失败502。不截断过长原文，不以调用失败替代核验结论。该接口不自行查询文档权限/数据库版本，调用端只传已授权证据。

`POST /v1/supervision/extract` 已注册到现有 `query.api.app:app`。鉴权头 `X-Internal-Token` 对应部署环境 `AUDIT_AI_INTERNAL_TOKEN`；不传用户令牌，不在 Python 计算用户权限。Java 必须先完成资料授权。

此接口位于已有 S0–S5 入库之后：Java 上传并维护元数据 → 现有管线生成 IR/索引 → 本接口提取 → Java/Pi 消费。
它不接收文件字节、不新建上传入口、不重跑 OCR，也不让请求方自行声称已经 indexed。
documentId/documentVersionId 必须对应当前 PG logical_id/doc_version_id；Java 自有附件主键若不同，调用前解析为本平台实际文档标识，不涉及甲方源系统关联。

## 请求

```json
{
  "metadata": {
    "documentId": "DOC-1", "documentVersionId": "DV-1",
    "fileName": "监管函.pdf", "title": "监管检查函", "issueDate": "2026-06-30",
    "categoryCode": "REG", "documentOrigin": "external",
    "organizationIds": ["ORG-1"], "uploadEntry": "supervision"
  },
  "organizations": [{ "organizationId": "ORG-1", "name": "甲单位", "aliases": [] }],
  "rules": [{
    "ruleId": "REG-1", "reportSection": "external.regulatory",
    "extractFields": [{ "key": "problem", "description": "监管检查发现的问题事实", "required": true }]
  }]
}
```

示例类别/规则是测试编码。实际 rules 从 Pi 既有九类规则选择，投影 ruleId、reportSection、extractFields 的 key/description/required。
类别和内外部文档不自动等同于上传部门或 P-INT/P-EXT 分区。单位目录必须与上传涉及单位 ID 集合一致，简称重名不能强行归属。
请求不接收权限名单、上传人、源系统编号、导入编号、客户端提供的 indexed 状态或存储路径。

## 响应

- `uploadedMaterial`：直接符合 Pi `supervision-upload-material.v1`。保留 Java 标题/日期/类别/单位，标题空白回退文件名；服务核验 PG 后提供 `processingStatus=indexed`。
- `parseVersion` 是当前 IR 内容指纹，`indexVersion` 是当前 PG chunk 内容指纹；不是新增数据库列。请求结束前重读版本、IR、chunk 核对，变化则返回 409。
- `evidence`：完整段落、表格各行（含表头），有文档/版本、证据 ID、PARAGRAPH/TABLE_ROW/PAGE_TEXT 定位、页码及原文。页码缺失保留 null，不伪造。PAGE_TEXT 是文本 PDF 的同页连续排版行，locatorValue 形如 blocks:0-13，text 保留原换行；不跨表格或标题，IR 保持不变。
- `metadataChecks`：标题差异、缺失/无效发文日期、正文日期候选等。不自动用正文某个日期替换发文日期。
- PDF 引用若只有 CR/LF 换行位置不同，且忽略 CR/LF 后在 PAGE_TEXT 中唯一匹配，可恢复为原文原始摘录；metadataChecks 增加 PDF_QUOTE_LINE_BREAKS_RESTORED，携带 field、ruleId、evidenceId。其他字符（包括空格、数字、标点）变化或多处匹配仍拒绝，返回 quote 保持可逐字回查。表格和普通段落不应用此恢复。
- `facts`：按规则输出的业务字段候选。每字段包含 value、evidenceId 和逐字 quote；跨页或分散的事实还包含可选 supportingEvidence（evidenceId/quote 数组）。主引用与全部补充引用共同支持该字段，不能只读取主引用。另带 ruleId、reportSection、organizationIds、missingRequiredFields。
- 若规则含 evidenceLocation，此字段由后端使用全部主引用及补充引用的页码/块范围生成，不交给模型猜测；value 属于证据元数据，evidenceId/quote 指向首个业务引用，有跨页补充引用时还保留去重后的 supportingEvidence。页码缺失时只输出真实块范围。
- `extractionStatus=EVIDENCE_READY`：模型未开启，只有证据与元数据校验；facts 为空不表示没有问题。
- `extractionStatus=EXTRACTED`：所有证据组均已提交提取并通过结构/引用校验。仍是 `PENDING_REVIEW` 候选，不证明语义、分类和单位判断全部正确，不等于 `AUTO_CONFIRMED`。

前端逐段引用仍仅展示名称；原文证据用于后台校验。Java 应保存返回证据及候选结果，再按业务规则转成 Pi 的 issues/rectifications/accountabilities；不可将 facts 直接当作已经确认的问题列表。
Java 保存、转发或生成报告段落依据时须同时读取主 evidenceId/quote 和 supportingEvidence，按文档去重展示资料名称，不能丢掉跨页的补充证据。此调整无需新增任务表单字段。旧模型响应可不含 supportingEvidence，空列表不会写入结果，旧单引用候选继续有效。
资料上传、业务日期筛选、最新月份选择、历史问题关联等分别沿用既有分工；本接口本身不替用户创建任务或确认资料。

跨页字段示例（编号仅示意，实际必须完整复制本次 evidenceId）：

```json
{
  "issueDescription": {
    "value": "申报时遗漏相关事项披露，保荐核查未充分履行。",
    "evidenceId": "DV-1:blocks:14-36:完整内容摘要",
    "quote": "该页中关于未披露事项的连续原文",
    "supportingEvidence": [{
      "evidenceId": "DV-1:blocks:37-59:完整内容摘要",
      "quote": "另一页中关于核查责任的连续原文"
    }]
  }
}
```

每个引用都校验本次模型证据组与逐字原文。跨组的内容仍单独提取，不凭模型推测合并，也不能用 facts 长度作为去重后的问题数量。

## 模型配置

### 问题与记录的向量相似度

`POST /v1/supervision/similarity` 沿用 X-Internal-Token。请求为 pairs 数组，每项含 pairId、issueText、recordText；每次1至64对，每段1至4000字符，超限拒绝，不静默截断。响应 scores 数组逐对返回 pairId 与0至1的余弦相似度。复用既有 embedding 配置（本地BGE-M3或配置的远端），去重文本后批量嵌入，不接收外部相似度、不读写业务数据库、不跨范围搜索资料。调用方负责先按任务和权限限定资料范围；评分只用于候选排序，不等于确认事实。缺向量、零向量、非有限值、维度错误或重复pairId均拒绝。

model_timeout_seconds 默认300秒（大于0、最大900），model_attempts 默认2（1到3），均在 supervision.toml 配置。监督调用不再沿用查询的60秒超时；HTTP层只调用一次，由提取层对调用失败或 JSON/schema 失败有限重试。成功重试记录 metadataChecks.code=MODEL_OUTPUT_RETRY 与 attempt；耗尽仍失败，引用不匹配不会被宽松修复。多组提取时每组分别限制次数，调用方网关超时与异步任务机制需要按实际总耗时配置。

当前 `config/supervision.toml` 已按要求设置 backend="gateway"；密钥仍从环境读取。部署时可用 `SUPERVISION_CONFIG` 指定外部配置文件，或设置 backend="none" 关闭模型。
gateway 复用现有 LLMClient，使用进程环境 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL；不自动加载 .env、不保存密钥。
max_evidence_chars 控制单次证据文本分组容量（不含规则和元数据开销，不是 token 上限）。每一组都处理，单段超容量显式报错，不截断。

## 错误

- 401：服务令牌未设置或错误。
- 404：文档版本不存在。
- 409：文档/版本不一致、非 INDEXED/effective、降级或 staging chunk、IR 缺失、提取期间版本内容改变。
- 422：请求结构、IR 内容或模型字段/证据校验不通过。
- 500：模型或存储等内部错误。不会伪装为空结果，也不返回密钥、内部异常或模型原始输出。

## 验证边界

定向 pytest 使用真实 DOCX 解析器和本地 ObjectStore；数据库读取用测试替身，模型用注入的可控响应。另于 2026-09-04 用上交所原始 3 页 PDF 完成 LightParser → 真实 DeepSeek V4 Flash → 引用校验补测，并独立验证扫描测试件 MinerU OCR，结果和完整性限制见 PLAN。真实 Java、HTTP 服务与 PostgreSQL/Milvus 未在该补测串联。
当前环境现有 .venv 是 Python 3.12.7；源码按仓库 Python 3.11 语法目标编写并经 Ruff 校验，但本轮未在 3.11 重跑。
# 无编号逐项关联

`POST /v1/supervision/associate`，沿用内部令牌鉴权。请求 `pairs` 与 similarity 的每对字段相同（pairId/issueText/recordText），每批 1–8 对，每侧文本最长 4000 字符。返回 `decisions`，每对包含 pairId、verdict（MATCH/NO_MATCH/UNCERTAIN）、reason、issueQuote、recordQuote。

引用必须分别为输入文本的非空连续子串，ID 必须唯一且完整覆盖请求。不通过返回 422，模型关闭返回 503，模型调用失败返回 502。模型传输/JSON解析失败按 model_attempts 有限重试；证据校验不放宽，结构/覆盖错误不重试。配置复用 SUPERVISION_CONFIG 和现有网关环境变量。缓存和评测入口见 OPTIMIZATION.md。

输入是调用方已限定范围的抽取描述，并非该接口从数据库读取全文。MATCH 仅表示事项对应，不代表整改完成；多候选及跨问题歧义由 Pi 汇总处理。已确认关系返回两侧 evidenceIds，判定理由及摘录保留在 Pi 工具详情中。
