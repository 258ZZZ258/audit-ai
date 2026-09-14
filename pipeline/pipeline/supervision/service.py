"""读取现有已入库文档版本，为监督报告提供元数据、完整证据和字段候选。"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from common.ir import IRDocument
from common.pg_models import Chunk, DocVersion
from common.supervision import SupervisionExtractRequest
from pipeline.config import DEFAULT_CONFIG_DIR, load_config
from pipeline.index.object_store import ObjectStore
from pipeline.index.pg_io import PgIO
from pipeline.supervision.cache import ResultCache
from pipeline.supervision.extract import JsonExtractor, prepare_extraction
from pipeline.supervision.prompting import load_prompt


class SupervisionNotReady(ValueError):
    """文档版本、IR 或索引尚不允许分析。"""


class SupervisionVersionNotFound(LookupError):
    """请求的文档版本不存在，与模型内部 KeyError 区分。"""


class SupervisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["none", "gateway"]
    max_evidence_chars: int = Field(gt=0)
    model_timeout_seconds: float = Field(default=300, gt=0, le=900)
    model_attempts: int = Field(default=2, ge=1, le=3)
    cache_entries: int = Field(default=32, ge=0, le=1024)
    cache_ttl_seconds: int = Field(default=900, ge=0, le=86400)
    embedding_cache_entries: int = Field(default=4096, ge=0, le=65536)
    coverage_review: bool = False


class SupervisionService:
    def __init__(
        self, pg, store: ObjectStore, config: SupervisionConfig, client: JsonExtractor | None = None
    ):
        self.pg = pg
        self.store = store
        self.config = config
        self.client = client
        self._cache = ResultCache(config.cache_entries, config.cache_ttl_seconds)

    @classmethod
    def from_config(cls):
        settings = load_config()
        config_path = Path(
            os.environ.get(
                "SUPERVISION_CONFIG",
                str(DEFAULT_CONFIG_DIR / "supervision.toml"),
            )
        )
        config = SupervisionConfig.model_validate(tomllib.loads(config_path.read_text("utf-8")))
        # 默认 none 不读模型密钥也不构造 client。部署启用后沿用现有网关环境变量。
        client = None
        if config.backend == "gateway":
            from pipeline.llm_client import make_llm_client

            client = make_llm_client(timeout=config.model_timeout_seconds, retries=1)
        return cls(PgIO.from_config(settings), ObjectStore.from_config(settings), config, client)

    def _read_version(self, request: SupervisionExtractRequest):
        meta = request.metadata
        with self.pg.session() as session:
            dv = session.get(DocVersion, meta.documentVersionId)
            if dv is None:
                raise SupervisionVersionNotFound(meta.documentVersionId)
            if dv.logical_id != meta.documentId:
                raise SupervisionNotReady("Document/version identity mismatch")
            if dv.pipeline_status != "INDEXED" or dv.version_status != "effective" or dv.degraded:
                raise SupervisionNotReady("Document version is not effective and indexed")
            if not dv.ir_object_key:
                raise SupervisionNotReady("Indexed document has no IR")
            chunks = list(
                session.scalars(
                    select(Chunk)
                    .where(
                        Chunk.doc_version_id == meta.documentVersionId,
                    )
                    .order_by(Chunk.seq, Chunk.chunk_id)
                )
            )
            if not chunks or any(c.chunk_status != "effective" or c.degraded for c in chunks):
                raise SupervisionNotReady("Document index is incomplete or degraded")
            index_payload = [
                [c.chunk_id, c.text, c.page_start, c.page_end, c.chunk_status] for c in chunks
            ]
            ir_key = dv.ir_object_key
        # 从权威版本记录取 key；不接受调用方任意文件路径。
        ir = IRDocument.model_validate_json(self.store.get(ir_key))
        if ir.doc_version_id != meta.documentVersionId:
            raise SupervisionNotReady("Stored IR version mismatch")
        return ir, index_payload

    def extract(self, request: SupervisionExtractRequest) -> dict:
        meta = request.metadata
        ir, index_payload = self._read_version(request)
        if self.config.backend == "gateway" and self.client is None:
            raise RuntimeError("Configured supervision extractor is unavailable")
        cache_key = hashlib.sha256(json.dumps([
            request.model_dump(mode="json"), ir.model_dump(mode="json"), index_payload,
            self.config.model_dump(), id(self.client), getattr(self.client, "model", None),
            load_prompt("extraction-prompt.txt"),
            load_prompt("coverage-prompt.txt"),
            Path(__file__).with_name("citation-repair-prompt.txt").read_text("utf-8"),
        ], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        output = self._cache.compute(cache_key, lambda: prepare_extraction(
            request,
            ir,
            client=self.client if self.config.backend == "gateway" else None,
            max_evidence_chars=self.config.max_evidence_chars,
            model_attempts=self.config.model_attempts,
            coverage_review=self.config.coverage_review,
        ))
        # 长模型调用期间可能发生重新解析/替代；返回前复验，不给旧内容贴新快照。
        current_ir, current_index = self._read_version(request)
        if current_ir != ir or current_index != index_payload:
            raise SupervisionNotReady("Document content changed during extraction; retry")
        # 内容指纹作为本次解析/索引快照标识，绝不伪装为新建的数据库版本列。
        parse_hash = hashlib.sha256(ir.model_dump_json().encode()).hexdigest()
        index_hash = hashlib.sha256(
            json.dumps(index_payload, ensure_ascii=False).encode()
        ).hexdigest()
        output["uploadedMaterial"] = {
            **meta.model_dump(exclude_none=True),
            "title": (meta.title or "").strip() or meta.fileName,
            "organizationIds": list(dict.fromkeys(meta.organizationIds)),
            "processingStatus": "indexed",
            "parseVersion": f"ir-sha256:{parse_hash}",
            "indexVersion": f"chunks-sha256:{index_hash}",
        }
        return output
