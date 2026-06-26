"""T1.4 ref_render:窗口渲染原语(§6.7)——把指代注释临时插入窗口文本,不落库。

复用面(三处,主文档 §6.7):S6 图谱窗口装配、比对交叉验证、查询条款跳转。纯逻辑:
- 按 span **倒序**插入〖gloss〗,防前面插入令后面 span 偏移漂移;
- gloss ≤ ``gloss_max``(默认 30)截断;
- ``render=False``(UNRESOLVED / ambiguous)**不渲染**——宁缺勿错(§6.7)。
``chunks.text`` 永不被改:渲染产物是临时字符串,调用方自行使用、不回写。
"""

from __future__ import annotations

from dataclasses import dataclass

_GLOSS_OPEN = "〖"
_GLOSS_CLOSE = "〗"


@dataclass(frozen=True)
class Annotation:
    """一处待渲染注释:在 ``span_end``(引用表面末尾)后插入〖gloss〗。"""

    span_end: int
    gloss: str  # target 可读形式(如「即第三十一条第一款」「文档标题+文号」)
    render: bool = True  # UNRESOLVED / ambiguous → False(不渲染)


def render_window(text: str, annotations: list[Annotation], *, gloss_max: int = 30) -> str:
    """按 span_end 倒序插〖gloss〗;render=False 跳过;gloss 超长截断。返回带注释文本。"""
    out = text
    for a in sorted(annotations, key=lambda x: x.span_end, reverse=True):
        if not a.render:
            continue  # 宁缺勿错:未解析/歧义不渲染
        gloss = a.gloss[:gloss_max]
        out = out[: a.span_end] + f"{_GLOSS_OPEN}{gloss}{_GLOSS_CLOSE}" + out[a.span_end :]
    return out
