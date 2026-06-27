"""PG 权威库的 SQLAlchemy 2.0 模型(建表子集,字段名对齐生产 §10)。

原则:
- **add-only**:字段/类型/枚举只增不改;枚举以 String 存储(应用层用 states 枚举约束),
  避免 PG 原生 ENUM 的 ALTER 痛点。
- 全表带 created_at/by、updated_at/by(AuditMixin)。
- chunks 含 ``dense_vec_cold``/``sparse_vec_cold`` bytea 冷备列(服务 rebuild,⚠)。
- 未建表(clause_references / quality_tickets / doc_graph_stats / obligation_keywords)
  以文件末尾注释保留,后续 add-only 迁移加入。``cases`` 已于迁移 0006 建(§9 P-CASE)。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
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
    source_filename: Mapped[str | None] = mapped_column(String(256))  # 原始文件名(替代解析/溯源)

    pipeline_status: Mapped[str] = mapped_column(String(32), index=True, default="REGISTERED")
    # version_status: effective | superseded | abolished | upcoming(版本生命周期标量,§1.1/§7.2)
    version_status: Mapped[str] = mapped_column(String(16), default="effective")

    perm_tag: Mapped[str | None] = mapped_column(String(32))  # 密级:全链路写入,M1 不过滤
    biz_domain: Mapped[str | None] = mapped_column(String(64))  # 原单值(manifest);保留不删
    # 业务域多值(D4,§7.1 L2):LLM 为事实主来源,写权威字段 + 标来源(manifest|llm|confirmed)
    biz_domains: Mapped[list | None] = mapped_column(JSONB)
    biz_domain_source: Mapped[str | None] = mapped_column(String(16))
    sub_type: Mapped[str | None] = mapped_column(String(32))  # 子类型(issuer_level 分层)
    issuer: Mapped[str | None] = mapped_column(String(128))
    doc_number: Mapped[str | None] = mapped_column(String(128))  # 发文字号
    issue_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)  # 生效日期(upcoming 判定 + 时间窗)
    title: Mapped[str | None] = mapped_column(String(512))

    version_relation: Mapped[str | None] = mapped_column(String(32))  # revise_replace|abolish_only
    supersedes_version_id: Mapped[str | None] = mapped_column(String(26), index=True)  # 应用层引用
    qc_marginal: Mapped[bool] = mapped_column(Boolean, default=False)
    # 降级件:走索引但 chunk 标 degraded。server_default 使 add-only 迁移对已有行安全。
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
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
    # chunk_type: clause | table | qa | case_summary | case_section(§8.3;is_table 保留并存)
    chunk_type: Mapped[str | None] = mapped_column(String(16))
    # parent_chunk_id: 子块指向其节级父块(§8.3「小块检索、大块供证」;应用层引用,非 FK)
    parent_chunk_id: Mapped[str | None] = mapped_column(String(24), index=True)
    internal_refs: Mapped[list | None] = mapped_column(JSONB)  # 正文条款引用(§8.3 前置信号)
    embed_status: Mapped[str | None] = mapped_column(String(16))  # pending|done|failed(§8.1)
    entity_type: Mapped[list | None] = mapped_column(JSONB)  # CP-007 实体类型(E2 富集,预留)
    # 单段超长无语义边界被字符硬切(质量信号)。server_default 使 add-only 迁移对已有行安全。
    oversize: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
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
    # ── 类型列(§19.1/§10,CP-007;与上方 k-v 并存,add-only)──
    deontic_type: Mapped[str | None] = mapped_column(String(16))  # 应当/必须/不得/禁止/不予
    norm_duration_days: Mapped[int | None] = mapped_column(Integer)  # 期限归一到日(CP-007)
    surface_duration: Mapped[str | None] = mapped_column(String(64))  # 原文期限表达(standoff)
    is_business_day: Mapped[bool | None] = mapped_column(Boolean)  # 工作日(区别自然日)
    norm_status: Mapped[str | None] = mapped_column(String(16))  # parsed|unparsed
    entity_type: Mapped[list | None] = mapped_column(JSONB)  # CP-007 实体类型(E2 富集,预留)


class ClauseReference(AuditMixin, Base):
    """条款指代/引用 standoff 解析表(V1.6 §6.7,CP-001)。

    ``chunks.text`` 保持逐字原文,引用解析结果存这里(独立表),带注释文本仅 S6 窗口装配时
    临时渲染、不落库。解析的是条文里**字面写出的引用**四类(``ref_type``):R1 文档自指
    (本办法)/ R2 相对条款(前款)/ R3 绝对条款(第十五条)/ R4 跨文档(《证券法》第196条 →
    ``target_doc_version_id``)。**R4 才涉及外规,且仅解析正文已写出的引用——不是"内规覆盖了
    哪条外规义务"的语义映射**(那属功能2 比对智能体「必要性覆盖」)。

    状态:**表结构已建**(供查询侧 R1/R2 多跳确定性拦截开发起步);**填充逻辑 ref_resolver
    尚未实现(§6.7,TODO 先不做)**。建表后 ``chunks.internal_refs[]`` 按 §6.7「保留不删、
    停止新写」。``method`` 恒为 ``rule``——字段预留,禁止未来混入不可区分的 LLM 解析结果。
    """

    __tablename__ = "clause_references"

    ref_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # ON DELETE CASCADE:standoff 附属随 chunk/版本删除自动清(删 chunk 的各路径无需手动清,
    # 与 ref_resolver 填充配套;§6.7)。clause_tags 仍手动删(富集打标,既有模式不动)。
    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("chunks.chunk_id", ondelete="CASCADE"), index=True
    )
    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id", ondelete="CASCADE"), index=True
    )
    span_start: Mapped[int | None] = mapped_column(Integer)  # 引用在 chunks.text 的字符跨度
    span_end: Mapped[int | None] = mapped_column(Integer)
    surface_text: Mapped[str] = mapped_column(String(256))  # 原文引用表面("前款""《证券法》第X条")
    ref_type: Mapped[str] = mapped_column(String(8))  # R1 | R2 | R3 | R4
    # 目标为应用层引用(非 FK):可 pending_target/unresolved,或指向尚未入库的外规
    target_doc_version_id: Mapped[str | None] = mapped_column(String(26), index=True)
    target_clause_path_norm: Mapped[str | None] = mapped_column(String(512))
    # resolution_status: resolved | unresolved | ambiguous | pending_target
    resolution_status: Mapped[str] = mapped_column(String(16), index=True, default="unresolved")
    method: Mapped[str] = mapped_column(String(16), default="rule", server_default="rule")


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


class DictEntityType(AuditMixin, Base):
    """适用实体类型字典(§19.2 / §16-7,CP-007);E2 打标约束空间。dict_version 支持增量重打。"""

    __tablename__ = "dict_entity_types"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    dict_version: Mapped[str | None] = mapped_column(String(32))


class DictDepartment(AuditMixin, Base):
    """责任部门字典(§19.2);E2 打标约束空间。dict_version 支持增量重打。"""

    __tablename__ = "dict_departments"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    dict_version: Mapped[str | None] = mapped_column(String(32))


class DictViolationType(AuditMixin, Base):
    """违规事由分类字典(§9 案例 L2;§16-6 待评审)。v0-draft 从样例聚类;dict_version 增量重打。"""

    __tablename__ = "dict_violation_types"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    dict_version: Mapped[str | None] = mapped_column(String(32))


class DictAlias(AuditMixin, Base):
    """制度简称别名表(§6.7 R4 跨文档指代);别名 → 权威文号。人工维护,带 dict_version。"""

    __tablename__ = "dict_aliases"

    alias: Mapped[str] = mapped_column(String(256), primary_key=True)  # 简称/别名(唯一)
    canonical_doc_number: Mapped[str | None] = mapped_column(String(128))  # 权威文号
    canonical_title: Mapped[str | None] = mapped_column(String(512))  # 权威标题(兜底匹配)
    dict_version: Mapped[str | None] = mapped_column(String(32))


class Case(AuditMixin, Base):
    """P-CASE 案例要素抽取(§9):一案一行,FK → doc_versions。L1 规则 + L2 LLM(默认关)。"""

    __tablename__ = "cases"

    doc_version_id: Mapped[str] = mapped_column(
        ForeignKey("doc_versions.doc_version_id"), primary_key=True
    )
    penalty_org: Mapped[str | None] = mapped_column(String(256))  # 处罚机构
    doc_number: Mapped[str | None] = mapped_column(String(128))  # 处罚决定书文号
    penalty_date: Mapped[date | None] = mapped_column(Date)  # 处罚日期
    respondent: Mapped[str | None] = mapped_column(String(256))  # 处罚对象
    respondent_type: Mapped[str | None] = mapped_column(String(16))  # 机构 | 个人
    violation_category: Mapped[str | None] = mapped_column(String(64))  # 违规事由分类(L2)
    cited_regulations: Mapped[list | None] = mapped_column(JSONB)  # 引用外规条款(归一对齐)
    penalty_type: Mapped[str | None] = mapped_column(String(64))  # 处罚类型
    amount_wan: Mapped[float | None] = mapped_column(Float)  # 金额(万元)
    # 引用对齐失败 → 低优先人工队列,不阻塞案例入库(§9)
    ref_unresolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


# ── 未建表(add-only 保留,后续触发式建设;见 SPEC §5 / V0.1 §1.3)──────────────
# 注:clause_references 表结构已建(见上 ClauseReference);但其填充逻辑 ref_resolver
#     尚未实现(§6.7,TODO 先不做)——表已就位,resolver 落地时按 §6.7 R1–R4 补写。
# quality_tickets  : 质量工单(试运行前)
# doc_graph_stats  : 图谱探针统计(E3)
# obligation_keywords : E1 词典表(随比对智能体建设;M1 用内置正则 + 配置词表)
