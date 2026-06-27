"""T2.3a 业务域 L2 LLM 打标(§7.1):整篇制度 → 业务域多值(``dict_biz_domains`` 约束)。

L2 元数据辅助(默认关 ``l2_enabled``);默认路径零 LLM(本模块不被触达)。镜像 E2/case_l2 纪律:
- **字典约束服务端裁剪**:取值空间是 ``dict_biz_domains``;LLM 返回任何字典外值一律丢弃。
- **不臆测**:只在文档内容明确支持时才打;无法明确归类留空。
- **字典空 → 不调 LLM**(consumed-when-present)。

纯打标(返回多值 list);写权威字段(``doc_versions.biz_domains`` + ``biz_domain_source="llm"``)的
profile 分档装配在 s4_meta(T2.3b)。``dict_biz_domains`` 无 ``dict_version`` 列(seed schema 既定,
同 E2「涉及事项」)——业务域 provenance 落 ``biz_domain_source`` 标志,不另记版本。
"""

from __future__ import annotations

import hashlib

_SYSTEM_BIZ = (
    "你是证券公司制度文档的业务域打标助手。任务:仅依据给定的【允许清单】,为整篇制度判定其所属"
    "「业务域」(可多值)。硬性规则:"
    "(1) 取值必须**严格来自**允许清单原文,不得改写、近义替换或自创;"
    "(2) 只在文档内容明确支持时才打;无法明确归类一律留空,**不臆测**;"
    "(3) 只输出 JSON 对象 "
    '{"biz_domains": []},为字符串数组,无命中给空数组;不输出 JSON 之外的任何文字。'
)


def build_biz_prompt(doc_text: str, allowed: list[str]) -> tuple[str, str]:
    """构造 (system, user):在【允许清单】内判定整篇业务域(多值)。"""
    user = (
        "【允许清单 · 业务域】\n"
        + ("、".join(allowed) if allowed else "(空)")
        + "\n\n【制度文档(节选)】\n"
        + (doc_text or "")
        + '\n\n请按规则只输出 JSON:{"biz_domains": [...]}。'
        "取值严格取自上述清单;无法明确归类留空,不臆测。"
    )
    return _SYSTEM_BIZ, user


def _enforce(returned: object, allowed: set[str]) -> list[str]:
    """服务端字典约束:只保留落在 allowed 内的字符串(去重、保序);非 list → []。"""
    if not isinstance(returned, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for v in returned:
        if isinstance(v, str) and v in allowed and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def tag_biz_domain(client, doc_text: str, allowed: list[str]) -> list[str]:
    """调 LLM 给整篇制度打业务域,**服务端裁字典**;返回多值 list。

    ``allowed`` 空 → 不调 LLM、直接 ``[]``(consumed-when-present)。LLM 越界值被丢弃。
    """
    if not allowed:
        return []
    system, user = build_biz_prompt(doc_text, allowed)
    raw = client.chat_json(system, user)
    val = raw.get("biz_domains") if isinstance(raw, dict) else None
    return _enforce(val, set(allowed))


# ── T2.3b 业务域 profile 分档(纯逻辑:定权威值 / 来源 / 是否人工)──────────────
_DIRECT_LAND = ("P-EXT", "P-QA", "P-CASE")  # LLM 业务域直落 effective 的 profile


def _sampled(key: str, rate: float) -> bool:
    """确定性抽检:``rate<=0`` → False;``rate>=1`` → True;否则按 sha1(key) 落点 < rate。

    确定性(非随机)使重跑/测试可复现——同 key 同 rate 恒同判。
    """
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    h = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)
    return (h / 0xFFFFFFFF) < rate


def biz_l2_decision(
    corpus: str,
    manifest_biz: str | None,
    llm_biz: list[str],
    *,
    sampling_rate: float,
    sample_key: str,
) -> tuple[list[str] | None, str | None, bool]:
    """纯逻辑定 ``(biz_domains, source, needs_review)``(§7.1 交叉校验 + profile 分档)。

    - **manifest 有值 → 优先**:权威用 manifest(``source=manifest``);LLM 给值且与 manifest **不一致**
      (manifest 不在 LLM 命中里)→ 冲突 → 待人工。
    - **manifest 无 → LLM 主来源**(``source=llm``):**P-INT 候选恒入 META_REVIEW**(内规权威担责);
      P-EXT/P-QA/P-CASE **直落 effective**,仅 ``sampling_rate`` 抽中者入 spot-check 复核。
    - manifest 无且 LLM 空 → ``(None, None, False)``(无候选,不写、不复核)。
    """
    if manifest_biz:
        conflict = bool(llm_biz) and manifest_biz not in llm_biz
        return [manifest_biz], "manifest", conflict
    if not llm_biz:
        return None, None, False
    if corpus == "P-INT":
        return llm_biz, "llm", True  # 内规业务域候选恒人工确认
    return llm_biz, "llm", _sampled(sample_key, sampling_rate)  # 直落 + 抽检
