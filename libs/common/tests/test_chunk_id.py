import hashlib

from common.chunk_id import compute_chunk_id
from common.ir import Block, BlockType, IRDocument, SourceFormat
from pipeline.chunking.chunker import build_chunks
from pipeline.config import ChunkConfig

CFG = ChunkConfig(target_token_min=1, target_token_max=8, parent_block_token_max=20)


def _doc(dvid: str = "DV1") -> IRDocument:
    P = BlockType.PARAGRAPH
    return IRDocument(
        doc_version_id=dvid,
        source_format=SourceFormat.DOCX,
        blocks=[
            Block(index=0, type=P, text="第一章 总则", page=1),
            Block(index=1, type=P, text="第一条 当事人应当遵守本办法规定并配合检查。", page=1),
            Block(index=2, type=P, text="第二条 略。", page=1),
        ],
    )


def test_chunk_id_exact_formula():
    cid = compute_chunk_id("DV1", "2/1/10", 3)
    assert cid == hashlib.sha1(b"DV1|2/1/10|3").hexdigest()[:24]
    assert len(cid) == 24


def test_seq_changes_id():
    assert compute_chunk_id("DV", "p", 0) != compute_chunk_id("DV", "p", 1)


def test_path_changes_id():
    assert compute_chunk_id("DV", "1/1/1", 0) != compute_chunk_id("DV", "1/1/2", 0)


def test_dvid_changes_id():
    assert compute_chunk_id("DVa", "p", 0) != compute_chunk_id("DVb", "p", 0)


def test_build_chunks_deterministic():
    a = [c.chunk_id for c in build_chunks(_doc(), CFG)]
    b = [c.chunk_id for c in build_chunks(_doc(), CFG)]
    assert a == b  # 同输入两次同输出(V5)
    assert len(set(a)) == len(a)  # 无重复 chunk_id


def test_chunk_id_matches_clause_path_and_seq():
    chunks = build_chunks(_doc(), CFG)
    for c in chunks:
        assert c.chunk_id == compute_chunk_id(c.doc_version_id, c.clause_path_norm, c.seq)
