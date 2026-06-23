"""R3 相似案例 + 案例桥接(§6.3):case 分区检索 → 要素回填卡片 + 精确反查桥接 + 附挂到 R1。

纯函数(``case_card`` 组卡 / ``bridge`` 反查)+ 编排(``r3_case``);本包不 import langgraph,
节点薄封装在 ``graph.py``。全程零 LLM(检索 + PG 回填 + 机械组装)。
"""
