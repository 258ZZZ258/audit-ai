# 任务清单：文档处理管线 · 本地 Demo（M1 · Phase 3）

> 上游:`SPEC.md`(规格)、`PLAN.md`(四阶段 + 风险)。本文件把计划拆成可独立实施的任务。
> 排序按**依赖**(非重要性)。单任务 ≤5 个代码文件(fixtures/seed 等数据文件不计入此限)。
> 图例:依赖 = 前置任务;验收 = 完成判据;验证 = 确认命令/手段;`[需 demo up]` = 需 pg+milvus 在跑的集成验证。
> CC 任务映射:**T-A** = 阶段 A+B,**T-B** = 阶段 C+D(并行流横跨两者)。

---

## 阶段 A — 底座与环境(T-A)

- [ ] **A1 · 项目骨架 + 配置加载**
  - 依赖:无(最先)
  - 验收:`pip install -e .` 通;`from pipeline.config import load_config` 返回带类型的 config(覆盖 settings/qc_thresholds/profiles 全部 ⚠ 值,含对齐带宽/模糊阈值/批量参数);`ruff` 配好;`PROMPTS.md` 占位存在并声明"L2 开启时启用"
  - 验证:`pip install -e . && python -c "from pipeline.config import load_config; load_config()"`;`ruff check .`
  - 文件:`pyproject.toml`、`src/pipeline/config.py`、`config/settings.toml`、`config/qc_thresholds.yaml`、`config/profiles.yaml`(+`PROMPTS.md`)

- [ ] **A2 · IR 契约模型**
  - 依赖:A1
  - 验收:`ir.py` pydantic 模型含 blocks/tables/bbox/page(bbox 可空、page 对齐前可空),全字段对齐生产 §4.2;JSON 双向 round-trip 无损
  - 验证:`pytest -k ir`
  - 文件:`src/pipeline/ir.py`、`tests/test_ir.py`

- [ ] **A3 · 状态机枚举 + Stage 契约 + 错误码表**
  - 依赖:A1
  - 验收:`PipelineState` 为 demo 子集(无 REPARSE 系);`StageContext`/`StageResult`/`QueueItem` 定义,`StageResult` 携带 next_state/error_code/evidence/queue/artifacts;错误码 E1xx–E8xx 子集 + `-DEMO` 后缀(含 E101/E202/E203/E204-DEMO/E301);合法迁移表显式定义
  - 验证:`pytest -k states`(断言非法迁移被拒)
  - 文件:`src/pipeline/states.py`、`src/pipeline/stage_base.py`、`tests/test_states.py`

- [ ] **A4 · PG schema + SQLAlchemy 模型 + Alembic 首批迁移**
  - 依赖:A1
  - 验收:11 张表建成(`import_batches`/`documents`/`doc_versions`/`chunks`〔含 `dense_vec_cold`/`sparse_vec_cold` bytea〕/`pipeline_events`/`remediation_records`/`revision_notes`/`clause_tags`/`review_queue`/`dict_issuers`/`dict_biz_domains`),字段名/类型/枚举对齐生产 §10,全表带 created_at/by、updated_at/by;未建表(cases/clause_references/quality_tickets/doc_graph_stats/obligation_keywords)以注释 DDL 保留;add-only
  - 验证:`[需 PG]` `alembic upgrade head` 成功;反射校验表与列名
  - 文件:`src/pipeline/index/pg_models.py`、`alembic.ini`、`alembic/env.py`、`alembic/versions/0001_init.py`

- [ ] **A5 · compose + demo up/down + README 离线说明**
  - 依赖:A1
  - 验收:`compose.yaml` 起 pg16 + milvus2.4(自带 etcd/minio,与业务对象存储无关);`demo up` 健康等待 + 建库,`demo down` 拆除;README 写明 `HF_HOME` 离线缓存路径用法
  - 验证:`demo up` 后 `docker ps` 见 pg+milvus healthy;psql 可连
  - 文件:`compose.yaml`、`src/pipeline/cli.py`、`README.md`

- [ ] **A6 · ObjectStore(本地 FS)**
  - 依赖:A1
  - 验收:按 key 布局 put/get `raw/`、`rendition/`、`ir/`;`raw`+`rendition` 写一次语义
  - 验证:`pytest -k object_store`
  - 文件:`src/pipeline/index/object_store.py`、`tests/test_object_store.py`

- [ ] **A7 · pg_io 基础 + 字典 seed 导入**
  - 依赖:A4
  - 验收:`pg_io` 提供 session + doc_versions/chunks/events 基础读写;`demo up` 把字典 CSV 导入 `dict_issuers`/`dict_biz_domains`
  - 验证:`[需 demo up]` seed 后查询返回行
  - 文件:`src/pipeline/index/pg_io.py`、`seeds/dict_issuers.csv`、`seeds/dict_biz_domains.csv`

- [ ] **A8 · Milvus audit_corpus 建集合**
  - 依赖:A5
  - 验收:`audit_corpus` 全 schema(标量 perm_tag/biz_domain/issuer_level 等 + partition key,dense + sparse 向量字段,HNSW 参数从 config);`demo up` 内建集合
  - 验证:`[需 demo up]` describe collection 字段符合预期
  - 文件:`src/pipeline/index/milvus_io.py`

- [ ] **✅ 检查点 A(硬门)**:`demo up` + `alembic upgrade head` 通过;契约模块可导入;`pytest` 全绿;字典 seed 入库;`audit_corpus` 建成。**过不了不进阶段 B。**

---

## 并行流 P — fixtures 构造(可与阶段 A 同起;阻塞检查点 B)

> 语料构成 ⚠ 可调:batch01 = 外规 3–4(真下载)+ 内规 6(自拟)+ 坏样例 2,总 11–12 件。合规:政府/交易所公开信息可直接用、无需脱敏。

- [ ] **P1 · 下载脚本 + 外规真下载(证监会/交易所公开法规)**
  - 依赖:无(尽早起)
  - 验收:`build_fixtures.py` 下载器按"URL→槽位"清单 `curl`(浏览器 UA + 重试)落 `fixtures/batch01/`;**仅收文本层 PDF**(下载后 pypdf 校验 `len(text)>阈值`,否则报错——防止把图片版当正常件);外规 ≥3 篇真下载:
    - **信息披露办法 182号(2021)** ✅已验证文本层/结构干净 `https://www.csrc.gov.cn/csrc/c106256/c1653948/1653948/files/317acd342b4a437596920f576209385f.pdf`〔部门规章;batch02 的 supersede 目标〕
    - **投资者适当性管理办法** — 规章库 `c106256/c1653849/content.shtml`(下载直链 JS 注入,P1 解析文件列表接口,或换一篇有直链的部门规章)〔部门规章〕
    - **上交所股票上市规则** — sse 站(最新版 docx 或 repeal 版 PDF)〔自律规则〕
    - (可选第 4 篇:再选一篇证监会部门规章,P1 敲定直链)
  - 注:部分规章 PDF **逐字加空格**排版(pdfplumber 抽出"第 一 条"),`normalize` 去空白须先于 `clause_tree`——真素材正好压测此点
  - 验证:`python build_fixtures.py --download` → 外规件落地且 pypdf 文本层校验通过
  - 文件:`tools/build_fixtures.py`、`tools/fixtures_sources.csv`(URL 清单)、`fixtures/batch01/*.pdf`

- [ ] **P2 · 内规自拟生成(python-docx ×6)**
  - 依赖:P1(共用脚本)
  - 验收:脚本生成 6 件内规 docx,**条款号字面文本**(非 Word 自动编号,规避 R5b);覆盖标准章节条 ×3、含大表格跨行组 ×1、含超长条款(>600 token)×1、无章直条短通知 ×1;**其中 ≥1 件嵌入"第X条之一"插入条**(覆盖解析边界,补真规章缺失的之一)
  - 验证:`python build_fixtures.py --gen-internal` → 6 件 docx;python-docx 可读、含预期结构
  - 文件:`tools/build_fixtures.py`、`fixtures/batch01/*.docx`

- [ ] **P3 · 坏样例构造 ×2(确定可复现)**
  - 依赖:P1、P2
  - 验收:① 扫描件 pdf:取一件文本层 PDF **栅格化**(逐页转图再合成无文本层 PDF,<50 字/页)→ S1 路由 `E202-DEMO` 隔离;② 跳号 docx:取一件标准内规**删第8条**留第7→9缺口 → QC 指标2 拦截;两者脚本确定生成
  - 验证:扫描件 pypdf 抽文本≈空;跳号件含确定缺口
  - 文件:`tools/build_fixtures.py`、`fixtures/batch01/*`

- [ ] **P4 · batch02 真实修订对 + manifest 汇总**
  - 依赖:P1
  - 验收:下载 **信息披露办法 226号(2025)** ✅已验证 + 官方**《修订说明》** ✅已验证(3页),落 `fixtures/batch02_revision/`;`manifest.xlsx`(batch01 + batch02)填齐 9 必填列(外规密级=公开、内规=内部,issuer/文号/biz_domain/corpus_type);**batch02 的 226 声明替代 batch01 的 182 的 logical_id**;修订说明走 revision_notes CLI 录入
    - 226 PDF `http://www.csrc.gov.cn/csrc/c101953/c7547359/7547359/files/…上市公司信息披露管理办法.pdf`
    - 修订说明 PDF `http://www.csrc.gov.cn/csrc/c101981/c7528811/7528811/files/…修订说明.pdf`
  - 验证:`openpyxl` 读 manifest 列齐;226 声明替代 182
  - 文件:`tools/build_fixtures.py`、`fixtures/batch02_revision/*`、`fixtures/batch01/manifest.xlsx`、`fixtures/batch02_revision/manifest.xlsx`

---

## 并行流 L — L3 纯逻辑 TDD(A2 完成后即可起;阶段 B/C 装配)

- [ ] **L1 · normalize 中文数字归一化**
  - 依赖:A2
  - 验收:全分支(一二三…十百、`第X条之一`、`21bis`/`21.1b`)
  - 验证:`pytest tests/test_normalize.py`
  - 文件:`src/pipeline/chunking/normalize.py`、`tests/test_normalize.py`

- [ ] **L2 · clause_tree 七类节点正则 + internal_refs**
  - 依赖:L1
  - 验收:章/节/条/款/项/目/虚拟根;`第X条之一` 插入条、虚拟根、`internal_refs[]` 捕获、`clause_path_norm`
  - 验证:`pytest tests/test_clause_tree.py`
  - 文件:`src/pipeline/chunking/clause_tree.py`、`tests/test_clause_tree.py`

- [ ] **L3 · chunker 切块六规则 + chunk_id**
  - 依赖:L2
  - 验收:六规则(300–600 token、超长按款拆+条头续接、超短独立、父块仅 PG ≤2000、表格独立块按行组+重复表头、面包屑前缀、页码跨度);`chunk_id = sha1(doc_version_id+"|"+clause_path_norm+"|"+seq)[:24]` 逐字;**确定性**(同输入两次同输出,定序无无序结构参与)
  - 验证:`pytest tests/test_chunker.py tests/test_chunk_id.py`
  - 文件:`src/pipeline/chunking/chunker.py`、`tests/test_chunker.py`、`tests/test_chunk_id.py`

- [ ] **L4 · page_align 文本对齐**
  - 依赖:A2
  - 验收:单调两指针精确匹配;跨页 `page_start/page_end`;重复文本消歧;`rapidfuzz` 局部兜底(阈值 config);未中 → `page=null`;归一化函数对两侧对称
  - 验证:`pytest tests/test_page_align.py`(含重复"第X条 删除"消歧、跨页、未中用例)
  - 文件:`src/pipeline/parsing/page_align.py`、`tests/test_page_align.py`

---

## 并行流 SP — 早期 spike(A 完成后;降关键路径不确定性)

- [ ] **SP1 · soffice 渲染 + 对齐链路 spike**
  - 依赖:A6、L4
  - 验收:`soffice --headless --convert-to pdf` 成功;pdfplumber 逐页文本 + 偏移区间;对 1 件 fixture docx 端到端回填页码并记录命中率;按 y 坐标剥页眉页脚带
  - 验证:跑 1 件 → block 页码填充;打印命中率(暴露 R5a/R5b)
  - 文件:`src/pipeline/parsing/rendition.py`

- [ ] **SP2 · BGEM3 + Milvus hybrid spike**
  - 依赖:A8
  - 验收:BGEM3 dense+sparse 产出;sparse(`lexical_weights`)→ `SPARSE_FLOAT_VECTOR` 转换;写 1 条 + 混合查 1 条命中;**若 hybrid 受阻,落 dense-only 路径 + `retrieval_mode` 标记**(验证 R2 兜底可行)
  - 验证:`[需 demo up]` 脚本写 1 chunk → hybrid(或 dense-only)查回
  - 文件:`src/pipeline/index/embedding_client.py`、`src/pipeline/index/milvus_io.py`

---

## 阶段 B — 接入到质检(T-A)

- [ ] **B1 · orchestrator 轮询 worker**
  - 依赖:A3、A7
  - 验收:循环 `SELECT 可推进文档 BY pipeline_status` → 调 stage 纯函数 → 条件迁移 → 写 `pipeline_events`;人工等待态(QC_FAILED/META_REVIEW/QUARANTINED)**不轮询**;空闲 sleep
  - 验证:`pytest -k orchestrator`(假 stage 驱动迁移、事件落库、等待态不被轮询)
  - 文件:`src/pipeline/orchestrator.py`、`tests/test_orchestrator.py`

- [ ] **B2 · s0_register**
  - 依赖:A6、A7、P1、P2
  - 验收:manifest 9 列校验(不匹配整批拒收)、SHA-256 精确去重(命中标注关联 doc)、ULID 双 ID(替代时 logical 继承)、magic number 格式探测、隔离路由(疑似重复/密级缺失/白名单外);原件 `raw/` 写一次;发文字号/命名仅告警入报告
  - 验证:`[需 demo up]` ingest → 坏 manifest 整批拒;正常件登记 + ULID
  - 文件:`src/pipeline/stages/s0_register.py`、`tests/test_s0_register.py`

- [ ] **B3 · ParserAdapter + light_parser(结构抽取)**
  - 依赖:A2、A6
  - 验收:`ParserAdapter` 接口;light docx(python-docx 抽结构)→IR、pdf 文本层(pdfplumber)→IR;路由扫描件→`QUARANTINED(E202-DEMO)`、xlsx/图片→`E101-DEMO`;docx 的 page 暂置 null(待 L4 回填)
  - 验证:解析 fixture docx+pdf → IR JSON 有 blocks;扫描件→隔离
  - 文件:`src/pipeline/parsing/adapter.py`、`src/pipeline/parsing/light_parser.py`、`tests/test_light_parser.py`

- [ ] **B4 · s1_parse(渲染 + 解析 + 对齐 整合)**
  - 依赖:B3、SP1、L4
  - 验收:s1 = 渲染件生成(写一次、reprocess 复用)→ light 抽结构 → page_align 回填;渲染失败→`PARSE_FAILED(E204-DEMO)`、超时 5min→`E203`;IR 落 `ir/`
  - 验证:`[需 demo up]` ingest 正常 docx → IR 有 page;`rendition/` 只生成一次
  - 文件:`src/pipeline/stages/s1_parse.py`、`tests/test_s1_parse.py`(rendition.py 复用 SP1)

- [ ] **B5 · s2_qc 七指标 + gate + evidence**
  - 依赖:B1、A2
  - 验收:7 指标(SPEC 表,阈值从 config);任一不达标→`QC_FAILED` + evidence JSON(失败指标 + 页码/条号定位);边缘带 `qc_marginal` 仅标记;指标4 拦 `page=null`
  - 验证:`pytest -k qc`;跳号件→QC_FAILED(指标2 条号连续性)、正常件→通过
  - 文件:`src/pipeline/qc/indicators.py`、`src/pipeline/qc/gate.py`、`src/pipeline/stages/s2_qc.py`、`tests/test_qc.py`

- [ ] **B6 · review_queue 模型 + 处置流**
  - 依赖:A4、A3
  - 验收:`review_queue` 承载 3 类 queue_type(qc_fix/quarantine/meta_confirm);处置 fix/degrade/reject/release/approve 写 `remediation_records` + `pipeline_events`;fix→重入 QC、degrade→DEGRADED_INDEXED、reject→REJECTED、release→重入
  - 验证:`pytest -k queue`(enqueue→fix 重入、degrade 终态)
  - 文件:`src/pipeline/queue.py`、`tests/test_queue.py`

- [ ] **B7 · CLI:ingest / status / queue**
  - 依赖:B1、B2、B5、B6、P3
  - 验收:`demo ingest`、`demo status`、`demo queue list|show|fix|degrade|reject|release` 接通;`queue show` 输出失败指标 + 定位证据 + IR 片段路径 + 页码提示
  - 验证:`[需 demo up]` ingest batch01 → status 表;queue show 打印证据;queue fix 重入
  - 文件:`src/pipeline/cli.py`

- [ ] **✅ 检查点 B(硬门)**:ingest batch01 后文档分别落 QC_PENDING/QC_FAILED/QUARANTINED 无悬挂;正常 docx 页码经渲染件回填、QC4 可评估;`queue show <跳号件>` 给指标+定位;`queue fix` 重入。**覆盖 V2 前半闭环。**

---

## 阶段 C — 结构化、元数据、向量化(T-B)

- [ ] **C1 · s3_structure(装配 clause_tree + chunker)**
  - 依赖:B1、L2、L3
  - 验收:从 IR 装配条款树 + 切块,产出 chunks(chunk_id、clause_path_norm、面包屑、页码跨度、父块仅 PG);表格块仅面包屑前缀(无 LLM 摘要)
  - 验证:`pytest -k s3_structure`;结构化 fixture → 确定性 id
  - 文件:`src/pipeline/stages/s3_structure.py`、`tests/test_s3_structure.py`

- [ ] **C2 · s4_meta L1 规则 + manifest 交叉校验**
  - 依赖:B1、A7
  - 验收:L1 抽发文字号/日期/机构(字典)/标题;与 manifest 交叉校验,冲突→META_REVIEW + meta_confirm 队列;L2 默认关
  - 验证:`pytest -k l1`;冲突件→META_REVIEW
  - 文件:`src/pipeline/meta/l1_rules.py`、`src/pipeline/stages/s4_meta.py`、`tests/test_l1.py`

- [ ] **C3 · version_chain 关系建模**
  - 依赖:C2、P4
  - 验收:从 manifest 解析替代声明;logical 继承;revise_replace/abolish_only;merge/split_replace 命中→队列报"demo 不支持转人工"(原子切换在 D1)
  - 验证:`pytest -k version_chain`;batch02 → 版本关系建模、merge→队列提示
  - 文件:`src/pipeline/meta/version_chain.py`、`tests/test_version_chain.py`

- [ ] **C4 · EmbeddingClient 本地 BGEM3**
  - 依赖:SP2
  - 验收:`EmbeddingClient` 接口 + 本地 BGEM3 实现(dense+sparse 一次产出),batch=64、max_length=1024、指数退避×3;endpoint 实现留 env 桩(M1 不要求跑)
  - 验证:`[离线缓存]` embed 几条 → dense 向量 + sparse dict
  - 文件:`src/pipeline/index/embedding_client.py`、`tests/test_embedding_client.py`

- [ ] **C5 · milvus_io upsert/flush + 冷备 + 混合查**
  - 依赖:A8、SP2
  - 验收:批量 upsert(500/批)→ flush;INDEXED 前 status=staging 不可见;sparse→`SPARSE_FLOAT_VECTOR`;dense/sparse 同落 PG bytea 冷备;混合查 helper(+ dense-only 兜底 + `retrieval_mode`)
  - 验证:`[需 demo up]` upsert → num_entities;staging 不可见;混合查回
  - 文件:`src/pipeline/index/milvus_io.py`、`tests/test_milvus_io.py`

- [ ] **C6 · s5_embed_index(装配)**
  - 依赖:C1、C4、C5
  - 验收:块级嵌入(块失败入队不阻塞同文档其他块;文档级 INDEXING 前检查全块就绪);写入顺序 PG→Milvus upsert→flush→INDEXED;冷备写入
  - 验证:`[需 demo up]` 正常件→INDEXED;PG chunk 数 == Milvus
  - 文件:`src/pipeline/stages/s5_embed_index.py`、`tests/test_s5.py`

- [x] **C7 · CLI:search / meta**
  - 依赖:C5、C2、C6
  - 验收:`demo search` 混合检索 + 默认 `status=effective` 过滤、`--include-superseded`/`--corpus`/`--topk`;结果带四级引用(条款路径/文档+文号/页码/版本+状态);dense-only 兜底时输出 `retrieval_mode`;`demo meta list|confirm` 放行 META_REVIEW
  - 验证:`[需 demo up]` search → 四级引用结果;`meta confirm --batch` 放行 ✅(本地 BGE-M3 真跑:`meta confirm`→INDEXED、hybrid 检索四级引用渲染、`--corpus external→P-EXT` 过滤)
  - 文件:`src/pipeline/cli.py`、`tests/test_cli.py`、`tests/test_search_meta.py`

- [x] **✅ 检查点 C(硬门)**:正常件全链路到 INDEXED;`demo search` 返回带四级引用;S3 单测(归一化/节点正则/chunk_id 确定性/超长续接)全绿。**覆盖 V1 主干。**

---

## 阶段 D — 版本切换、幂等、报告(T-B)

- [x] **D1 · version_chain 原子切换事务 + finalize**
  - 依赖:C3、C6
  - 验收:INDEXED 后原子切换三步(PG `pg_io.supersede_version` 单事务:旧版 version_status+chunks chunk_status→superseded、新版 effective → Milvus 旧版 chunk 标量改 `superseded` 不删[从冷备重建 upsert,零重编码] → 下游通知日志占位);前置校验到 INDEXED + 带 supersedes;自动触发(`_advance_one` 到 INDEXED 即跑)
  - 验证:`pytest -k atomic_switch` ✅(连 PG+Milvus,免模型;切换可重放、no-op 守卫、默认检索排除旧版 + `--include-superseded` 可见)
  - 文件:`src/pipeline/stages/finalize.py`、`src/pipeline/index/corpus_rows.py`(抽出 s5/finalize 共用的块→CorpusRow 映射)、`src/pipeline/index/pg_io.py`(supersede_version)、`src/pipeline/cli.py`、`tests/test_atomic_switch.py`

- [x] **D2 · batch02 联调 + 版本可见性**
  - 依赖:D1、C7、P4
  - 验收:batch02 入库后默认 search 不见旧版;`--include-superseded` 见旧版且标 `superseded`
  - 验证:`[需 demo up]` 两条 search 命令对比(**V4**)✅ 本地 BGE-M3 真跑:真实修订对 182→226 走 ingest→meta confirm→自动 finalize,s0 真实解析 supersedes + 继承 logical,默认 search 仅见 226、`--include-superseded` 见 182(`tests/test_version_demo.py`,模型门控)
  - 文件:`tests/test_version_demo.py`

- [x] **D3 · verify idempotency + reprocess**
  - 依赖:C6、D1
  - 验收:`reprocess` = 全量重跑(重置 REGISTERED + 清 Milvus 孤儿)+ 自动重确认到 INDEXED;`verify idempotency` 断言 chunk_id 集合不变、Milvus `num_entities` 不变、第二次运行有 `duplicate_ingest` 事件
  - 验证:✅ 本地 BGE-M3 / 真栈跑:`reprocess` 182 重跑回 INDEXED 且 chunk_id 集合+Milvus 计数不变(确定性);`verify idempotency` 第二次 ingest SHA 去重、三项不变量通过(`tests/test_idempotency.py`;verify 免模型)
  - 文件:`src/pipeline/verify/idempotency.py`、`src/pipeline/cli.py`、`tests/test_idempotency.py`、`tests/conftest.py`(mini_batch/ingest_index 共享 fixture)

- [x] **D4 · report CLI**
  - 依赖:C6
  - 验收:`demo report <batch>` 输出 JSON + 控制台:解析成功率、QC 一次通过率、各状态计数、锚点填充率、`retrieval_mode`;**不含** `t2_pass_rate`/`t4_pass_rate` 键;快照落库 `import_batches.report`
  - 验证:✅ 真栈跑:CLI 输出四项指标 + retrieval_mode(Milvus 探测)、无 t2/t4 键、快照持久化(`tests/test_report.py`;指标数学免模型/免 Milvus 单测)
  - 文件:`src/pipeline/verify/report.py`、`src/pipeline/index/milvus_io.py`(probe_retrieval_mode)、`src/pipeline/cli.py`、`tests/test_report.py`

- [x] **D5 · M2 占位 CLI**
  - 依赖:A5
  - 验收:`demo verify smoke|replay|reconcile`、`demo rebuild` 打印"非 M1 范围"并非零退出(**禁止伪造断言**)
  - 验证:✅ 四命令均 exit=2 + 明示「非 M1 范围(M2)」,零伪造(`tests/test_cli.py` 参数化,无需 demo up)
  - 文件:`src/pipeline/cli.py`

- [ ] **✅ 检查点 D(总验收 · 硬门)**:V1(全终态无悬挂)、V2(完整闭环 + degrade)、V4(版本切换)、V5(幂等)全过;演示脚本第 1–9 步端到端跑通;`pytest` + `ruff check .` 全绿。

---

## 验收点 → 任务回溯

| 验收点 | 关键任务 | 总验证 |
|---|---|---|
| V1 端到端到终态 | C6 + B2/B3/B4(隔离失败分支) | 检查点 C + D |
| V2 QC 关卡 + 补录闭环 | B5 + B6 + B7 | 检查点 B + D(degrade) |
| V4 版本原子切换 | D1 + D2 | 检查点 D |
| V5 幂等重跑 | D3 + L3(chunk_id 确定性) | 检查点 D |

## 实施约定(每个任务都适用)

- 提交前 `pytest` + `ruff check` 全绿;stage 保持纯函数、互不 import;状态迁移与 events 只经 orchestrator;一切走三接口(`ParserAdapter`/`EmbeddingClient`/`ObjectStore`)。
- 硬契约逐字不动(chunk_id 公式、manifest 9 列、PG 字段名、Milvus schema、写入顺序)。schema/接口 add-only;改动需"先问"。
- ⚠ 值一律从 config 读。关键歧义暂停并提 ≥3 问再动手。
