"""T1.4 ref_render 窗口渲染原语:按 span 倒序插注释、gloss≤30、unresolved 不渲染(§6.7)。"""

from pipeline.chunking.ref_render import Annotation, render_window


def test_inserts_in_reverse_no_offset_drift():
    # 两个注释倒序插入,互不偏移(spec:按 span 倒序防偏移漂移)
    text = "依照前条和第十五条"  # 「前条」end=4,「第十五条」end=9
    anns = [Annotation(span_end=4, gloss="即第十四条"), Annotation(span_end=9, gloss="即2/15")]
    out = render_window(text, anns)
    assert out == "依照前条〖即第十四条〗和第十五条〖即2/15〗"


def test_unresolved_not_rendered():
    text = "依照前款规定"
    anns = [Annotation(span_end=4, gloss="即...", render=False)]  # UNRESOLVED → 不渲染
    assert render_window(text, anns) == text


def test_gloss_truncated_to_30():
    out = render_window("见第一条", [Annotation(span_end=4, gloss="x" * 50)])
    assert "〖" + "x" * 30 + "〗" in out
    assert "x" * 31 not in out
