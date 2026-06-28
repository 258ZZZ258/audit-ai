# 索引 / 嵌入 / 冷备 devlog(pipeline/pipeline/index)

**职责**:S5 向量化与索引写入。`embedding_client.py`(BGE-M3)· `milvus_io.py`(I/O,schema 定义已抽到 common)· `corpus_rows.py`(s5/finalize 共享映射层)· `pg_io.py`(PG 权威 I/O)· `object_store.py`。stage 在 `stages/s5_embed_index.py`。

## 关键决策 / 踩坑
- **EmbeddingClient(C4)**:ABC + 本地 BGEM3(懒加载,一次 `encode` 出 dense+sparse)。**环境坑**:hf-mirror 在该网络 308 跳回 HF、直连慢 → 用 **modelscope** 拉 bge-m3,经 `PIPELINE_EMBEDDING_MODEL` 指本地目录 + `HF_HUB_OFFLINE=1`;真模型测试 gate 该 env(未设秒 skip,绝不联网下载)。`EndpointClient` **fail-fast 在 `__init__`**(`mode` 是 config 合法值,否则到 S5 才崩);`cache_dir` 透传 `BGEM3FlagModel`。
- **milvus_io(C5)**:`upsert`(`upsert_batch`/批,**不自动 flush**,写序由 s5 控)+ flush + count/delete + **混合查**(dense+sparse + RRFRanker,默认 `status=="effective"` 过滤;hybrid 失败/空 sparse → **dense-only 兜底 + `retrieval_mode`** 标记)+ 冷备 serialize(dense float32 / sparse JSON)。search/count 用 Strong 一致性。
- **`include_superseded` 漏 staging(C7 审查修复,硬契约)**:原实现该旗标时**整条删 `status` 过滤** → staging 半成品可见,违反「staging 不可见」。修:旗标只把可见集从 `effective` 放宽到 `[effective, superseded]`,**staging 任何情况不可见**。
- **s5(C6)**:`embed`(嵌入非-parent + 冷备写 PG + Milvus upsert staging)→ `index`(flush + `count==` 校验 + 从冷备重 upsert effective + 翻 chunk_status + 终态)。**写序 PG→upsert→flush→INDEXED**;parent 仅 PG。stage 只返 `next_state` 不写 status(orchestrator 应用)→ s5 测试须经 orchestrator 驱动。
- **`corpus_rows` 共享层(D1)**:s5 与 finalize 都要「PG chunk + 冷备 → CorpusRow」但两 stage 不得互 import → 放 `index/` 共用(`build_rows`/`rows_from_cold`/`indexable_chunks`)。`rows_from_cold_strict`(任一缺冷备抛 `ColdBackupIncomplete`)给 s5 INDEXING + finalize(否则缺冷备静默少返回、文档仍翻 effective,破坏「全块就绪才可见」)。

- **finalize chunk_id 相撞(D1 踩坑)**:同毫秒 ULID 仅末位不同,`dvid[:22]+suffix` 截法使两版 chunk_id 撞车 → 用 tag 前缀区分(ULID `[:8]` 坑的 finalize 复现)。
- **milvus 两契约点**:`page_start` 未对齐写 **0**(INT64 不收 None),渲染按 falsy 判「未对齐」;`probe_retrieval_mode`(合成非零向量 topk=1 探 hybrid/dense_only,**免模型免真查**)。
- **v1.6 下游取值**:Milvus `biz_domain` ARRAY 优先 `dv.biz_domains`(L2 多值),空回落 manifest 单值 `biz_domain`(`corpus_rows.build_rows`;改此处勿漏——L2 写库逻辑在 metadata 模块)。

## 升格
Milvus schema 定义抽到 `common.milvus_schema`,`MilvusIO.schema()` 委托 `audit_corpus_schema()`(值不变);其余 I/O 留本模块。

> 时间轴:`docs/devlog.md` 阶段 C(C4/C5/C6/C7 审查)、阶段 D(D1 corpus_rows)、升格 Step 2。
