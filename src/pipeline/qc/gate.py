"""QC gate:跑全部七指标 → QcReport(任一不达标即 failed;任一落边缘带即 marginal)。"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.config import QcThresholds
from pipeline.ir import IRDocument
from pipeline.qc.indicators import ALL_INDICATORS, IndicatorResult


@dataclass
class QcReport:
    indicators: list[IndicatorResult]

    @property
    def failed(self) -> bool:
        return any(not i.passed for i in self.indicators)

    @property
    def marginal(self) -> bool:
        return any(i.marginal for i in self.indicators)

    def failures(self) -> list[IndicatorResult]:
        return [i for i in self.indicators if not i.passed]

    def to_evidence(self) -> dict:
        return {
            "failed": [
                {"index": i.index, "name": i.name, "value": round(i.value, 4),
                 "threshold": i.threshold, "evidence": i.evidence}
                for i in self.failures()
            ],
            "marginal": [i.name for i in self.indicators if i.marginal],
        }


def evaluate(ir: IRDocument, thresholds: QcThresholds) -> QcReport:
    return QcReport([fn(ir, thresholds) for fn in ALL_INDICATORS])
