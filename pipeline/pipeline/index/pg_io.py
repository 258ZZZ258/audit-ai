"""PG 权威库的基础读写层。

提供:session 上下文、原子状态迁移(更新 pipeline_status + 写 pipeline_events,带 can_transition
守卫)、chunk 批量读写、字典 seed 导入。供 orchestrator 与各 stage 使用——
**状态迁移与 events 只经此层落库**(SPEC 边界)。
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from common.pg_models import (
    Case,
    Chunk,
    DictBizDomain,
    DictDepartment,
    DictEntityType,
    DictIssuer,
    DocVersion,
    PipelineEvent,
    ReviewQueue,
)
from pipeline.config import Settings
from pipeline.states import PipelineState, can_transition


class PgIO:
    def __init__(self, dsn: str) -> None:
        self.engine = create_engine(dsn)
        # expire_on_commit=False:commit 后对象仍可读列(脱离 session 使用)
        self._Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    @classmethod
    def from_config(cls, settings: Settings) -> PgIO:
        return cls(settings.db.dsn)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """事务性 session:正常 commit,异常 rollback,结束 close。"""
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ── 通用 ──────────────────────────────────────────────────
    def add(self, obj: Any) -> Any:
        with self.session() as s:
            s.add(obj)
        return obj

    def get(self, model: type, pk: Any) -> Any:
        with self.session() as s:
            return s.get(model, pk)

    # ── 状态机 ────────────────────────────────────────────────
    def docs_in_states(self, states: Iterable[PipelineState | str]) -> list[DocVersion]:
        vals = [s.value if isinstance(s, PipelineState) else s for s in states]
        with self.session() as s:
            return list(s.scalars(select(DocVersion).where(DocVersion.pipeline_status.in_(vals))))

    def transition(
        self,
        doc_version_id: str,
        to_state: PipelineState | str,
        *,
        actor: str = "system",
        error_code: str | None = None,
        detail: dict | None = None,
        queue_row: ReviewQueue | None = None,
        session: Session | None = None,
    ) -> None:
        """原子迁移:校验合法性 → 更新 pipeline_status → 写 pipeline_events(可选同事务入队)。

        ``queue_row`` 非空时与迁移共用同一事务:守卫失败(非法迁移)或任何 DB 错误都会
        一并回滚,不会遗留"有 open 队列项却没进对应等待态"的孤儿行(入队与迁移要么全成、
        要么全滚)。

        ``session`` 非空时**加入调用方事务**(不自开、不提交/回滚,由调用方 with 块统一管理),
        供 queue.py 把"迁移 + remediation + 关单"凑成一个原子单元;为 None 时自开自管(默认)。
        迁移 + events 仍是本层唯一真相源(SPEC 边界)——调用方只提供事务,不旁路这段逻辑。
        """
        to = PipelineState(to_state)
        if session is not None:
            self._do_transition(session, doc_version_id, to, actor, error_code, detail, queue_row)
            return
        with self.session() as s:
            self._do_transition(s, doc_version_id, to, actor, error_code, detail, queue_row)

    def _do_transition(
        self,
        s: Session,
        doc_version_id: str,
        to: PipelineState,
        actor: str,
        error_code: str | None,
        detail: dict | None,
        queue_row: ReviewQueue | None,
    ) -> None:
        dv = s.get(DocVersion, doc_version_id)
        if dv is None:
            raise KeyError(doc_version_id)
        frm = PipelineState(dv.pipeline_status)
        if not can_transition(frm, to):
            raise ValueError(f"非法迁移 {frm} -> {to}")
        dv.pipeline_status = to.value
        if error_code is not None:
            dv.last_error_code = error_code
        s.add(
            PipelineEvent(
                doc_version_id=doc_version_id,
                from_state=frm.value,
                to_state=to.value,
                error_code=error_code,
                actor=actor,
                detail=detail,
            )
        )
        if queue_row is not None:
            s.add(queue_row)

    # ── chunks ────────────────────────────────────────────────
    def bulk_insert_chunks(self, chunks: list[Chunk]) -> None:
        with self.session() as s:
            s.add_all(chunks)

    def replace_chunks(self, doc_version_id: str, chunks: list[Chunk]) -> None:
        """同事务替换某文档全部 chunk:先删旧再插新。

        确定性 chunk_id 使 s3 可重跑(reprocess/重入):同输入产出同 id 集,旧行被整体替换、
        不撞 PK。删 + 插共用一个事务,失败回滚不留半套。
        """
        with self.session() as s:
            s.execute(delete(Chunk).where(Chunk.doc_version_id == doc_version_id))
            s.add_all(chunks)

    def write_cold_vectors(self, updates: dict[str, tuple[bytes, bytes]]) -> None:
        """写 chunks 冷备向量:``{chunk_id: (dense_bytes, sparse_bytes)}``(s5 embed 阶段)。"""
        with self.session() as s:
            for chunk_id, (dense_b, sparse_b) in updates.items():
                c = s.get(Chunk, chunk_id)
                if c is not None:
                    c.dense_vec_cold = dense_b
                    c.sparse_vec_cold = sparse_b

    def set_chunk_status(self, doc_version_id: str, status: str) -> None:
        """翻转某文档全部 chunk 的 chunk_status(s5 index:staging→effective/upcoming)。"""
        with self.session() as s:
            for c in s.scalars(select(Chunk).where(Chunk.doc_version_id == doc_version_id)):
                c.chunk_status = status

    def set_version_status(self, doc_version_id: str, status: str) -> None:
        """翻转某文档 version_status(s5 index 写 effective/upcoming;activate 翻 upcoming)。"""
        with self.session() as s:
            dv = s.get(DocVersion, doc_version_id)
            if dv is not None:
                dv.version_status = status

    def supersede_version(
        self, old_dvid: str, *, new_dvid: str, old_status: str = "superseded"
    ) -> None:
        """版本原子切换(PG 侧,D1):单事务内把旧版及其全部 chunk 置 ``old_status``、新版置 effective。

        - 旧版 ``DocVersion.version_status`` → ``old_status``;其 ``chunks.chunk_status`` → 同值
          (与 Milvus 标量一致,且 rebuild 从 PG 重建时不会把旧版误标回 effective)。``old_status``
          默认 superseded(revise_replace);abolish_only 件传 "abolished"(§1.1/§7.2 废止终态)。
        - 新版 ``version_status`` → effective(幂等;新版 INDEXED 时已是 effective)。
        单事务使切换在 PG 侧原子、可重放安全(旧版已置 ``old_status`` 时重跑等价无副作用)。
        """
        with self.session() as s:
            old = s.get(DocVersion, old_dvid)
            if old is not None:
                old.version_status = old_status
            new = s.get(DocVersion, new_dvid)
            if new is not None:
                new.version_status = "effective"
            for c in s.scalars(select(Chunk).where(Chunk.doc_version_id == old_dvid)):
                c.chunk_status = old_status

    def chunk_doc_version_ids(self) -> list[str]:
        """有 chunk 的全部 doc_version_id(去重)——供 rebuild 遍历全量重灌。"""
        with self.session() as s:
            return list(s.scalars(select(Chunk.doc_version_id).distinct()))

    def get_chunks(self, doc_version_id: str) -> list[Chunk]:
        with self.session() as s:
            return list(
                s.scalars(
                    select(Chunk).where(Chunk.doc_version_id == doc_version_id).order_by(Chunk.seq)
                )
            )

    def get_issuers(self) -> list[DictIssuer]:
        """发文机关字典(供 s4 L1 机构匹配)。"""
        with self.session() as s:
            return list(s.scalars(select(DictIssuer)))

    # ── cases(P-CASE 案例要素)──────────────────────────────────
    def upsert_case(self, doc_version_id: str, fields: dict) -> None:
        """按 doc_version_id upsert 一行 ``cases``(merge 即 upsert,reprocess 重跑覆盖安全)。"""
        with self.session() as s:
            s.merge(Case(doc_version_id=doc_version_id, **fields))

    def get_case(self, doc_version_id: str) -> Case | None:
        with self.session() as s:
            return s.get(Case, doc_version_id)

    # ── 字典 seed ─────────────────────────────────────────────
    def get_entity_types(self) -> list[DictEntityType]:
        with self.session() as s:
            return list(s.scalars(select(DictEntityType)))

    def get_departments(self) -> list[DictDepartment]:
        with self.session() as s:
            return list(s.scalars(select(DictDepartment)))

    def get_biz_domains(self) -> list[DictBizDomain]:
        """业务域/涉及事项字典(E2 打标「涉及事项」约束空间,§19.2)。"""
        with self.session() as s:
            return list(s.scalars(select(DictBizDomain)))

    def seed_dicts(self, seeds_dir: str | Path) -> dict[str, int]:
        """从 CSV 导入字典表(merge 即 upsert,可重复执行)。返回 {表名: 行数}。

        含 dict_issuers / dict_biz_domains + V1.6 新增 dict_entity_types / dict_departments
        (E2 打标约束字典,§19.2;带 dict_version)。
        """
        seeds_dir = Path(seeds_dir)
        issuers = _read_csv(seeds_dir / "dict_issuers.csv")
        domains = _read_csv(seeds_dir / "dict_biz_domains.csv")
        entity_types = _read_csv(seeds_dir / "dict_entity_types.csv")
        departments = _read_csv(seeds_dir / "dict_departments.csv")
        with self.session() as s:
            for r in issuers:
                s.merge(
                    DictIssuer(
                        code=r["code"], name=r["name"], issuer_level=r.get("issuer_level") or None
                    )
                )
            for r in domains:
                s.merge(
                    DictBizDomain(
                        code=r["code"], name=r["name"], parent_code=r.get("parent_code") or None
                    )
                )
            for r in entity_types:
                s.merge(
                    DictEntityType(
                        code=r["code"], name=r["name"], dict_version=r.get("dict_version") or None
                    )
                )
            for r in departments:
                s.merge(
                    DictDepartment(
                        code=r["code"], name=r["name"], dict_version=r.get("dict_version") or None
                    )
                )
        return {
            "issuers": len(issuers),
            "biz_domains": len(domains),
            "entity_types": len(entity_types),
            "departments": len(departments),
        }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
