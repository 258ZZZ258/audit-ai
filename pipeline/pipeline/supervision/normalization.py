"""Exact status aliases only. Never infer progress from a substring such as 完成."""

STATUS_ALIASES = {
    "全部完成": "已完成",
    "已全部完成": "已完成",
    "全部整改完成": "已完成",
    "整改已全部完成": "已完成",
    "完成": "已完成",
    "整改中": "进行中",
    "正在整改": "进行中",
    "部分已完成": "部分完成",
    "已完成部分整改": "部分完成",
    "尚未完成": "未完成",
    "未全部完成": "未完成",
}


def normalize_status(value):
    cleaned = value.strip().rstrip("。；")
    return STATUS_ALIASES.get(cleaned, cleaned)
