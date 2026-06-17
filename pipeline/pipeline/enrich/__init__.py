"""富集层(enrich):IR 边界下游的条款级打标。

M3 仅 E1 义务预打标(`e1_obligation`,零 LLM 正则)。E2/E3(LLM 事项/图谱)留独立轮。
enrich 为纯/半纯函数,只读 chunks + 写 clause_tags,由装配层(`cli.py::_structuring`)调度,
不被 stage import、不参与状态机迁移(富集副作用,无终态阻断权)。
"""
