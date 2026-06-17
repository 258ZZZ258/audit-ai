"""chunk_id 公式(§6.5)—— 幂等的根基,逐字确定性。

    chunk_id = sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]

确定性 ID 保证:同一版本重跑管线产生相同 ID → Milvus upsert 天然幂等、PG ON CONFLICT 可重入。
**契约**:一字不改(pin: libs/common/tests/test_chunk_id.py 钉死逐字节输出)。
"""

from __future__ import annotations

import hashlib


def compute_chunk_id(doc_version_id: str, clause_path_norm: str, seq: int) -> str:
    raw = f"{doc_version_id}|{clause_path_norm}|{seq}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
