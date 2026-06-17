"""B1 · mini golden set:条款树结构 **F1 = 1.0**(demo 集必须完美解析;亦为 parser-swap 准入门)。

ground truth = `tests/golden/<doc>.json`(`build_tree` 输出镜像,人工核对正确)。**免模型/免 soffice**:
`build_tree` 只用 docx 解析出的 IR blocks 文本(不需渲染/页码)。fixtures 未构建则 skip。
F1 over 节点身份 (type, clause_path_norm):demo 集要求 = 1.0(候选集 == ground truth)。
"""

import json
import pathlib

import pytest

from pipeline.chunking.clause_tree import build_tree
from pipeline.parsing.light_parser import _docx_blocks

_FIX = pathlib.Path("fixtures/batch01")
_GOLDEN = pathlib.Path(__file__).parent / "golden"
# 覆盖:多级章/节/条 · 章条 · 第X条之一插入条 · 超长条款 · 无章通知(虚拟根)
_DOCS = ["int_hetong", "int_yinzhang", "int_baoxiao", "int_baogao", "int_tongzhi"]


def _node_set(root) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()

    def walk(n) -> None:
        for c in n.children:
            out.add((c.type.value, c.clause_path_norm()))
            walk(c)

    walk(root)
    return out


def _f1(cand: set, exp: set) -> float:
    if not cand and not exp:
        return 1.0
    tp = len(cand & exp)
    p = tp / len(cand) if cand else 0.0
    r = tp / len(exp) if exp else 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


@pytest.mark.parametrize("name", _DOCS)
def test_golden_clause_tree_f1(name):
    docx = _FIX / f"{name}.docx"
    if not docx.exists():
        pytest.skip("fixtures 未构建(build_fixtures.py --all)")
    blocks, _ = _docx_blocks(docx.read_bytes())  # docx→IR blocks(免 soffice)
    cand = _node_set(build_tree(blocks))
    expected = json.loads((_GOLDEN / f"{name}.json").read_text(encoding="utf-8"))
    exp = {(n["type"], n["clause_path_norm"]) for n in expected}
    assert _f1(cand, exp) == 1.0, f"{name}: 多出={cand - exp} 缺失={exp - cand}"
