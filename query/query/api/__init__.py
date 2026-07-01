"""制度查询智能体 HTTP API 层(SPEC-API)。

薄壳 over 域纯函数:参数校验 → 调 ``query.graph``/``query.*`` → PG 回查富集 → 契约序列化 →
(SSE)事件编排。**不进 graph 域节点**;单向只读(只写 query 自有 ``query_*`` 会话表)。
"""
