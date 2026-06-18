"""manifest 列契约(§3.1)—— 导入清单必填列,导入时校验,不匹配整批拒收。

**契约**:列名/顺序对齐生产 §3.1。V1.6 增 ``sub_type``(子类型:法律/规章/自律规则…,
驱动 issuer_level 分层与灰度)+ ``effective_date``(生效日期,upcoming 判定与时间窗过滤)。
"""

from __future__ import annotations

REQUIRED_COLUMNS = [
    "filename", "title", "doc_number", "issuer", "perm_tag",
    "corpus_type", "sub_type", "biz_domain", "issue_date", "effective_date", "supersedes",
]
