# 开发日志(devlog)

文档处理管线 · 本地 Demo(M1)的完整开发叙述与决策记录。
**用途**:当需要回看"某个已开发节点为什么这么做 / 当时的决策与踩坑",查这里。
稳定结论已提炼进 `CLAUDE.md`;规格见 `SPEC.md` / `PLAN.md` / `TASKS.md`。

## 工作方式

spec-driven:`SPEC.md`(M1 规格)→ `PLAN.md`(四阶段)→ `TASKS.md`(任务级验收)→ 逐模块实现。
每个模块:实现 → 验证(pytest + ruff,集成测连真栈)→ 停下等用户审批 → 下一个。
决策**逐个**用问答定,不打包;用户常自带技术方案(如页码对齐),给空间先听其思路。
git **直接提交 main**(本地单人 demo)。沟通用中文。

## 关键决策记录(按时间)

1. **范围 = M1**(骨架 + light 解析器跑通 S0–S5,验收 V1/V2/V4/V5);M2/M3 后续。
2. **嵌入默认本地 FlagEmbedding**(BGE-M3),endpoint 留 env;首跑下 ~2GB,文档写离线缓存。
3. **fixtures = 自构造/公开语料**:外规真下载证监会/交易所公开法规,内规自拟,坏样例脚本构造。
4. **页码方案 = 规范渲染件 + 文本对齐**(用户提出):不猜 docx 分页,soffice 渲染 PDF 作页码权威,
   结构仍从 docx XML 抽,`page_align` 单调两指针回填。残留 R5a(信创 soffice)、R5b(docx 自动编号,
   fixtures 用字面条款号规避)。
5. **检索遇阻显式退化 dense-only**(不静默,schema 不变,M2 再启 hybrid)。
6. **Milvus 独立 collection**(不与制度查询 demo 共库)。
7. **batch02 用真实修订对**:信息披露办法 182号→226号 + 官方《修订说明》,226 声明替代 182。
8. **chunker `target_token_min`**:用户审查发现是死参数 → 实现**条内尾块合并**(尾组<min 并回前组,仅同条内)。
9. **clause_tree bis/.1b**:用户审查发现 `normalize` 支持但 `classify_heading` 入口够不着 → 接通 `_ART_NUM`,
   交 normalize 校验,误匹配落项/目。
10. **单段超长条**:用户审查发现无法拆 → 语义边界(项（N）/句末；。)拆 + 字符硬切兜底(标 `oversize`);
    `token_count` 改量内容(不含面包屑/条头续接)。

## 模块日志

### 阶段 A — 底座(全部完成,检查点 A 通过)
- **A1 config**:`load_config()` 把全部 ⚠ 收口 config + env 覆盖。踩坑:机器默认 Python 3.14 无
  grpcio/torch wheel → 装 brew python@3.11 重建 .venv;setuptools≥81 移除 pkg_resources → 钉 `<81`。
- **A2 ir.py**:IR 契约(pydantic,`extra=forbid`,校验器:表格块必带 table、page_end≥page、index 严格升序)。
- **A3 states/stage_base**:13 态 demo 子集(无 REPARSE)+ 合法迁移表 + reprocess + 三态集分区 + 错误码;
  `StageContext`/`StageResult`/`QueueItem`。
- **A4 pg_models + alembic 0001**:11 表(字段名对齐生产,枚举存 String,add-only,含 bytea 冷备)。
  验证用临时 pg16 容器:autogenerate → upgrade → `alembic check` 无漂移。
- **A5 compose + demo up/down + README**:pg16 + milvus2.4 standalone;`demo up`= compose --wait + alembic upgrade。
- **A6 ObjectStore**:本地 FS,key 对齐 MinIO;raw/rendition 写一次,ir 可重写。
- **A7 pg_io**:事务 session、`transition`(改 status + 写 event,带 can_transition 守卫)、字典 seed。
- **A8 milvus_io**:`audit_corpus` 全 schema(dense+sparse + 标量 + corpus_type partition key,HNSW 从 config)。

### 并行流 L — 纯逻辑 TDD(全部完成)
- **L1 normalize**:中文数字→int;条款号→规范形(之一/bis/小数式统一 `N-K`);全半角/去空白。
- **L2 clause_tree**:七类节点正则、栈式建树、虚拟根、clause_path(_norm)、internal_refs。
  审查后补:bis/.1b 接通(决策9);bug:`第X条之一`的`之一`在条**之后**,初版 refs 正则写反了。
- **L3 chunker**:切块六规则 + 确定性 `chunk_id=sha1(dvid|clause_path_norm|seq)[:24]`。
  审查后补:尾块合并(决策8)、单段超长拆 + token_count 量内容(决策10)。
- **L4 page_align**:单调两指针 + rapidfuzz 兜底。bug:`idx = _fuzzy_find(...) or -1` 在命中偏移 0 时
  `0 or -1==-1` 误判未中 → 改显式 None 判断。

### 并行流 P — fixtures(全部完成,`build_fixtures.py --all` 一键重建)
- **P1** 外规真下载:信息披露182 / 非上市公众公司收购 / 上交所上市规则(规章库直链;下载后 pypdf 校验文本层)。
  踩坑:规章库下载按钮 href 由 JS 注入,静态抓不到,改用有直链的篇目。
- **P2** 内规自拟 ×6(python-docx,字面条款号):标准章节条×3 / 大表格 / 超长条款 / 无章通知 / 第X条之一。
- **P3** 坏样例:PIL 图片版扫描件(无文本层)+ 删第八条跳号 docx。
- **P4** batch02 真实修订对 + manifest(9 必填列,226 声明替代 182;修订说明 role=revision_notes 不入 manifest)。

### 并行流 SP
- **SP1 rendition**:soffice 渲染 + pdfplumber 逐页(按 y 剥页眉页脚带)+ 端到端对齐。踩坑:soffice 未装 →
  brew --cask libreoffice(SPEC #5 已批);`soffice_bin()` 支持 env/PATH/.app 定位。真实 docx 命中率 100%。

### 阶段 B — 接入到质检(B1–B7 完成,检查点 B 达成)
- **B1 orchestrator**:stage 注入式轮询(见 CLAUDE.md「Orchestration」)。
- **B2 s0_register**:manifest 9 列(整批拒收)、SHA-256 去重、magic number 探测、ULID 双 ID + 替代 logical 继承
  (按 source_filename,新增列走迁移 0002)、隔离路由、原件写一次。踩坑:SQLAlchemy 无 relationship 不自动排
  FK 插入序 → flush;ULID `[:8]` 截断 = 时间戳前缀,同毫秒相撞 → 用完整 ULID。
- **B3 light_parser + adapter**:`ParserAdapter` 边界;docx(python-docx 按序段落+表格,page=None 待对齐)、
  pdf(pdfplumber 逐页 + 字符密度判扫描件 E202)。
- **B4 s1_parse**:渲染件(写一次/reprocess 复用)→ 抽结构 → page_align 回填 → IR 落库;E204/E202/E101。
- **B5 s2_qc**:7 指标 + gate + evidence;QC_FAILED(E301)。踩坑:边缘带对"阈值=100%"(页码锚点)和
  "阈值<ε"(文本质量)退化会误标完美文档 → 这俩关边缘带。

#### B 段审查修复(`bfe2cb7`,逐项查 B1–B5,各带回归测试)
- **状态缺口**:s1 加 `start()` 薄 stage 补 `REGISTERED→PARSING`——状态机无 `REGISTERED→QC_PENDING`,
  而 s1.run 建模的是 `PARSING→QC_PENDING`,原先没 stage 推进登记态;PARSING 由此成落库的"解析中"态(崩溃可重入)。
- **入队/迁移原子性**:orchestrator 原本先单独入队再单独迁移,两事务;迁移守卫失败会留孤儿 open 队列行。
  → `pg_io.transition` 加 `queue_row` 参数,入队与迁移同事务,要么全成要么全滚。
- **批次幂等**:s0 `ImportBatch` 改 get-or-create——同 batch_id 重跑不撞主键,SHA 去重得以跳过已登记件
  (保住 doc_version_id → chunk_id 幂等根);中途崩溃可拿同 batch_id 续跑。
- **manifest 精确列校验**:SPEC §S0「缺列/多列整批拒收」——原先只查缺列,多列漏网 → 改列集合精确匹配。
- **issue_date 漏写**:manifest 的 issue_date 归一为 `date`(openpyxl 日期格给 datetime,文本格走 fromisoformat)
  写入 `DocVersion.issue_date`;解析失败按"仅告警"置空入报告。
- **测试加固**:soffice "二进制找得到 ≠ 能渲染"——`tests/conftest.py` 加 session 级探测 fixture,用同一
  `render_pdf` 真渲一次,present-but-broken → skip 而非 flaky fail(环境噪声与代码回归分离)。
- **隐式依赖**:Pillow 此前靠 pdfplumber 传递引入 → 显式声明进 dev extra。

- **B6 review_queue 处置流(`queue.py` `dispose()`)**:5 处置(fix/degrade/reject/release/approve)各为三写
  原子单元(迁移+events / remediation_records / 关单)。两层校验:queue_type↔disposition 相容(本层)+
  `can_transition`(state 级,非法→ValueError 整事务回滚)。原子性需 **`transition` session 注入**(`session=`
  加入调用方事务)——即 turn 2 选 A 时搁置的「选项 B」,B6 是其真用武之地。degrade→DEGRADED_INDEXED 按状态机
  是直达终态(SPEC:58),"降级件真出 degraded chunk"留到检查点 D(已标记,B6 不解)。
- **B7 CLI(`cli.py`:ingest/status/queue)**:装配根 `_build_stages()` 接真 stage(REGISTERED→s1.start、
  PARSING→s1.run、QC_PENDING→s2.run;s0 非轮询)。`ingest`=register_batch + run_until_idle;queue 处置调
  `dispose()` 后 `_advance_one` **只推进本件**(不扫全库);`queue show` 渲染失败指标 + `hint`(条号+页码定位)
  + IR 路径。踩坑:typer 的 `Argument()/Option()` 默认值被 ruff B008 误判 → 配 `extend-immutable-calls`。
  手动 e2e:clean+跳号 docx → clean 落 STRUCTURING(过全 7 项)、跳号落 QC_FAILED+队列,show 打"第2条后缺第3条
  (第1页)"。注:过 QC 件停 STRUCTURING(C 段前无 s3 stage),非检查点 B 措辞里的 QC_PENDING。

### 阶段 C — 结构化 / 元数据 / 向量化(C1–C7 完成,检查点 C 达成)
- **C1 s3_structure**:STRUCTURING 阶段薄装配——载 IR → `chunker.build_chunks`(L3 已做树+六规则+确定性
  chunk_id)→ ChunkSpec 映射 Chunk 行 → `pg_io.replace_chunks`(同事务删旧插新,确定性 id 使重跑幂等)→
  META_REVIEW。chunk_status=staging;父块/表格块入 PG(Milvus 排除留 s5);degraded=False;oversize 无列不持久化。
- **C2 s4_meta + l1_rules**:`meta/l1_rules.py`(纯)抽 发文字号/日期/机构(字典)/标题 + 交叉校验
  (冲突=L1 候选非空且 manifest 非空值不在候选中;日期成员判定;文号统一括号变体)。s4 均 → META_REVIEW,
  冲突另入 meta_confirm 队列。踩坑:文号/日期须**逐块**匹配——拼接后 `strip_ws` 粘连标题,文号正则贪婪前缀
  会吃进标题。STRUCTURING 接**复合** `cli._structuring`(s3 副作用 + s4 决定终态),在装配根组合以守
  "stage 互不 import"。`pg_io.get_issuers` 加。L2 默认关。
- **C3 version_chain**:`meta/version_chain.py`(纯)解析 supersedes → 关系(demo 编码:空/单文件 revise_replace
  /`abolish:`abolish_only/多文件 merge;split=批次内 ≥2 新件指向同一旧件)。s0 `_resolve_logical`→`_resolve_version`:
  revise 继承 logical、abolish 新 logical+记被废止版、merge/split 登记 + meta_confirm 队列"demo 不支持"(s0 首次写
  队列)。原子切换留 D1。**发现未修**(超范围):s0 隔离件不写 review_queue → `queue list` 不可见,待补。
- **C4 EmbeddingClient**:`index/embedding_client.py` ABC + 本地 BGEM3(FlagEmbedding,懒加载,一次 encode 出
  dense+sparse,batch/max_length/retries 从 config,指数退避)+ endpoint 桩。**环境坑**:hf-mirror 在此网络 308
  跳回 HF、直连慢 → 用 **modelscope** 拉 bge-m3,经 `PIPELINE_EMBEDDING_MODEL`(config 新增 env 覆盖)指本地目录 +
  `HF_HUB_OFFLINE=1` 加载;真模型测试 gate 在该 env(未设秒 skip,绝不联网下载)。
- **C5 milvus_io**:upsert(`upsert_batch`/批,不自动 flush)+ flush + count/delete + 混合查(dense+sparse +
  RRFRanker,默认 status==effective 过滤;hybrid 失败/空 sparse → dense-only + `retrieval_mode` 兜底)+ 冷备
  serialize(dense float32 / sparse JSON)。search/count 用 Strong 一致性。**SP2 风险退**(hybrid 真命中)。
- **C6 s5_embed_index**:embed(嵌入非-parent + 冷备写 PG + Milvus upsert staging)→ index(flush + count== 校验 +
  从冷备重 upsert effective + flush + 翻 chunk_status → 终态)。写序 PG→upsert→flush→INDEXED;parent 仅 PG。
  踩坑:**stage 只返回 next_state 不写 status**(orchestrator 应用),s5 测试须经 orchestrator 驱动;且 ingest/queue
  处置至多到 META_REVIEW 人工闸即停、**到不了 s5**,故用轻 ctx(`_worker_context` 留 C7 meta confirm)。
- **C6 并入 degrade 修复**(B6 遗留):degrade 不再直达空终态——`DocVersion.degraded`(迁移 0003)+ states
  (QC_FAILED→STRUCTURING、INDEXING→DEGRADED_INDEXED)+ dispose 置 degraded 重入 STRUCTURING + s3 chunk 标 degraded
  + s5.index 按 degraded 选终态。降级件走完整索引。
- **审查修复**:s4 META_REVIEW 全件入 meta_confirm(统一队列唯一入口,无冲突件 conflicts=[]);s0 SHA 去重在既有
  doc 写 `duplicate_ingest` pipeline_event(非迁移审计,report 未持久化否则无痕);chunker `oversize` 落库
  (Chunk 加列,迁移 0004,s3 映射,此前被丢弃)。
- **C7 search / meta CLI**(纯装配,无新契约):`demo search` 用 `EmbeddingClient` 编码 query → `MilvusIO.search`
  (C5 混合查/dense-only 兜底)→ 命中后回 PG 批量补 `DocVersion`(title/doc_number/version_status)凑齐**四级引用**
  (文档+文号 / 条款路径 / 页码 / 版本+状态),`degraded` 显式标注;`--corpus internal→P-INT / external→P-EXT` 映射,
  非法值在触栈前退 1;dense-only 兜底打 `retrieval_mode`。展示格式 = **带标签分块**(用户选,演示讲解清晰)。
  `demo meta list`(列 meta_confirm,冲突件高亮 `field/manifest/L1` 明细)+ `meta confirm <id|--batch>` 复用 `dispose`
  的 approve 处置(approve→EMBEDDING)再 `_advance_one` 推到 INDEXED——这正是 C6 预留 `_worker_context`(含 embedding+
  milvus)的用武之地(ingest/queue 处置至多到 META_REVIEW 人工闸用轻 ctx)。**`meta confirm` 设计为 doc-centric**:
  一件即便有 **多条** open meta_confirm(merge/split 件 s0 登记 + s4 元数据各写一条)也只 approve 迁移一次、其余关联行
  随之关单(`_close_extra_meta` 写 remediation 不再迁移),`--batch` 按 doc 去重保序——否则首行放行后 doc 已离 META_REVIEW,
  兄弟行会悬挂、INDEXED 后 `meta list` 仍显示待确认(C3 在 memory 记下的 C7 必处理点)。验证:本地 BGE-M3 真跑
  `meta confirm`→INDEXED + hybrid 检索四级引用渲染 + 双行关联关单(`test_search_meta.py`,模型门控);PG-only/无栈测试
  (meta list / 参数互斥 / 非法 corpus / 非 meta_confirm 拒绝)进常规套件。踩坑:Milvus `page_start` 未对齐写 0
  (INT64 不收 None)→ 渲染按 falsy 判「未对齐」;同 alias 重复 connect 幂等(CLI 与测试 fixture 各 connect "default"
  安全);s5 对无 chunk 文档优雅(`if chunks:` 守卫不加载模型),故 chunkless 件可不触模型验推进。
- **C7 审查修复(include_superseded 漏 staging)**:用户审查发现 `milvus_io.search` 原实现 `include_superseded=True`
  时**整条删掉** `status` 过滤,等于把 `staging`(INDEXED 前半成品)也放出来,违反「staging 不可见」硬契约
  (写序 PG→upsert→flush→INDEXED,翻 effective 前不暴露)。修正:`include_superseded` 不再去过滤,而是把可见集从
  `status=="effective"` 放宽为 `status in ["effective","superseded"]`——staging 在任何情况下都不可见,旗标只多放
  superseded 旧版(V4 本意)。`test_milvus_io` 原 `test_staging_invisible_until_effective` 固化了错误行为(断言去
  过滤后 staging 可见)→ 改为 `test_staging_invisible_even_with_include_superseded`(staging 带旗标仍不可见)+ 新增
  `test_superseded_visible_only_with_include_superseded`(superseded 默认不可见、带旗标可见);连真 Milvus 验 `in` 表达式。
- **C7 审查修复(endpoint 桩 fail-fast)**:用户审查发现 `EndpointClient` 只在 `embed()` 抛 `NotImplementedError`,而
  `embedding.mode` 是 config 合法值(`Literal["local","endpoint"]`)、`from_config` 会据此选到它——一旦部署切 endpoint,
  要先白跑 S0–S4,到 S5 嵌入那刻才崩且报错弱。修正:把失败前移到 `EndpointClient.__init__`(带指引:改 `mode="local"`),
  使 `_worker_context`/`from_config` 一构造客户端(search/meta confirm/ingest 命令开头)就清晰失败。ABC 细节:必须保留
  `embed` 定义,否则实例化先抛 `TypeError`(抽象方法未实现)盖过此处。测试改 `test_endpoint_stub_fails_fast_at_construction`
  + 新增 `test_from_config_endpoint_fails_fast`(model_copy 改 mode=endpoint 验 from_config 即抛)。endpoint 真实现仍属 M2。
- **C7 审查修复(cache_dir 未接线)**:用户审查发现 `config.embedding.cache_dir` 被 `_apply_env`(HF_HOME env→cache_dir)
  或 settings.toml 备着,但 `LocalBGEM3Client._load()` 只传 `model_name`——离线缓存路径形同虚设(经 settings.toml 设而不设
  HF_HOME env 时完全失效)。修正:`BGEM3FlagModel(model_name, use_fp16=False, cache_dir=cfg.cache_dir)` 透传(经查 1.4
  的 M3Embedder 接受 `cache_dir`);None=用 HF 默认缓存,model_name 为本地绝对目录时不参与加载(传 None 无害)。测试
  `test_local_load_passes_cache_dir`:monkeypatch 模型类(免载 2.3GB)验 cache_dir 透传到加载器。
- **C7 审查修复(迁移纳入 lint)**:用户审查发现 `alembic/versions` 被 pyproject `extend-exclude` 掉,4 个迁移
  (0001–0004,含本段新增的 0003/0004)有 I001 import 排序 + E501 行宽违规(共 38 个),被 exclude 静默藏起、债务累积,
  影响日后把迁移纳入 CI。**决策:移除 exclude、纳入 `ruff check .`**(用户选)。`ruff check --fix` + `ruff format`
  一键清完(import 重排 + 长 `op.add_column` 折行 + 引号归一,**纯格式、DDL 语义不变**,`alembic check` 仍无漂移)。
  约定写进 CLAUDE.md:autogenerate 后跑 `ruff check --fix alembic/versions && ruff format alembic/versions` 再提交
  (模板违规全可自动修)。0001 因 11 表大初始迁移 format 改动达 ~595 行,但同属纯格式。

### 阶段 D — 版本切换 / 幂等 / 报告(D1 完成,D2–D5 待做)
- **D1 finalize 版本原子切换**:`INDEXED` 是终态、版本切换改的是 `version_status`(独立标量)非 `pipeline_status`,
  故**不新增状态**、不动状态机硬契约;是 INDEXED 后的**带外操作**,由 cli `_advance_one` 推进到 INDEXED 后**自动触发**
  (用户选),不被 orchestrator 轮询。新版带 `supersedes_version_id` → 三步置旧版 superseded:① PG 原子事务
  (`pg_io.supersede_version`:旧版 version_status + 其 chunks chunk_status → superseded,新版 effective 幂等,单事务可重放)
  ② Milvus 旧版 chunk 标量改 superseded——Milvus 2.4 改标量只能整条 upsert,故**从 PG 冷备重建整行 upsert + flush,零重编码、
  不 delete**(旧版仍可被 `--include-superseded` 检索)③ 下游通知 `logger.info` 占位。写序 PG→Milvus,PG 侧原子使整体可重放
  (Milvus 失败重跑 finalize 从冷备幂等重做)。**抽 `index/corpus_rows.py` 共享层**:s5 与 finalize 都要"PG chunk+冷备→
  CorpusRow"映射但两者是 stage 不得互 import → 放 index/ 共用(`build_rows`/`rows_from_cold`/`indexable_chunks`),s5 重构
  复用、删本地 `_rows`/`_issuer_level`/`_indexable`。范围:任何到 INDEXED/DEGRADED_INDEXED 且带 supersedes 触发
  (revise_replace 的 V4 + abolish_only)。验证:`test_atomic_switch.py`(连 PG+Milvus,**免模型**——走冷备无需编码;3 测:
  切换双置 superseded + 默认检索排除旧版/`--include-superseded` 可见、可重放、no-op 守卫);s5/search_meta 经模型重跑确认
  重构+钩子无破坏。踩坑:同毫秒 ULID 仅末位不同,`dvid[:22]+suffix` 两版 chunk_id 相撞 → 用 tag 前缀(devlog ULID 坑复现)。
- **D2 batch02 联调 + 版本可见性(V4)**:用真实修订对(`ext_xxpl_182.pdf` 182 → `ext_xxpl_226.pdf` 226,226 manifest
  声明 supersedes 182)走**完整真实路径**:`register_batch`(真实 s0 解析 supersedes + 继承 logical)→ orchestrator
  run_until_idle 到 META_REVIEW → `cli._approve_doc`(真实 meta confirm 路径,含 `_advance_one` 自动 finalize)→ INDEXED。
  断言:226.supersedes_version_id==182.dvid + 同 logical、182 置 superseded(PG+chunk);**默认 search 仅命中 226、
  `--include-superseded` 见 182**(V4)。为聚焦两件外规 PDF(且免 docx soffice),`_mini_batch` 从 fixtures 各抽**单件**
  临时批(原 manifest 行不变,9 列契约不破)——避免整 batch01 12 件解析(慢)。验证:本地 BGE-M3 真跑 1 测过(68s,
  含两 PDF 解析+嵌入+两次检索);先用轻 ctx 探得 182 真实 PDF 过 QC、67 块到 META_REVIEW(de-risk 真实链路)。模型门控。
- **D3 verify idempotency + reprocess(V5)**:`verify/idempotency.py` `check_idempotency`——幂等根是 s0 SHA-256
  精确去重(二次 ingest 同文件返回 DUPLICATE 不新建 doc + 写 `duplicate_ingest` 事件)。快照「二次 register_batch」前后:
  断言 chunk_id 集合不变(确定性 `sha1(dvid|path|seq)`)、Milvus `num_entities` 不变(全集+逐 doc)、新增 ≥1 条
  duplicate_ingest 留痕——**不重嵌入、不需模型**(走 s0 去重)。`cli` 起 `verify` 子命令组(D5 再加 M2 占位)。
  **`reprocess <dvid>`**(用户选「重跑到 INDEXED」):清孤儿(`milvus.delete` 删投影,PG chunk 由 s3 replace_chunks
  覆盖)→ 重置 REGISTERED(状态机 REPROCESS_RESET_FROM)→ `_advance_one` 到 META_REVIEW → `_approve_doc` 自动重确认
  到 INDEXED(+finalize)。确定性 chunk_id 使全量重跑同 id 覆盖、幂等。验证:test1 verify(**免模型**:seed 已索引件
  +磁盘文件 SHA 匹配+manifest,跑 check;三项不变量 + 无新建 doc)/ test2 reprocess(模型门控:真实 182 ingest+index
  →reprocess→回 INDEXED 且 chunk_id 集合+Milvus 计数不变)。**复用**:`mini_batch`/`ingest_index` 提到 conftest 共享
  (D2/D3 同用),test_version_demo 一并改用。已知边界:reprocess 一个已 superseded 的旧版会被 s5 重置 chunk_status=
  effective(版本可见性误恢复)——edge,正常 reprocess 的是新版,留记不解。
- **D4 report**:`verify/report.py` `build_report`(纯读)从 pipeline_events(状态历史)+ chunks 算四项 + retrieval_mode:
  解析成功率=到 QC_PENDING / 进 PARSING(事件判定,排除 S0 未入解析的隔离件)、QC 一次通过率=直达 STRUCTURING 且历史
  无 QC_FAILED / 到 QC_PENDING、各状态计数、锚点填充率=page_start 非空 chunk / 总 chunk。**retrieval_mode** 经新增
  `milvus.probe_retrieval_mode`(合成非零向量发 topk=1,hybrid 成功→hybrid / 受阻→dense_only,免模型免真查询)。
  **SPEC 决策 1**:JSON **不含** `t2_pass_rate`/`t4_pass_rate` 键(不留半成品字段,M2 再加)。比率分母为 0 → None(避免
  0% 误读)。cli `report <batch>` 控制台摘要 + JSON,快照落 `import_batches.report`(A4 预留列)。验证:test1 指标数学
  (**免模型/免 Milvus**,ctx.milvus=None,4 件不同状态历史精确验三率 + 无 t2/t4 键)/ test2 CLI(Milvus-guarded 免模型,
  验输出 + retrieval_mode 探测 + 快照落库)。
- **D5 M2 占位**:`verify smoke/replay/reconcile` + `rebuild` 共用 `_not_m1(name)`——打印「属 M2,非 M1 范围(未实现;
  按 SPEC 禁止伪造断言)」+ `Exit(2)`(非零)。**SPEC 边界:禁伪造 M2 断言**(smoke/replay/reconcile/rebuild),宁可
  非零退出占位也不假装通过。验证:test_cli 参数化 4 命令 exit≠0 + 输出含「M2」「非 M1 范围」(无需栈,命令即时退出)。

### 检查点 D 走查(真 fixtures + 本地 BGE-M3 + 真栈端到端)
跑通演示脚本全步骤(ingest batch01 → status/queue list/show → meta confirm --batch → queue degrade+confirm →
status → search → report → verify idempotency → batch02 切换 + 两条 search)。**V2/V4/V5 完整闭环真跑通过**;走查初见整批
分布与 SPEC「~10 INDEXED」有差(4 件意外 QC_FAILED),抓到 3 项;**发现 1、2 均已修(含「做全小数规则」)**,
**修复后 batch01 = 9 INDEXED + 1 DEGRADED_INDEXED + 1 QUARANTINED、QC_FAILED 清零**,V1 干净达成。
- **发现 1(已修)QC 指标 3 误报插入条**:`hierarchy_legality` 要求同级条号严格递增,`_base("第四条之一")`=4 与前面
  `第四条`=4 相等 → 误判违规。`第四条之一` 是解析器明确支持的合法插入条(决策9),int_baoxiao(专为覆盖此边界的
  fixture)被 QC 误杀。**修**:`hierarchy_legality` 改用 `_key(num)` **变长整数元组**键(`"4-1"`→(4,1) > `"4"`→(4,);见
  发现 2 做全后 `_key` 统一按「.」「-」分段)做 `k <= last` 比较——插入条不误判,真重复/逆序仍被抓;`clause_continuity`
  用 `_base`(首段)。回归测试 `test_inserted_clause_not_flagged_by_hierarchy` + `test_hierarchy_catches_duplicate_clause`;
  真实 fixture 确认:int_baoxiao 经 `queue fix`(以修复后 QC 重跑)→ 过 QC → meta confirm → INDEXED(顺带演示 V2 fix→INDEXED 闭环)。
- **发现 2(已修,「做全小数规则」)真实外规 PDF 不干净过 QC**:根因都在解析器**下游 `clause_tree`**(IR 边界后,
  与换不换 DeepDoc 无关),分两类——
  - **ext_fei(证监会令102号,真 47 条)**:正文「第N条」跨**法**引用(`…第一百九十六条、依照《证券法》…`)碎片落块首被当条标题
    → 撑出假缺口。修:`第X条` 紧跟枚举标点 `、，,;；`(`_REF_PUNCT`)即判引用列举、非条标题。→ 7/7 过。
  - **ext_sse(上证发〔2013〕26号,143 页交易所规则)**:体例用**变深小数编号**(`2.17`/`3.1.2`/`3.2.15`,章[.节].条),
    `第X条` 正则识别 0 条;另有目录页 + 文内 `第 N.M.K 条` 小数引用。**做全**:① `classify_heading` 加小数分支(号后强制空白
    避开 `2.17%`/`1.5亿`;`(?!条)` 排除 `10.1.3 条…` 小数引用碎片;号取**全小数** `10.1.3` 保排序信息)② `_key` 改**变长元组**
    (`10.1.3`→(10,1,3))使跨节排序正确(节点未识别也不误判)、`_base` 取首段 ③ `_TOC_LEADER`(≥4 连续点/省略号)剥目录条目
    (避免目录章节与正文重复)。→ ext_sse 0→**401 条**、7/7 过。回归测试覆盖小数识别/误报防护/目录剥离/跨节排序。
    残留小风险:小数分支可能在他文数字子列表误触发(靠号后空白 + M2 golden set 把关);已记。
- **发现 3(次要,已记)**:`queue degrade` 单独只到 META_REVIEW(重结构化),需再 meta confirm 才到 DEGRADED_INDEXED
  (两步);Milvus `num_entities`(108)> PG 块数是 upsert churn 未压实计数语义(V5 稳定性不受影响,M2 reconcile 处理)。

## 已建链路与下一步

全链路:`demo ingest`(s0 登记+版本关系+去重审计)→ s1(渲染+解析+对齐)→ s2(七指标质检)→ STRUCTURING 复合
(s3 切块 + s4 元数据校验)→ META_REVIEW(全件入 meta_confirm 人工闸)→ `meta confirm`(approve)→ EMBEDDING(s5 嵌入+冷备)
→ INDEXING(Milvus 索引 + 翻 effective)→ INDEXED → **finalize**(带 supersedes 自动把旧版置 superseded);`search` 混合查出
四级引用(默认 effective,`--include-superseded` 见旧版);degrade 重入索引终于 DEGRADED_INDEXED。失败件入统一队列、`dispose`
处置。**检查点 B/C 达成;C1–C7 + D1–D5 完成**(V1 主干 + V2 + V4 版本切换 + V5 幂等 + report;M2 占位)。
**检查点 D 余项**:演示脚本第 1–9 步端到端手动走查(V1 全 12 件终态无悬挂 / V2 完整闭环含 degrade 的整批演示)——
自动化测试已覆盖 V4/V5 全程 + V1/V2 关键分支,整批 demo 走查是终验人工门。

**状态快照(截至检查点 D 走查 + 发现1/2 修复 + 做全小数规则)**:全套 215 passed / 9 skipped(不带
`PIPELINE_EMBEDDING_MODEL`:9 个模型门控测试 skip;带时全跑)· `ruff check .` 全绿(含 alembic/versions)· 迁移至 0004
无漂移 · 检查点 A/B/C 达成、D 自动化部分全绿。**检查点 D 走查**:V2/V4/V5 真栈端到端跑通;3 项发现的 1、2 均已修
(指标3 插入条误报 + clause_tree 跨法引用过滤 + 小数编号做全[目录剥离/全小数排序/小数引用过滤]),**真实 fixture 全部
端到端入库:batch01 = 9 INDEXED + 1 DEGRADED_INDEXED + 1 QUARANTINED、QC_FAILED 清零,V1 干净达成**。提交锚点:A 段早期 / B 段
(B6 c1f1bd7·B7 9e9e737)/ C1–C3(601ba3c·fffee03)/ C4 e457f37 · C5 7d3b1e0 · C6 6b98bf0 · 审查修复 cb460f4。
**待修小项**:s0 隔离件(格式/密级)只置 QUARANTINED 不写 review_queue → `queue list` 不可见(B2 缺口,待补)。

## 测试与运行约定

- venv:`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`。
- 集成测试连真栈,栈未起则 skip;各自按 batch_id 反 FK 序清理。
- 迁移 add-only:autogenerate → upgrade → check 无漂移。`alembic/versions` 已纳入 ruff lint,autogenerate 后须
  `ruff check --fix alembic/versions && ruff format alembic/versions`(违规全可自动修,纯格式)再提交。
- 行宽 100,ruff(E/F/I/UP/B);CJK 注释易超行,放独立行或缩短。
