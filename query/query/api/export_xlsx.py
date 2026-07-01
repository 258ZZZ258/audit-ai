"""T9(SPEC-API §8.1 / v1.5 §6.7):查询报告 xlsx 模板填充。

模板占位:问题 / 答复摘要 / 依据条款(四级定位)/ 相似案例 / 路由类型 / 导出人 / 导出时间 +
**固定 AI 内容标识页脚**(§9.3)。纯函数:吃已取好的字段 → xlsx bytes(无栈可测)。
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

#: AI 内容标识页脚(§9.3):所有导出文件固定携带。
AI_LABEL = "本报告内容由 AI 生成,仅供参考,请人工复核。(AI 内容标识)"


def build_export_xlsx(*, question, answer_summary, result, exporter, exported_at) -> bytes:
    """组 xlsx。``result`` = 该轮 §10+structured 契约快照(result_json)。"""
    result = result or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "制度查询报告"

    ws.append(["项目", "内容"])
    ws.append(["问题", question or ""])
    ws.append(["答复摘要", answer_summary or ""])
    ws.append(["路由类型", result.get("route_type", "")])
    ws.append(["导出人", exporter])
    ws.append(["导出时间", exported_at])

    ws.append([])
    ws.append(["依据条款(四级定位)"])
    for c in result.get("citations", []):
        loc = (
            f"{c.get('doc_title', '')} {c.get('clause_path', '') or ''} "
            f"p.{c.get('page_start', '')} [{c.get('status', '')}]"
        )
        ws.append([c.get("clause_id", ""), loc])

    ws.append([])
    ws.append(["相关案例"])
    for case in _cases(result):
        ws.append([case.get("title", ""), case.get("regulator", ""), case.get("penalty_date", "")])

    ws.append([])
    ws.append([AI_LABEL])            # AI 标识页脚(数据行)
    ws.oddFooter.center.text = AI_LABEL   # 打印页脚亦带

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cases(result) -> list:
    structured = result.get("structured") or {}
    return (structured.get("cases") or {}).get("items", [])
