"""PG 权威库的 SQLAlchemy 2.0 模型(建表子集,字段名对齐生产 §10)。

原则:
- **add-only**:字段/类型/枚举只增不改;枚举以 String 存储(应用层用 states 枚举约束),
  避免 PG 原生 ENUM 的 ALTER 痛点。
- 全表带 created_at/by、updated_at/by(AuditMixin)。
- chunks 含 ``dense_vec_cold``/``sparse_vec_cold`` bytea 冷备列(服务 rebuild,⚠)。
- 未建表(cases / clause_references / quality_tickets / doc_graph_stats / obligation_keywords)
  以文件末尾注释保留,后续 add-only 迁移加入。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AuditMixin:
    """统一审计列。所有表带 created/updated 时间与操作者。"""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(64), default="system")


class ImportBatch(AuditMixin, Base):
    __tablename__ = "import_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_dir: Mapped[str | None] = mapped_column(String(512))
    manifest_path: Mapped[str | None] = mapped_column(String(512))
    report: Mapped[dict | None] = mapped_column(JSONB)  # demo report 输出快照


class Document(AuditMixin, Base):
    """逻辑文档(跨版本身份)。"""

    __tablename__ = "documents"

    logical_id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    corpus_type: Mapped[str] = mapped_column(String(16))  # P-INT | P-EXT
    title: Mapped[str | None] = mapped_column(String(512))


class DocVersion(AuditMixin, Base):
    """文档的一个具体版本(摄取/解析/索引的主体)。"""

    __tablename__ = "doc_versions"

    doc_version_id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    logical_id: Mapped[str] = mapped_column(ForeignKey("documents.logical_id"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.batch_id"), index=True)

    source_format: Mapped[str] = mapped_column(String(8))  # docx | pdf
    source_hash: Mapped[str] = mapped_column(String(64), index=True)  # SHA-256 精确去重
    raw_object_key: Mapped[str] = mapped_column(String(512))
    rendition_object_key: Mapped[str | None] = mapped_column(String(512))  # 规范渲染件
    ir_object_key: Mapped[str | None] = mapped_column(String(512))

    pipeline_status: Mapped[str] = mapped_column(String(32), index=True, default="REGISTERED")
    # version_status: effective | superseded(版本链原子切换标量)
    version_status: Mapped[str] = mapped_column(String(16), default="effective")

    perm_tag: Mapped[str | None] = mapped_column(String(32))  # 密级:全链路写入,M1 不过滤
    biz_domain: Mapped[str | None] = mapped_column(String(64))
    issuer: Mapped[str | None] = mapped_column(String(128))
    doc_number: Mapped[str | None] = mapped_column(String(128))  # 发文字号
    issue_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str | None] = mapped_column(String(512))

    version_relation: Mapped[str | None] = mapped_column(String(32))  # revise_replace|abolish_only
    supersedes_version_id: Mapped[str | None] = mapped_column(String(26), index=True)  # 应用层引用
    qc_marginal: Mapped[bool] = mapped_column(Boolean, default=False)
    last_error_code: Mapped[str | None] = mapped_column(String(16))


class Chunk(AuditMixin, Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(24), primary_key=True)  # sha1(...)[:24]
    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id"), index=True
    )
    clause_path: Mapped[str | None] = mapped_column(String(512))
    clause_path_norm: Mapped[str | None] = mapped_column(String(512))
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    breadcrumb: Mapped[str | None] = mapped_column(String(512))  # 面包屑前缀
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    is_parent: Mapped[bool] = mapped_column(Boolean, default=False)  # 父块(节级)仅 PG
    is_table: Mapped[bool] = mapped_column(Boolean, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    # chunk_status: staging | effective | superseded(staging 对检索不可见)
    chunk_status: Mapped[str] = mapped_column(String(16), default="staging")
    dense_vec_cold: Mapped[bytes | None] = mapped_column(BYTEA)  # ⚠ 冷备(rebuild)
    sparse_vec_cold: Mapped[bytes | None] = mapped_column(BYTEA)  # ⚠ 冷备(rebuild)


class PipelineEvent(AuditMixin, Base):
    """状态迁移全量留痕(append-only)。"""

    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id"), index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(64), default="system")  # system | CLI 用户名
    detail: Mapped[dict | None] = mapped_column(JSONB)


class ReviewQueue(AuditMixin, Base):
    """统一审核队列(生产统一工作台的领域模型种子)。"""

    __tablename__ = "review_queue"

    queue_id: Mapped[str] = mapped_column(String(26), primary_key=True)  # ULID
    # queue_type: qc_fix | quarantine | meta_confirm
    queue_type: Mapped[str] = mapped_column(String(16), index=True)
    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id"), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSONB)  # 失败指标 + 定位证据
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open|closed
    # disposition: fix | degrade | reject | release | approve
    disposition: Mapped[str | None] = mapped_column(String(16))
    operator: Mapped[str | None] = mapped_column(String(64))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RemediationRecord(AuditMixin, Base):
    __tablename__ = "remediation_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id"), index=True
    )
    queue_id: Mapped[str | None] = mapped_column(ForeignKey("review_queue.queue_id"))
    disposition: Mapped[str] = mapped_column(String(16))  # fix|degrade|reject|release|approve
    operator: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[str | None] = mapped_column(String(32))
    after_state: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSONB)


class RevisionNote(AuditMixin, Base):
    """修订说明:M1 简化为全文 + 人工录入条目(JSON)。"""

    __tablename__ = "revision_notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id"), index=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    entries: Mapped[dict | None] = mapped_column(JSONB)


class ClauseTag(AuditMixin, Base):
    """E1 义务预打标(正则,零 LLM)。"""

    __tablename__ = "clause_tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.chunk_id"), index=True)
    tag_type: Mapped[str] = mapped_column(String(32))  # e.g. is_obligation
    tag_value: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[str | None] = mapped_column(String(256))  # 命中关键词


class DictIssuer(AuditMixin, Base):
    __tablename__ = "dict_issuers"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    issuer_level: Mapped[str | None] = mapped_column(String(32))


class DictBizDomain(AuditMixin, Base):
    __tablename__ = "dict_biz_domains"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    parent_code: Mapped[str | None] = mapped_column(String(64))


# ── 未建表(add-only 保留,后续触发式建设;见 SPEC §5 / V0.1 §1.3)──────────────
# cases            : P-CASE 要素抽取表(W3 前)
# clause_references : ref_resolver 解析后的条款引用(图谱 POC 启动时)
# quality_tickets  : 质量工单(试运行前)
# doc_graph_stats  : 图谱探针统计(E3)
# obligation_keywords : E1 词典表(随比对智能体建设;M1 用内置正则 + 配置词表)
