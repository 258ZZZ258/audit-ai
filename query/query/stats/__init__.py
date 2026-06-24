"""R6 统计型(§6.6):规则维度抽取 + 参数化 SQL 聚合 over ``cases``,**不走向量检索**。

`dimensions`(规则抽取)/ `sql_builder`(白名单 + bound params 防注入)/ `r6_stats`(编排)均纯函数 +
PG 只读;本包不 import langgraph,节点薄封装在 `graph.py`。全程零 LLM、不触 Milvus/embedding。
"""
