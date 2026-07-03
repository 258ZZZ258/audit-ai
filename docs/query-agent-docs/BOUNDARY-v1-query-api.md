# audit-biz 调用 audit-ai 查询接口说明

> 本文件是 audit-ai 侧的落地说明,方便本地联调和排查问题。接口契约主本仍以
> audit-biz 仓的 `docs/audit-biz-docs/openapi/boundary.v1.yaml` 为准。

## 一句话说明

Java 后端 `audit-biz` 调 Python 服务 `audit-ai` 时,走内部接口:

```text
POST /v1/query
```

这个接口只给 Java 后端调用,不是前端页面接口。前端相关接口仍是:

```text
/api/query/v1/*
```

## 本地服务端口

本地启动查询服务时,建议用 `8770` 端口:

```powershell
$env:AUDIT_AI_INTERNAL_TOKEN = "dev-secret"
.venv\Scripts\python.exe -m uvicorn query.api.app:app --host 127.0.0.1 --port 8770
```

本地健康检查:

```text
GET http://127.0.0.1:8770/healthz
```

Java 后端本地联调地址:

```text
http://127.0.0.1:8770/v1/query
```

端口号不是契约本身,部署时可以由运维或 Java 配置改成其他地址;真正稳定的调用路径是
`/v1/query`。

## 鉴权

请求必须带内部令牌:

```text
X-Internal-Token: <内部共享令牌>
```

Python 服务读取环境变量:

```text
AUDIT_AI_INTERNAL_TOKEN
```

令牌缺失或不一致时,返回:

```json
{
  "error": {
    "code": "B104",
    "message": "内部令牌无效"
  }
}
```

## 请求体

示例:

```json
{
  "query": "客户适当性管理有什么要求?",
  "request_id": "REQ-20260703-0001",
  "filters": {
    "perm_tags": ["内部"],
    "corpus_types": ["internal", "external"],
    "project_id": null,
    "owner": null
  },
  "options": {
    "top_k": 5,
    "include_superseded": false
  }
}
```

字段说明:

| 字段 | 必填 | 说明 |
|---|---:|---|
| `query` | 是 | 用户问题。不能为空字符串。 |
| `request_id` | 是 | Java 后端生成的请求编号。Python 会把它写入追踪链路,方便排查。 |
| `filters.perm_tags` | 是 | Java 已算好的权限标签。Python 只消费这个结果,不重新判断用户身份。 |
| `filters.corpus_types` | 是 | 本次允许查询的语料类型。 |
| `filters.project_id` | 否 | 审计项目编号。当前只为后续审计项目语料预留。 |
| `filters.owner` | 否 | 审计项目负责人。当前只为后续审计项目语料预留。 |
| `options.top_k` | 否 | 返回候选数量上限。缺省时使用 query 配置里的默认值。 |
| `options.include_superseded` | 否 | 是否包含已被替代的旧版本制度。默认 `false`。 |

语料类型映射:

| Java 传入值 | Python 检索分区 | 说明 |
|---|---|---|
| `internal` | `P-INT` | 内规 |
| `external` | `P-EXT` | 外规 |
| `qa` | `P-QA` | 监管问答 |
| `case` | `P-CASE` | 案例 |
| `audit_project` | `audit_project` | 审计项目语料,当前字段链路尚未完整接入 |

## 返回格式

返回类型是流式事件:

```text
Content-Type: text/event-stream
```

事件格式:

```text
event: <事件名>
data: <JSON>
```

成功请求通常按这个顺序返回:

```text
meta -> delta -> citation -> done
```

异常时返回:

```text
error
```

## 事件说明

### `meta`

查询元信息,一开始返回。

```json
{
  "request_id": "REQ-20260703-0001",
  "route_type": "evidence",
  "ai_label": "依据查询",
  "review_required": false,
  "export_enabled": true
}
```

### `delta`

答案正文块。一个回答可能有多个正文块。

```json
{
  "block_seq": 0,
  "block_type": "text",
  "text": "根据现有制度,客户适当性管理需要..."
}
```

### `citation`

轻量引用。Python 只返回条款或切块标识,详细标题、页码、版本状态由 Java 后端回查数据库后装配。

```json
{
  "clause_id": "abc123",
  "chunk_id": "abc123",
  "score": 0.87
}
```

字段说明:

| 字段 | 说明 |
|---|---|
| `clause_id` | 条款或切块主标识。Java 用它回查制度详情。 |
| `chunk_id` | 当前和 `clause_id` 一致,保留给后续细分。 |
| `score` | 匹配度,范围约为 0 到 1。可能为空,不能用于权限判断。 |

### `done`

本次回答结束。

```json
{
  "finish_reason": "stop",
  "confidence": 0.82,
  "exhausted_scope": []
}
```

`finish_reason` 常见值:

| 值 | 说明 |
|---|---|
| `stop` | 正常完成 |
| `refused` | 查询智能体拒答 |

### `error`

生成过程中发生异常时返回。

```json
{
  "code": "INTERNAL_ERROR",
  "message": "生成失败"
}
```

## 调试示例

PowerShell 里可以用:

```powershell
curl.exe -N `
  -H "Content-Type: application/json" `
  -H "X-Internal-Token: dev-secret" `
  -d "{\"query\":\"客户适当性管理有什么要求?\",\"request_id\":\"REQ-local-1\",\"filters\":{\"perm_tags\":[\"内部\"],\"corpus_types\":[\"internal\"],\"project_id\":null,\"owner\":null},\"options\":{\"top_k\":5,\"include_superseded\":false}}" `
  http://127.0.0.1:8770/v1/query
```

## 职责边界

Java 后端负责:

| 事项 | 说明 |
|---|---|
| 用户登录和权限判断 | Python 不接收用户身份,只接收 Java 算好的过滤条件。 |
| 会话保存 | Python 的 `/v1/query` 是无状态接口。 |
| 引用详情回查 | Python 只返回 `clause_id/chunk_id/score`;标题、页码、版本等由 Java 查库。 |
| 导出 | 导出归 Java 后端或前端业务接口处理。 |
| 对外入口 | 对用户暴露的统一入口是 Java 后端,不是 Python 服务。 |

Python 服务负责:

| 事项 | 说明 |
|---|---|
| 智能查询 | 调用现有查询智能体生成答案。 |
| 检索 | 根据 Java 传来的语料范围和权限标签做向量库前置过滤。 |
| 流式返回 | 把查询结果转换成 `meta/delta/citation/done/error` 事件。 |
| 追踪 | 把 `request_id` 写入查询追踪链路。 |

## 当前限制

`audit_project` 语料里的 `project_id/owner` 过滤当前还没有完整接入。

原因是 audit-ai 当前向量库字段里还没有 `project_id` 和 `owner`。如果强行支持,只能先检索再过滤,
这不符合权限隔离要求。因此当前处理是:

| 请求情况 | 当前行为 |
|---|---|
| 查询制度语料,带 `owner` | 忽略 `owner`,按制度语料权限标签和语料类型过滤。 |
| 查询 `audit_project`,且带 `project_id` 或 `owner` | 返回参数错误,不做未隔离检索。 |

后续要完整支持审计项目语料,需要先补齐向量库字段和入库链路,再开放这两个过滤条件。

## 代码位置

| 文件 | 作用 |
|---|---|
| `query/query/api/routes_boundary.py` | `/v1/query` 接口实现 |
| `query/query/api/app.py` | 挂载 `/v1/query` |
| `query/query/retrieve/hybrid.py` | 请求级检索范围下推 |
| `query/query/graph.py` | `request_id` 进入查询追踪 |
| `query/tests/test_api_boundary.py` | 边界接口测试 |

