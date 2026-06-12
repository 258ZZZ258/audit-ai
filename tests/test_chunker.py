from pipeline.chunking.chunker import build_chunks
from pipeline.config import ChunkConfig
from pipeline.ir import Block, BlockType, IRDocument, SourceFormat, Table, TableCell

BIG = ChunkConfig(target_token_min=1, target_token_max=10000, parent_block_token_max=10000)
SMALL = ChunkConfig(target_token_min=1, target_token_max=10, parent_block_token_max=20)


def _table() -> Table:
    return Table(
        n_rows=3,
        n_cols=2,
        header_rows=1,
        cells=[
            TableCell(text="层级", row=0, col=0),
            TableCell(text="权限", row=0, col=1),
            TableCell(text="经理", row=1, col=0),
            TableCell(text="一万以下", row=1, col=1),
            TableCell(text="总监", row=2, col=0),
            TableCell(text="五万以下", row=2, col=1),
        ],
    )


def make_doc() -> IRDocument:
    P = BlockType.PARAGRAPH
    return IRDocument(
        doc_version_id="DVTEST",
        source_format=SourceFormat.DOCX,
        blocks=[
            Block(index=0, type=P, text="第一章 总则", page=1),
            Block(index=1, type=P, text="第一节 一般规定", page=1),
            Block(index=2, type=P, text="第一条 略。", page=1),
            Block(index=3, type=P, text="第二条 报销规定如下。", page=1),
            Block(index=4, type=P, text="甲方应当及时提交单据并经审批流程。", page=1),
            Block(index=5, type=P, text="乙方应当在三个工作日内完成复核。", page=2),
            Block(index=6, type=P, text="第三条 审批权限表见下。", page=2),
            Block(index=7, type=BlockType.TABLE, page=2, table=_table()),
        ],
    )


def _by_norm(chunks, norm):
    return [c for c in chunks if c.clause_path_norm == norm]


def test_short_article_single_chunk_with_breadcrumb():
    c = _by_norm(build_chunks(make_doc(), BIG), "1/1/1")
    assert len(c) == 1
    assert not c[0].is_parent and not c[0].is_table
    assert c[0].breadcrumb == "第一章 > 第一节 > 第一条"
    assert c[0].text.startswith("第一章 > 第一节 > 第一条")  # 规则6 面包屑前缀
    assert "略" in c[0].text


def test_article_page_span():
    art2 = _by_norm(build_chunks(make_doc(), BIG), "1/1/2")
    assert len(art2) == 1  # BIG 不拆
    assert (art2[0].page_start, art2[0].page_end) == (1, 2)  # 规则6 页码跨度(跨页)


def test_section_parent_block_pg_only():
    parents = [c for c in build_chunks(make_doc(), BIG) if c.is_parent]
    assert len(parents) == 1  # 规则4 节级父块
    assert parents[0].clause_path_norm == "1/1"
    assert not parents[0].is_table


def test_table_chunk_independent():
    tbl = [c for c in build_chunks(make_doc(), BIG) if c.is_table]
    assert len(tbl) >= 1  # 规则5 表格独立块
    assert "层级" in tbl[0].text and "经理" in tbl[0].text
    assert all(c.clause_path_norm == "1/1/3" for c in tbl)  # 归属第三条


def test_long_article_splits_with_heading_continuation():
    art2 = _by_norm(build_chunks(make_doc(), SMALL), "1/1/2")
    assert len(art2) >= 2  # 规则2 超长按款拆
    assert [c.seq for c in art2] == list(range(len(art2)))  # seq 连续
    assert any("报销规定如下" in c.text for c in art2[1:])  # 条头续接
    assert len({c.chunk_id for c in art2}) == len(art2)  # 同条各块 id 不同


def test_table_split_repeats_header():
    tbl = [c for c in build_chunks(make_doc(), SMALL) if c.is_table]
    assert len(tbl) >= 2  # 规则5 按行组拆
    assert all("层级" in c.text for c in tbl)  # 每块重复表头


def test_short_articles_not_merged():
    # 规则3:第一条(短)与第二条 各自独立,不合并
    chunks = build_chunks(make_doc(), BIG)
    assert _by_norm(chunks, "1/1/1") and _by_norm(chunks, "1/1/2")


def _tail_doc() -> IRDocument:
    P = BlockType.PARAGRAPH
    return IRDocument(
        doc_version_id="DVMIN",
        source_format=SourceFormat.DOCX,
        blocks=[
            Block(index=0, type=P, text="第一条 正文正文正文", page=1),  # 9 token ≤max
            Block(index=1, type=P, text="补。", page=1),  # 2 token 小尾款
        ],
    )


def test_target_token_min_coalesces_tail():
    # 同一篇文档、同一 max,仅 min 不同:min=1 不合并出碎尾;min=5 把碎尾并回前组
    no_min = ChunkConfig(target_token_min=1, target_token_max=10, parent_block_token_max=50)
    with_min = ChunkConfig(target_token_min=5, target_token_max=10, parent_block_token_max=50)
    a = _by_norm(build_chunks(_tail_doc(), no_min), "1")
    b = _by_norm(build_chunks(_tail_doc(), with_min), "1")
    assert len(a) == 2  # 碎尾"补。"独立成块
    assert len(b) == 1  # 尾块并回 → 单块
    assert "正文" in b[0].text and "补" in b[0].text  # 合并后含两段


def test_single_oversize_paragraph_splits_semantically():
    # 单段超长条(整条一个段落):在 项标记（N）/句末；。 切,内容每块 ≤max,非硬切
    cfg = ChunkConfig(target_token_min=1, target_token_max=12, parent_block_token_max=50)
    doc = IRDocument(
        doc_version_id="DVO",
        source_format=SourceFormat.DOCX,
        blocks=[
            Block(
                index=0,
                type=BlockType.PARAGRAPH,
                text="第二条 应当报告:（一）甲类事项情况；（二）乙类事项情况；（三）丙类事项情况。",
                page=1,
            )
        ],
    )
    chunks = _by_norm(build_chunks(doc, cfg), "2")
    assert len(chunks) >= 2
    assert all(c.token_count <= cfg.target_token_max for c in chunks)  # 内容 ≤max
    assert not any(c.oversize for c in chunks)


def test_oversize_no_boundary_hard_splits_and_marks():
    # 无 项标记/句末 的超长串:字符硬切兜底,内容仍 ≤max 且标 oversize
    cfg = ChunkConfig(target_token_min=1, target_token_max=10, parent_block_token_max=50)
    doc = IRDocument(
        doc_version_id="DVH",
        source_format=SourceFormat.DOCX,
        blocks=[
            Block(
                index=0,
                type=BlockType.PARAGRAPH,
                text="第三条甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥天地玄黄",
                page=1,
            )
        ],
    )
    chunks = _by_norm(build_chunks(doc, cfg), "3")
    assert len(chunks) >= 2
    assert all(c.token_count <= cfg.target_token_max for c in chunks)
    assert any(c.oversize for c in chunks)
