from pipeline.stage_base import QueueItem, QueueType, StageResult
from pipeline.states import (
    ALLOWED_TRANSITIONS,
    HUMAN_WAIT_STATES,
    TERMINAL_STATES,
    WORKER_ADVANCEABLE_STATES,
    ErrorCode,
    PipelineState,
    can_transition,
)

PS = PipelineState


def test_no_reparse_states():
    # demo 子集明确去掉 REPARSE 系
    assert not any("REPARSE" in m.name for m in PipelineState)


def test_happy_path_transitions_allowed():
    chain = [
        PS.REGISTERED,
        PS.PARSING,
        PS.QC_PENDING,
        PS.STRUCTURING,
        PS.META_REVIEW,
        PS.EMBEDDING,
        PS.INDEXING,
        PS.INDEXED,
    ]
    for frm, to in zip(chain, chain[1:], strict=False):
        assert can_transition(frm, to), f"{frm}->{to} 应允许"


def test_remediation_transitions():
    assert can_transition(PS.QC_FAILED, PS.QC_PENDING)  # fix 重入
    assert can_transition(PS.QC_FAILED, PS.DEGRADED_INDEXED)  # degrade
    assert can_transition(PS.QC_FAILED, PS.REJECTED)  # reject
    assert can_transition(PS.QUARANTINED, PS.PARSING)  # release 重入
    assert can_transition(PS.PARSE_FAILED, PS.QC_PENDING)  # 补 IR 重入


def test_illegal_transitions_rejected():
    assert not can_transition(PS.REGISTERED, PS.INDEXED)  # 不能跳级
    assert not can_transition(PS.QC_PENDING, PS.INDEXED)
    assert not can_transition(PS.META_REVIEW, PS.INDEXED)
    assert not can_transition(PS.INDEXED, PS.PARSING)
    assert not can_transition(PS.QC_FAILED, PS.STRUCTURING)


def test_reprocess_reset():
    # 终态/失败/隔离可被 reprocess 重置回 REGISTERED
    for s in (PS.INDEXED, PS.DEGRADED_INDEXED, PS.REJECTED, PS.QC_FAILED, PS.QUARANTINED):
        assert can_transition(s, PS.REGISTERED), f"{s} 应可 reprocess 重置"
    # 但非重置状态不可凭空回 REGISTERED
    assert not can_transition(PS.QC_PENDING, PS.REGISTERED)
    # reprocess 不等于可乱跳到任意状态
    assert not can_transition(PS.INDEXED, PS.EMBEDDING)


def test_state_sets_partition_all():
    sets = [TERMINAL_STATES, HUMAN_WAIT_STATES, WORKER_ADVANCEABLE_STATES]
    union = TERMINAL_STATES | HUMAN_WAIT_STATES | WORKER_ADVANCEABLE_STATES
    assert union == set(PipelineState)  # 覆盖全部成员
    # 两两不相交
    for i, a in enumerate(sets):
        for b in sets[i + 1 :]:
            assert not (a & b)


def test_human_wait_not_worker_advanceable():
    assert PS.META_REVIEW in HUMAN_WAIT_STATES
    assert PS.QC_FAILED in HUMAN_WAIT_STATES
    assert PS.QC_PENDING in WORKER_ADVANCEABLE_STATES
    assert PS.INDEXED in TERMINAL_STATES


def test_allowed_transitions_cover_every_state():
    # 每个状态都在迁移表里有条目(终态映射到空集)
    assert set(ALLOWED_TRANSITIONS) == set(PipelineState)
    for s in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[s] == frozenset()


def test_error_codes():
    assert ErrorCode.FORMAT_NOT_WHITELISTED == "E101-DEMO"
    assert ErrorCode.SCANNED_OCR_DISABLED == "E202-DEMO"
    assert ErrorCode.PARSE_TIMEOUT == "E203"
    assert ErrorCode.RENDITION_FAILED == "E204-DEMO"
    assert ErrorCode.QC_GATE_FAILED == "E301"


def test_stage_result_and_queue_item():
    qi = QueueItem(
        queue_type=QueueType.QC_FIX,
        doc_version_id="d1",
        reason="条号缺口",
        evidence={"indicator": 2, "gap": "第7条后缺第8条", "page": 3},
    )
    res = StageResult(
        next_state=PS.QC_FAILED,
        error_code=ErrorCode.QC_GATE_FAILED,
        evidence=qi.evidence,
        queue=qi,
    )
    assert res.next_state is PS.QC_FAILED
    assert res.queue.queue_type == "qc_fix"
    assert res.artifacts == {}  # 默认空 dict
    assert res.marginal is False
