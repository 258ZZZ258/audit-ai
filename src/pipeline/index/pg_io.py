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

from pipeline.config import Settings
from pipeline.index.pg_models import (
    Chunk,
    DictBizDomain,
    DictIssuer,
    DocVersion,
    PipelineEvent,
    ReviewQueue,
)
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
        """翻转某文档全部 chunk 的 chunk_status(s5 index:staging→effective)。"""
        with self.session() as s:
            for c in s.scalars(select(Chunk).where(Chunk.doc_version_id == doc_version_id)):
                c.chunk_status = status

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

    # ── 字典 seed ─────────────────────────────────────────────
    def seed_dicts(self, seeds_dir: str | Path) -> tuple[int, int]:
        """从 CSV 导入 dict_issuers / dict_biz_domains(merge 即 upsert,可重复执行)。"""
        seeds_dir = Path(seeds_dir)
        issuers = _read_csv(seeds_dir / "dict_issuers.csv")
        domains = _read_csv(seeds_dir / "dict_biz_domains.csv")
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
        return len(issuers), len(domains)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
