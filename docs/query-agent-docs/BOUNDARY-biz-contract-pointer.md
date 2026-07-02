# 边界契约指针:audit-ai query API ↔ audit-biz 主本

> **本文件是指针(pointer),不是主本。** audit-ai 对 audit-biz 的服务契约(边界二)+ 对账/整改方案的
> **权威主本在 audit-biz 仓**;本仓只留指针,防「两份漂移」(v0.4 §15「以 CP 回灌」)。
> 契约任何改动先改 audit-biz 的 `boundary.v1.yaml`(规范单一源),本仓照做。

## 权威来源(audit-biz 远端)

- 仓库:`https://github.com/258ZZZ258/audit-biz`(SSH: `ssh://git@ssh.github.com:443/258ZZZ258/audit-biz.git`)
- **边界契约(规范单一源)**:`docs/audit-biz-docs/openapi/boundary.v1.yaml`(**v1.1.0**)
  - https://github.com/258ZZZ258/audit-biz/blob/main/docs/audit-biz-docs/openapi/boundary.v1.yaml
- **语义主本**:`docs/audit-biz-docs/SPEC-BOUNDARY.md`
- **对账 + 整改方案(本仓要照做的完整方案)**:`docs/audit-biz-docs/BOUNDARY-RECONCILIATION-001.md`
  - https://github.com/258ZZZ258/audit-biz/blob/main/docs/audit-biz-docs/BOUNDARY-RECONCILIATION-001.md

## 背景(为什么有这份指针)

audit-ai 的 query-api(PR#39,已并 `main`)是对着产品原型**直连前端**的会话式富 API
(`POST /api/query/v1/conversations/{cid}/messages` + `/clauses` + `/exports`,`auth.py` 带 subject/role 身份,
新建 `query_*` 会话表),**与 audit-biz 冻结的边界契约 CP-A 漂移**。
用户决策(2026-07-02):**守边界**——audit-ai 在现有 `QueryAgent.ask` 上加**薄壳** `POST /v1/query`,**不改 AI 内核**
(漂移在 HTTP 薄壳、不在域逻辑;`contract.py` 的 `QueryResult/AnswerBlock/Citation` 本就是 CP-A 对齐对象)。

## 本仓要做什么(摘要;完整 build recipe 见上方 `BOUNDARY-RECONCILIATION-001.md §3`)

在 `query/query/api/` 新增薄壳 `POST /v1/query`:

1. `X-Internal-Token` 静态共享密钥鉴权、**无身份**(勿复用 `auth.py` 的 subject/role)。
2. 请求 `filters{perm_tags, corpus_types, project_id, owner}` → 构 **Milvus 前置过滤**(检索**前**生效,红线:算在 Java、用在 Python)。
3. SSE 事件 `meta / delta / citation / done / error`(词汇见 boundary 附录 A);`citation` 加 per-hit `score`
   (v1.1.0 加法,供 biz 装制度查询四-Tab「匹配度」)。
4. `request_id` 注入 Langfuse trace。
5. 会话 / 身份 / PG 引用回查 / 导出**不进边界**(归 biz);`QueryAgent.ask`、`structured_for` 域逻辑**原样复用**。

差异对照 BR-1~8(端点形状 / 前置过滤红线 / 无身份 / 状态-回查-导出归属)见 `BOUNDARY-RECONCILIATION-001.md §2`。

> ⚠ **分支**:query-api 在 `main`。请从 audit-ai `main` 切分支实施(如 `feat/v1-query-boundary`)。
> **同机可执行 finding**(gitignore、不入库):本仓 `.review/findings.json` → `boundary.contract.query-api-drift`(critical)。

## 双向引用坐标(remote ↔ remote)

| 方向 | 位置 |
|---|---|
| audit-ai → audit-biz | 即本文件;引 `https://github.com/258ZZZ258/audit-biz` 的 `boundary.v1.yaml` + `BOUNDARY-RECONCILIATION-001.md` |
| audit-biz → audit-ai | `BOUNDARY-RECONCILIATION-001.md §7/§8`;远端坐标 `https://github.com/258ZZZ258/audit-ai`,待改代码 `query/query/api/*` |
