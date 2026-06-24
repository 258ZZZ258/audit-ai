"""LLM 无标注裁判:对单 PDF 一次结构化调用,核对三大目标(没有 manifest/人工标注时的"真值")。

- 目标①:正则抽取的字段/条款结构 对不对、全不全(LLM 当真值)。
- 目标②:解析文本是否版面破碎 / 需要 DeepDoc。
- 目标③:文档真实质量好坏(用于反推 QC 阈值松紧)。

key/endpoint 走 env(``OPENAI_API_KEY`` 等),绝不入库。LLM 失败不阻断——返回 error 标记,报告照常出确定性部分。
"""

# ruff: noqa: E501  (工具脚本:报告/prompt 文案 CJK 密集,放宽行宽)

from __future__ import annotations

from pipeline.llm_client import LLMError, make_llm_client

_SYSTEM = (
    "你是审计/合规文档处理管线的质量评审。给你一份 PDF 的【解析文本】(可能截断)、它的 corpus_type、"
    "以及管线用正则【自动抽取的字段/结构】。你的任务是当作'真值'核对三件事,只依据文本本身判断,"
    "不臆测。严格输出 JSON,不要多余文字。"
)

_SCHEMA = """请输出如下 JSON:
{
 "goal1_extraction": {
   "doc_number": {"correct": true|false|"na", "should_be": "文本中真实文号或null"},
   "date":       {"correct": true|false|"na", "should_be": "真实发布/处罚日期或null"},
   "issuer_or_org": {"correct": true|false|"na", "should_be": "真实发文/处罚机构或null"},
   "structure_complete": true|false,   // 条款/要素结构是否被完整识别(无漏条/漏要素)
   "issues": ["具体问题,如 '第N条用「第N部分」体例未被识别' / '当事人漏抽'"],
   "coverage_score": 0.0
 },
 "goal2_parse": {
   "verdict": "light_ok"|"deepdoc_recommended",
   "reasons": ["scanned_no_text"|"tables_lost"|"multi_column_interleaved"|"ocr_garble"|"reading_order_broken"|"formula_lost"],
   "confidence": 0.0
 },
 "goal3_quality": {
   "doc_quality": "good"|"borderline"|"bad",
   "reason": "一句话:这份文档作为该类型语料是否完整规整"
 }
}"""


def _sample(text: str, max_chars: int, strategy: str) -> str:
    if len(text) <= max_chars:
        return text
    if strategy == "head":
        return text[:max_chars]
    h = max_chars // 2
    t = max_chars - h
    return text[:h] + "\n…(中段略)…\n" + text[-t:]


def judge_pdf(metrics: dict, llm_cfg: dict, client=None) -> dict:
    """对单 PDF 的确定性 metrics + 解析文本跑一次 LLM 裁判 → dict(含 error 时仍可用)。

    ``client`` 复用同一 LLMClient(批量省构造);传 None 时按 ``llm_cfg`` 现造。
    """
    text = metrics.get("_text", "")
    if not text:
        return {"error": "无解析文本(解析失败或空),跳过 LLM 裁判"}
    try:
        client = client or make_llm_client(llm_cfg.get("model"))
    except LLMError as e:
        return {"error": f"LLM 不可用:{e}"}

    sample = _sample(text, int(llm_cfg.get("max_chars", 12000)), llm_cfg.get("sample", "head_mid_tail"))
    user = (
        f"corpus_type: {metrics.get('corpus_type')}\n"
        f"自动抽取(正则): {metrics.get('extracted')}\n"
        f"QC 判定(未过): {metrics.get('qc_failed')}\n\n"
        f"【解析文本】\n{sample}\n\n{_SCHEMA}"
    )
    try:
        return client.chat_json(_SYSTEM, user)
    except LLMError as e:
        return {"error": f"LLM 调用/解析失败:{e}"}
