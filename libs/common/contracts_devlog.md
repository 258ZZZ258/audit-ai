# 契约层 devlog(libs/common)

**职责**:5 项硬契约的单一来源(`ir` / `pg_models` / `chunk_id` / `milvus_schema` / `manifest`),**不依赖任何上层**;所有上层只从这里取。改这里 = 改契约,必先读 `SPEC*.md` + 生产 §4.1/4.2/6.5/8.2/10。

## 关键决策 / 踩坑

- **`ir.py`(§4.2)**:pydantic `extra=forbid` + 校验器(表格块必带 `table`、`page_end≥page`、`index` 严格升序)。是解析器与下游的稳定边界——换解析器不动它。
- **`pg_models.py`(§10)**:字段名/类型/枚举对齐生产,枚举存 String,**add-only**(Alembic 强制,绝不改名/删),含 bytea 冷备列。验证:autogenerate → `upgrade` → `alembic check` 无漂移。
- **`chunk_id`(§6.5)**:`sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]`。幂等之根——同版本重跑同 id、Milvus upsert 天然幂等、PG ON CONFLICT 可重入。**一字不改**;pin `libs/common/tests/test_chunk_id.py` 第 27 行 byte-exact 钉死公式构造(比存哈希更强)。
- **`milvus_schema.py`(§8.2)**:`audit_corpus` 全字段,`corpus_type` 作 partition key,`DENSE_DIM=1024`。`perm_tag`/`biz_domain`/`issuer_level` 全链写入,但 **`perm_tag` 过滤逻辑有意不实现**(字段预留)。
- **`manifest.py`(§3.1)**:9 必填列,导入校验、不匹配整批拒收。

## 升格(audit-ai)
契约从原 `src/pipeline` 归位 `libs/common/common/`:`ir.py`/`pg_models.py` 纯文件**整体 git mv**(历史保留);`chunk_id`/`milvus_schema`/`manifest` 从机制文件(chunker/milvus_io/s0_register)**surgical 抽取**(值逐字不变,机制留原处改 import)。`common` 零 `pipeline` 上行依赖。详见 `docs/migration_devlog.md` Step 2。

> 时间轴全叙事:`docs/devlog.md` 阶段 A(A2 ir / A4 pg_models / A8 milvus schema)、并行流 L(L3 chunk_id)、升格段。
