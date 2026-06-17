"""manifest 列契约(§3.1)—— 导入清单 9 必填列,导入时校验,不匹配整批拒收。

**契约**:只搬位置、值不变(列名/顺序对齐生产 §3.1)。
"""

from __future__ import annotations

REQUIRED_COLUMNS = [
    "filename", "title", "doc_number", "issuer", "perm_tag",
    "corpus_type", "biz_domain", "issue_date", "supersedes",
]
