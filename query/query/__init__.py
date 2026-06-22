"""audit-query —— 制度查询智能体(功能1,Chatbox 型 / 同步流式)。

本切片:R1 依据查询 + 覆盖感知拒答 + 八路路由/契约骨架。
依赖方向:query → pipeline → common(**只读消费** V1.6 摄取产物;绝不被 pipeline/common 反向 import)。
设计:``docs/制度查询智能体_技术框架设计_v1_0.md``;SDD 产物:``docs/query-agent-docs/``。
"""
