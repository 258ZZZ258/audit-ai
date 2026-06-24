"""R6-T4(集成):PG-only 合成 cases → 聚合/列表 SQL 正确(真 PG ``func.extract('year')``)。

gate = **PG**(无模型、无 Milvus)。合成案例用**哨兵未来年(2098/2099)+ 唯一名**,经年过滤与全表其它
cases 隔离 → 计数/排序确定。按 FK 序建(batch→document→doc_version→case)、反序清。
**可见性**:可见案例 = INDEXED + effective;另插 META_REVIEW/superseded/upcoming 不可见哨兵验证排除。
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import delete, select, text
from ulid import ULID

from common.pg_models import Case, Document, DocVersion, ImportBatch
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO
from query.stats.r6_stats import answer_stats

# 可见案例(INDEXED+effective):(violation_category, penalty_org, respondent_type, date, amount_wan)
_ROWS = [
    ("R6招揽", "R6京局", "机构", date(2099, 3, 1), 50.0),
    ("R6招揽", "R6京局", "个人", date(2099, 5, 1), 10.0),
    ("R6内幕", "R6沪局", "个人", date(2098, 8, 1), 120.0),
    (None, "R6深局", "机构", date(2099, 1, 1), 30.0),   # violation_category NULL(L2 默认空)
]
# 不可见哨兵(同类目/年但未上线/旧版/未审):不应计入。(pipeline_status, version_status)
_SENTINELS = [
    ("META_REVIEW", "effective"),   # 未 INDEXED
    ("INDEXED", "superseded"),       # 旧版
    ("INDEXED", "upcoming"),         # 未上线
]


def _add_case(s, bid, i, cat, org, rtype, pdate, amt, pstatus, vstatus):
    lid, dvid = str(ULID()), str(ULID())
    s.add(Document(logical_id=lid, corpus_type="P-CASE", title=f"R6案{i}"))
    s.flush()
    s.add(DocVersion(
        doc_version_id=dvid, logical_id=lid, batch_id=bid,
        source_format="pdf", source_hash=str(ULID()), raw_object_key="x",
        title=f"R6案{i}决定书", pipeline_status=pstatus, version_status=vstatus,
    ))
    s.flush()
    s.add(Case(
        doc_version_id=dvid, penalty_org=org, respondent_type=rtype,
        penalty_date=pdate, amount_wan=amt, violation_category=cat,
    ))


@pytest.fixture(scope="module")
def stats_cases():
    pg = PgIO.from_config(load_config())
    try:
        with pg.session() as s:
            s.execute(text("select 1"))
    except Exception:
        pytest.skip("PG 不可达(demo up 未起)")
    bid = str(ULID())
    with pg.session() as s:
        s.add(ImportBatch(batch_id=bid))
        s.flush()
        for i, (cat, org, rtype, pdate, amt) in enumerate(_ROWS):
            _add_case(s, bid, i, cat, org, rtype, pdate, amt, "INDEXED", "effective")
        for j, (ps, vs) in enumerate(_SENTINELS):  # 同 R6招揽/2099,但不可见
            _add_case(s, bid, 100 + j, "R6招揽", "R6京局", "机构", date(2099, 6, 1), 5.0, ps, vs)
    yield pg, bid

    with pg.session() as s:
        dvids = list(s.scalars(select(DocVersion.doc_version_id).where(DocVersion.batch_id == bid)))
        lids = list(s.scalars(select(DocVersion.logical_id).where(DocVersion.batch_id == bid)))
        s.execute(delete(Case).where(Case.doc_version_id.in_(dvids)))
        s.execute(delete(DocVersion).where(DocVersion.batch_id == bid))
        s.execute(delete(Document).where(Document.logical_id.in_(lids)))
        s.execute(delete(ImportBatch).where(ImportBatch.batch_id == bid))


def _content(res):
    return json.loads(res.answer_blocks[0].content)


def _dvids(pg, bid):
    with pg.session() as s:
        return set(s.scalars(select(DocVersion.doc_version_id).where(DocVersion.batch_id == bid)))


def test_aggregate_count_by_category(stats_cases):
    pg, _bid = stats_cases
    d = _content(answer_stats("2098年以来哪些板块处罚高发", pg))
    m = {r[0]: r[1] for r in d["rows"]}
    assert m["R6招揽"] == 2 and m["R6内幕"] == 1
    assert "未标注" in d["note"]                       # NULL 桶(L2 空)→ consumed-when-present 明示
    assert d["rows"][0][1] >= d["rows"][-1][1]         # 降序


def test_aggregate_by_org_count(stats_cases):
    pg, _bid = stats_cases
    m = {r[0]: r[1] for r in _content(answer_stats("2098年以来各机构处罚排名", pg))["rows"]}
    assert m["R6京局"] == 2 and m["R6沪局"] == 1 and m["R6深局"] == 1


def test_sum_amount_by_org_desc(stats_cases):
    pg, _bid = stats_cases
    d = _content(answer_stats("2098年以来各机构罚没金额排名", pg))
    assert d["columns"][1] == "罚没金额(万元)"
    m = {r[0]: r[1] for r in d["rows"]}
    assert m["R6沪局"] == 120.0 and m["R6京局"] == 60.0   # 50+10


def test_aggregate_by_year_int_serializable(stats_cases):
    # 逐年聚合:PG EXTRACT 返 Decimal,须 cast→int 否则 json.dumps 抛 TypeError(Codex R6-YEAR)
    pg, _bid = stats_cases
    m = {r[0]: r[1] for r in _content(answer_stats("2098年以来逐年处罚数量分布", pg))["rows"]}
    assert m[2099] == 3 and m[2098] == 1                # 2099:招揽×2+NULL;2098:内幕
    assert all(isinstance(k, int) for k in m)           # 年份为 int(非 Decimal)


def test_year_eq_excludes_other_year(stats_cases):
    pg, _bid = stats_cases
    m = {r[0]: r[1] for r in _content(answer_stats("2099年哪些板块处罚高发", pg))["rows"]}
    assert m["R6招揽"] == 2 and "R6内幕" not in m         # 2098 内幕被年过滤排除


def test_visibility_excludes_non_indexed_or_noneffective(stats_cases):
    # 3 个不可见哨兵(META_REVIEW/superseded/upcoming,均 R6招揽/2099)不计入(Codex R6-VISIBILITY)
    pg, _bid = stats_cases
    m = {r[0]: r[1] for r in _content(answer_stats("2098年以来哪些板块处罚高发", pg))["rows"]}
    assert m["R6招揽"] == 2     # 仅 2 个可见;若漏可见性过滤会变 5


def test_list_mode_date_desc(stats_cases):
    pg, bid = stats_cases
    mine_ids = _dvids(pg, bid)
    d = _content(answer_stats("2098年以来的处罚有哪些", pg))
    assert d["columns"][0] == "文书ID" and "标题" in d["columns"]
    mine = [r for r in d["rows"] if r[0] in mine_ids]
    assert len(mine) == 4                                # 仅 4 可见(哨兵不入列表)
    dates = [r[3] for r in mine]
    assert dates == sorted(dates, reverse=True)          # 按日期降序
