"""T7(SPEC-API §8.3):条款回查端点(联动展示 / 查看原文 / 详细释义 / 完整定义)。

``GET /clauses/{clause_id}`` → 四级锚点 + 全文 + 节级父块(PG 权威);不存在 → 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from query.api.errors import not_found
from query.api.service import QueryService, get_service

router = APIRouter(prefix="/clauses", tags=["clauses"])


@router.get("/{clause_id}")
def get_clause(clause_id: str, svc: QueryService = Depends(get_service)) -> dict:
    detail = svc.clause_detail(clause_id)
    if detail is None:
        raise not_found("条款不存在")
    return detail
