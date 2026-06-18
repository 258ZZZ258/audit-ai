"""L1 案例要素抽取(§9,规则)→ ``cases`` 表(纯逻辑,无 PG / 无 LLM,可单测)。

从处罚决定书全文抽:处罚机构 / 文号 / 处罚日期 / 当事人(+机构|个人)/ 处罚类型 / 金额(万元)。
文号/日期复用 ``l1_rules`` 正则(同一口径)。``violation_category`` / ``cited_regulations`` 为
**L2 LLM 字段(默认关、本阶段不抽)**——留 None/[];``ref_unresolved`` 暂置 False。
"""

from __future__ import annotations

import re

from pipeline.chunking.normalize import strip_ws, to_halfwidth
from pipeline.meta.l1_rules import _DATE_CN, _DATE_ISO, _DOC_NUM_PATTERNS, _safe_date

# 处罚机构:头部以「…局/会/厅/委员会/办公室」结尾的机构抬头(非贪婪取最短,首个命中即返回)。
_ORG_PATTERN = re.compile(r"([一-鿿A-Za-z]{2,40}?(?:局|委员会|办公室|会|厅))")
# 当事人:「当事人:X」「被处罚人:X」「被检查人:X」「被检查单位:X」抓名称(到分隔符/句末)。
_RESPONDENT_PATTERN = re.compile(
    r"(?:当事人|被处罚人|被检查单位|被检查人)\s*[:：]?\s*([^\s,,。;;]{1,40})"
)
# 个人特征:身份证 / 性别 / 出生 等 → 个人;否则机构(「住所地」机构也用,不作个人判据)。
_PERSON_HINTS = re.compile(r"身份证|性别|出生|男,|女,")
# 当事人无显式前缀时的回退:「机构名(、个人…)+ 冒号」抬头行(警示函/决定书首段)。
_PARTY_LINE = re.compile(r"^([^:：]{2,80}?(?:公司|中心|银行|集团|协会|事务所))[^:：]{0,40}[:：]$")
# 抬头回退须排除的行(段落正文/页眉,非当事人抬头)。
_NOT_PARTY = re.compile(r"^\s*(经查|依据|根据|违反|现决定|我局|我会|截至|http|\d{4}/)")
# 处罚/监管措施类型关键词(命中即收;按列表序去重保序拼接)。含行政监管措施(警示函/监管谈话)。
_PENALTY_TYPES = ["警示函", "监管谈话", "警告", "罚款", "没收", "责令", "市场禁入"]
# 金额:「X万元」或「X元」(支持千分位 / 小数);归一到万元 Float。
_AMOUNT_WAN = re.compile(r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*万元")
_AMOUNT_YUAN = re.compile(r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*元")


def _norm(s: str | None) -> str:
    return strip_ws(to_halfwidth(s or ""))


def _norm_dn(s: str) -> str:
    """文号括号归一:统一中西括号变体(〔【→[、〕】→]),同 l1_rules._norm_dn。"""
    return s.replace("〔", "[").replace("【", "[").replace("〕", "]").replace("】", "]")


def _first_doc_number(raw_head_lines: list[str]) -> str | None:
    """逐行抽文号(同 l1_rules:跨行拼接会让机构前缀正则贪婪吃进相邻行如机构抬头);括号归一。"""
    for line in raw_head_lines:
        nt = _norm(line)
        if "令第" in nt:  # 「证监会令第X号」= 被引外规令号,非本决定书文号,跳过
            continue
        for pat in _DOC_NUM_PATTERNS:
            m = pat.findall(nt)
            if m:
                return _norm_dn(m[0])
    return None


def _first_org(raw_head_lines: list[str]) -> str | None:
    """逐行抽机构抬头(逐行避免跨行把标题/相邻行吞进非贪婪机构匹配);取首个命中。"""
    for line in raw_head_lines:
        m = _ORG_PATTERN.search(_norm(line))
        if m:
            return m.group(1)
    return None


def _last_date(text: str) -> str | None:
    """末次出现的成文日期(落款常在文末);返回 ISO 字符串,无则 None。"""
    found: list[str] = []
    for pat in (_DATE_CN, _DATE_ISO):
        for m in pat.finditer(text):
            d = _safe_date(*m.groups())
            if d:
                found.append(d.isoformat())
    return found[-1] if found else None


def _amount_wan(text: str) -> float | None:
    """金额归一到万元 Float:优先「X万元」,否则「X元」÷1e4。取首个命中(通常即处罚金额)。"""
    m = _AMOUNT_WAN.search(text)
    if m:
        return float(m.group(1).replace(",", ""))
    m = _AMOUNT_YUAN.search(text)
    if m:
        return float(m.group(1).replace(",", "")) / 10000.0
    return None


def _penalty_type(text: str) -> str | None:
    hits = [t for t in _PENALTY_TYPES if t in text]
    return "/".join(hits) if hits else None


def _respondent(text: str, raw_lines: list[str]) -> tuple[str | None, str | None]:
    """当事人名称 + 类型(机构|个人)。先认显式前缀,无则回退抬头「名称+冒号」行。"""
    m = _RESPONDENT_PATTERN.search(text)
    name = m.group(1).strip() if m else None
    if not name:  # 回退:抬头首条「机构名 + 冒号」行(跳过经查/依据等正文段落)
        for line in raw_lines[:5]:
            ls = line.strip()
            if not ls or _NOT_PARTY.match(ls):
                continue
            pm = _PARTY_LINE.match(ls)
            if pm:
                name = pm.group(1).strip()
                break
    if not name:
        return None, None
    rtype = "个人" if _PERSON_HINTS.search(text) else "机构"
    return name, rtype


def extract_case(doc_or_ir_text: str, manifest_meta: dict) -> dict:
    """从决定书全文抽案例要素(纯函数)。

    ``doc_or_ir_text``:决定书全文(已拼接的纯文本)。``manifest_meta``:manifest 权威值
    (键 ``issuer`` 作 ``penalty_org`` 兜底;其余键忽略)。返回可直接喂 ``Case`` 的 dict。
    """
    raw_head_lines = doc_or_ir_text.splitlines()[:8]  # 头部逐行(机构/文号在版头,逐行避免贪婪误吞)
    text = _norm(doc_or_ir_text)

    penalty_org = _first_org(raw_head_lines) or (manifest_meta.get("issuer") or None)
    respondent, respondent_type = _respondent(text, doc_or_ir_text.splitlines())

    return {
        "penalty_org": penalty_org,
        "doc_number": _first_doc_number(raw_head_lines),
        "penalty_date": _last_date(text),  # ISO 字符串;s4 转 date 入库
        "respondent": respondent,
        "respondent_type": respondent_type,
        "penalty_type": _penalty_type(text),
        "amount_wan": _amount_wan(text),
        # violation_category / cited_regulations 是 L2 LLM 字段(默认关,本阶段不抽)→ 留空。
        "violation_category": None,
        "cited_regulations": [],
        "ref_unresolved": False,
    }
