"""T1.2 case_ref_align 纯对齐:案例引用「《X》第N条」→ doc_no/标题 + clause_path_norm。

纯逻辑(无模型/无栈):lookup 注入假实现。三级匹配(文号→标题→[别名留 T2.4]),
条号经 normalize 归一,超界/未命中标 resolved=False(→ ref_unresolved,不阻塞案例入库)。
"""

from pipeline.meta.case_ref_align import RegDoc, align_cited


class _Lookup:
    """假 lookup:按文号 / 标题精确命中(生产用 PG 实现,见 T2.1)。"""

    def __init__(self, by_no=None, by_title=None):
        self._by_no = by_no or {}
        self._by_title = by_title or {}

    def find(self, doc_number, title):
        if doc_number and doc_number in self._by_no:
            return self._by_no[doc_number]
        if title and title in self._by_title:
            return self._by_title[title]
        return None


# 目标外规:含 2/15、2/16(章/条)与插入条 3/21-1
DOC = RegDoc(
    doc_version_id="DV1",
    doc_number="证监会令第131号",
    clause_norms=frozenset({"2/15", "2/16", "3/21-1"}),
)


def test_align_by_doc_number_hits_clause():
    out, unresolved = align_cited(
        [{"doc_number": "证监会令第131号", "clause": "第十五条"}],
        _Lookup(by_no={"证监会令第131号": DOC}),
    )
    assert not unresolved
    assert out[0]["resolved"] and out[0]["clause_path_norm"] == "2/15"


def test_align_by_title_when_no_docnumber():
    out, _ = align_cited(
        [{"title": "证券公司监督管理条例", "clause": "第十六条"}],
        _Lookup(by_title={"证券公司监督管理条例": DOC}),
    )
    assert out[0]["resolved"] and out[0]["clause_path_norm"] == "2/16"


def test_align_insert_article():
    # 「第二十一条之一」→ 归一 21-1 → 命中 3/21-1
    out, _ = align_cited(
        [{"doc_number": "证监会令第131号", "clause": "第二十一条之一"}],
        _Lookup(by_no={"证监会令第131号": DOC}),
    )
    assert out[0]["resolved"] and out[0]["clause_path_norm"] == "3/21-1"


def test_align_strips_kuan_suffix():
    # 「第十五条第二款」→ 取条级 15 → 命中 2/15(反查精度到条)
    out, _ = align_cited(
        [{"doc_number": "证监会令第131号", "clause": "第十五条第二款"}],
        _Lookup(by_no={"证监会令第131号": DOC}),
    )
    assert out[0]["resolved"] and out[0]["clause_path_norm"] == "2/15"


def test_align_out_of_range_unresolved():
    out, unresolved = align_cited(
        [{"doc_number": "证监会令第131号", "clause": "第九十九条"}],
        _Lookup(by_no={"证监会令第131号": DOC}),
    )
    assert unresolved and not out[0]["resolved"] and out[0]["clause_path_norm"] is None


def test_align_doc_not_found_unresolved():
    out, unresolved = align_cited([{"title": "查无此法", "clause": "第一条"}], _Lookup())
    assert unresolved and not out[0]["resolved"]


def test_align_doc_level_when_no_clause():
    out, unresolved = align_cited(
        [{"doc_number": "证监会令第131号"}], _Lookup(by_no={"证监会令第131号": DOC})
    )
    assert not unresolved and out[0]["resolved"] and out[0]["clause_path_norm"] is None
