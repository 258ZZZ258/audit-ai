"""T4(SPEC-API §9):鉴权接缝(stub)。

本轮**放行**,但把 401/403 语义、角色上下文、导出权限点、操作日志位定好;真 Casbin RBAC/ABAC + SSO
后续增量接入(替换 ``current_principal`` 解析 + ``require_export_permission`` 的 policy.enforce)。
"""

from __future__ import annotations

from dataclasses import dataclass

from query.api.errors import forbidden


@dataclass
class Principal:
    """请求主体(角色上下文)。真接入后由 SSO/session 填充;stub 给默认审计角色。

    ``can_export`` 是 stub 权限位(真 Casbin 接入后由 ``policy.enforce`` 决定),便于测试 403 路径。
    """

    user_id: str = "demo-user"
    role: str = "审计人员"
    can_export: bool = True


def current_principal() -> Principal:
    """当前主体(FastAPI 依赖)。stub 恒返回默认审计角色。

    真接入:解析 SSO/session,未认证 → ``raise unauthenticated()``(401)。
    """
    return Principal()


def require_export_permission(principal: Principal) -> None:
    """导出权限点(SPEC-API §8.1):无权 → 403。stub 用 ``principal.can_export`` 判定。

    操作日志:导出动作应写操作日志(user/time/action = export);真接入时在此落日志。
    """
    if not principal.can_export:
        raise forbidden("无导出权限")
    # TODO(Casbin): policy.enforce(principal.role, "export", resource);写操作日志
