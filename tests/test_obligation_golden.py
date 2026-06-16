"""B1 · E1 义务 golden set(V8):`match_obligation` 在**人工标注真值**上 precision/recall ≥ 阈值。

真值由人工据语义独立判定(`obligation_truth.json`),**非 matcher 输出**(避免自证)。**免栈免模型**:
纯正则评测。门 = `config.obligation.accuracy_threshold`(默认 0.90);precision 与 recall 各须达标
(双门:recall 防「少标保精度」刷分,precision 防滥标)。
"""

import json
import pathlib

from pipeline.config import load_config
from pipeline.enrich.e1_obligation import match_obligation

_GOLDEN = pathlib.Path(__file__).parent / "golden" / "obligation" / "obligation_truth.json"


def _items() -> list[dict]:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))["items"]


def test_golden_is_balanced():
    items = _items()
    pos = sum(1 for it in items if it["is_obligation"])
    neg = len(items) - pos
    assert pos >= 20 and neg >= 10, f"标注集需 ≥20 正 + ≥10 负(实 正{pos}/负{neg})"


def test_golden_precision_recall():
    cfg = load_config().obligation
    items = _items()
    tp = fp = fn = 0
    wrong: list[tuple[str, str]] = []
    for it in items:
        pred = match_obligation(it["text"], cfg)[0]
        truth = it["is_obligation"]
        if pred and truth:
            tp += 1
        elif pred and not truth:
            fp += 1
            wrong.append(("FP", it["text"]))
        elif not pred and truth:
            fn += 1
            wrong.append(("FN", it["text"]))
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    thr = cfg.accuracy_threshold
    assert precision >= thr and recall >= thr, (
        f"V8 未达:precision={precision:.3f} recall={recall:.3f} < {thr}\n误判:{wrong}"
    )
