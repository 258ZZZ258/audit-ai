from pipeline.config import load_config
from pipeline.index.object_store import ObjectStore
from pipeline.ir import Block, BlockType, IRDocument, SourceFormat


def test_key_layout():
    assert ObjectStore.raw_key("P-EXT", "batch01", "DV1", "pdf") == "raw/P-EXT/batch01/DV1.pdf"
    assert ObjectStore.raw_key("P-INT", "b", "DV2", ".docx") == "raw/P-INT/b/DV2.docx"
    assert ObjectStore.rendition_key("DV1") == "rendition/DV1.pdf"
    assert ObjectStore.ir_key("DV1") == "ir/DV1.json"


def test_put_get_raw(tmp_path):
    store = ObjectStore(tmp_path)
    key = store.put_raw("P-EXT", "batch01", "DV1", "pdf", b"%PDF-1.7 ...")
    assert key == "raw/P-EXT/batch01/DV1.pdf"
    assert store.exists(key)
    assert store.get(key) == b"%PDF-1.7 ..."
    # 落盘路径符合布局
    assert (tmp_path / "raw" / "P-EXT" / "batch01" / "DV1.pdf").is_file()


def test_raw_is_write_once(tmp_path):
    store = ObjectStore(tmp_path)
    store.put_raw("P-EXT", "batch01", "DV1", "pdf", b"first")
    # 第二次写不同内容 → 不覆盖,保留首次(原件留证 + reprocess 幂等)
    key = store.put_raw("P-EXT", "batch01", "DV1", "pdf", b"SECOND")
    assert store.get(key) == b"first"


def test_rendition_write_once_and_exists(tmp_path):
    store = ObjectStore(tmp_path)
    assert not store.exists_rendition("DV1")
    store.put_rendition("DV1", b"render-v1")
    assert store.exists_rendition("DV1")
    store.put_rendition("DV1", b"render-v2")  # 写一次:不覆盖
    assert store.get_rendition("DV1") == b"render-v1"


def _ir(dvid: str, text: str) -> IRDocument:
    return IRDocument(
        doc_version_id=dvid,
        source_format=SourceFormat.DOCX,
        blocks=[Block(index=0, type=BlockType.PARAGRAPH, text=text, page=1)],
    )


def test_ir_roundtrip_and_overwritable(tmp_path):
    store = ObjectStore(tmp_path)
    store.put_ir(_ir("DV1", "第一条 原始"))
    assert store.load_ir("DV1").blocks[0].text == "第一条 原始"
    # IR 可重写(人工 fix 后重入)
    store.put_ir(_ir("DV1", "第一条 已修复"))
    restored = store.load_ir("DV1")
    assert restored.blocks[0].text == "第一条 已修复"
    assert restored == _ir("DV1", "第一条 已修复")


def test_from_config(tmp_path):
    from pathlib import Path

    cfg = load_config()
    store = ObjectStore.from_config(cfg)
    assert store.root == Path(cfg.object_store.root)
