"""audit-common —— audit-ai 契约承重层(单一来源,只搬位置不改值)。

子模块:
- ``ir``          IR 统一中间表示 schema(§4.2)
- ``pg_models``   PG 表模型/字段(§10,add-only)
- ``chunk_id``    chunk_id 公式(§6.5,幂等根基)
- ``milvus_schema`` Milvus ``audit_corpus`` collection schema(§8.2)
- ``manifest``    manifest 必填列契约(§3.1)

不依赖任何上层(pipeline / eval)。所有上层只从这里取契约。
"""
