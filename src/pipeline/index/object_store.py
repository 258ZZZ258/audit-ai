"""ObjectStore:本地文件系统实现,key 布局对齐 MinIO(生产期换 MinIO adapter 路径不变)。

key 布局:
- ``raw/{corpus_type}/{batch_id}/{doc_version_id}.{ext}`` —— 原件,**写一次**(原件留证)
- ``rendition/{doc_version_id}.pdf``                       —— 规范渲染件,**写一次**(reprocess 复用)
- ``ir/{doc_version_id}.json``                             —— IR,可重写(fix/reprocess)

写一次语义:put 时若 key 已存在则**不覆盖**、复用既有(使重复 ingest / reprocess 幂等安全)。
"""

from __future__ import annotations

from pathlib import Path

from pipeline.config import Settings
from pipeline.ir import IRDocument


class ObjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @classmethod
    def from_config(cls, settings: Settings) -> ObjectStore:
        return cls(settings.object_store.root)

    # ── key 布局 ──────────────────────────────────────────────
    @staticmethod
    def raw_key(corpus_type: str, batch_id: str, doc_version_id: str, ext: str) -> str:
        return f"raw/{corpus_type}/{batch_id}/{doc_version_id}.{ext.lstrip('.')}"

    @staticmethod
    def rendition_key(doc_version_id: str) -> str:
        return f"rendition/{doc_version_id}.pdf"

    @staticmethod
    def ir_key(doc_version_id: str) -> str:
        return f"ir/{doc_version_id}.json"

    # ── 通用 ──────────────────────────────────────────────────
    def _path(self, key: str) -> Path:
        return self.root / key

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def _write(self, key: str, data: bytes, *, write_once: bool) -> str:
        p = self._path(key)
        if write_once and p.exists():
            return key  # 写一次:不覆盖,复用既有
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    # ── 三类产物 ──────────────────────────────────────────────
    def put_raw(
        self, corpus_type: str, batch_id: str, doc_version_id: str, ext: str, data: bytes
    ) -> str:
        return self._write(
            self.raw_key(corpus_type, batch_id, doc_version_id, ext), data, write_once=True
        )

    def put_rendition(self, doc_version_id: str, data: bytes) -> str:
        return self._write(self.rendition_key(doc_version_id), data, write_once=True)

    def exists_rendition(self, doc_version_id: str) -> bool:
        return self.exists(self.rendition_key(doc_version_id))

    def get_rendition(self, doc_version_id: str) -> bytes:
        return self.get(self.rendition_key(doc_version_id))

    def put_ir(self, ir: IRDocument) -> str:
        # IR 可重写(人工 fix 编辑 / reprocess 重解析)
        return self._write(
            self.ir_key(ir.doc_version_id), ir.model_dump_json().encode("utf-8"), write_once=False
        )

    def load_ir(self, doc_version_id: str) -> IRDocument:
        return IRDocument.model_validate_json(self.get(self.ir_key(doc_version_id)).decode("utf-8"))
