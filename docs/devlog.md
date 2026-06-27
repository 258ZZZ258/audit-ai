# 开发日志(devlog)

文档处理管线 → audit-ai monorepo 的**按时间轴(阶段 A/B/C/D/M2/M3/W)**完整开发叙述。
**用途**:回看"某节点为什么这么做 / 当时的决策与踩坑"的全过程。
> **按模块查更快**:各模块的蒸馏记忆已拆到包内 `*_devlog.md`(见 `CLAUDE.md`「模块开发记忆索引」);
> **audit-ai 升格**(Step 0–7)叙事在 `migration_devlog.md` + `CP-009`(本文未含升格阶段)。
稳定结论已提炼进 `CLAUDE.md`;规格见 `file-processing-workflow-docs/SPEC*.md` / `file-processing-workflow-docs/PLAN*.md` / `file-processing-workflow-docs/TASKS*.md`。

## 工作方式

spec-driven:`file-processing-workflow-docs/SPEC.md`(M1 规格)→ `file-processing-workflow-docs/PLAN.md`(四阶段)→ `file-processing-workflow-docs/TASKS.md`(任务级验收)→ 逐模块实现。
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
  队列)。原子切换留 D1。**发现**(超范围,**M3 末 B2 已补**):s0 隔离件不写 review_queue → `queue list` 不可见。
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

### 阶段 M2 — 验证套件(检查点 M2 达成,V3/V6/V7)
spec-driven 再走一轮(`SPEC_M2`/`PLAN_M2`/`TASKS_M2`,各停下评审)。**立项反转**:据 M1 走查证据,**DeepDoc 降可选/留独立轮**
(真实 PDF 痛点在 clause_tree 下游,与解析器无关),M2 主体 = 验证套件 + golden set。
- **M2-0 config**:`[verify]` 段 + `VerifyConfig`(t2_head=30/hit@50/t4_window=1/fuzzy=92,⚠)。
- **A2 T4 锚点回放(V3)**`verify/anchor_replay.py`:逐非 parent chunk 在原件页 `[page_start-W..page_end+W]`(复用
  `rendition.page_texts` 同 page_align)精确子串 / rapidfuzz≥阈值定位;**is_table/degraded 豁免**。口径由 Plan 阶段实测探针
  定死(批 01:非表格 602/620 精确,18 近似全 fuzz≥92 救回,表格豁免→100%)。
- **A3 对账**`reconcile.py`:逐 doc PG 块数 vs `MilvusIO.count(dvid)`(query-by-PK 准确,**非**虚高 num_entities);不平 E701 +
  冷备重灌。**A4 rebuild(V6)**`rebuild.py`:`create_collection(drop_existing)` → 遍历全 doc 从冷备零编码回灌(纯 insert,
  count 干净)。两者复用 `corpus_rows.rows_from_cold(status=None)`(按各 chunk 存储 status 还原)。
- **A1 T2 冒烟(V7)**`smoke.py`:合成查询=标题+首条款前 N 字 → search(topk=hit_at);断言 hit@N + `SearchResult.expr` 含
  `status=="effective"` 过滤位(E801/E802)。
- **B1 golden set**:`tests/golden/*.json` ×5(build_tree 镜像,人工核对)覆盖多级章节条/插入条 4-1/虚拟根;`test_golden_set`
  断言 F1=1.0(免模型/免 soffice,只用 docx IR blocks)。
- **C1 report + C2 finalize(设计转折)**:初版让 report 现场跑 smoke → 无模型时触发模型加载/联网卡住。改为 **finalize 在
  INDEXED 时跑 T2/T4 并留痕 `pipeline_events.detail['verify']`(§9),report 只聚合读取**(不在 report 加载模型)。cli
  `_advance_one` 钩子改为**所有** INDEXED 件都调 finalize(原仅 supersedes 件)。**C3** `demo verify smoke/replay/reconcile` +
  `rebuild` 替换 D5 占位为真实现(退出码非零当且仅当真失败)。
- **M2-D 真栈走查**:`demo verify replay` 100%(620/620 含 143 页 ext_sse,豁免 11)· reconcile 一致 · `rebuild` 631 块零编码
  回灌 count 631→631 干净 · `verify smoke` 100%(9/9)。**走查发现:smoke 须排除 superseded 件**(182 被 226 替代后默认检索
  不可见,测它必 E801)→ `_indexed_dvids(effective_only=True)`;replay 不排除(旧版锚点不变仍可回放)。
- 验证:A2/A3/A4/B1 免模型连真栈过;A1 + C1/C2 e2e(finalize 留痕→report 聚合 t2/t4=1.0)本地 BGE-M3 真跑过。
- **M2 审查修复(推进失败静默 exit 0)**:用户审查发现 `_advance_one` 捕获 stage 异常后只打印「推进中止」并 break、
  不抛错,`_approve_doc`/`reprocess`/`_do_dispose` 随后仍走成功路径 → 文档可能停在 EMBEDDING/INDEXING/META_REVIEW
  但 CLI **exit 0**,违反「人工闸放行后达 INDEXED / 验证命令可靠表达结果」契约。修:`_advance_one` 回带
  `error`(中途异常即记,非静默);`_approve_doc` 返回**是否到终态** bool;`meta confirm` 聚合(任一未达 INDEXED →
  exit 1)、`reprocess`(final ∉ INDEXED 态 → exit 1)、`_do_dispose`(推进异常 → exit 1)。finalize 仅在无 error 且到
  终态才跑。`test_queue_degrade_via_cli`(seeded 件无 IR,s3 中止)断言从 exit 0 改为 **exit 1 + 「推进失败」**(处置副作用
  仍生效);成功路径(meta confirm/reprocess→INDEXED→exit 0)经模型门控测试确认未破坏。

### 阶段 M3 — E1 义务打标 + report 全量打磨(代码完成,V8 达成;检查点 M3 待 live)

spec-driven 四阶段(`SPEC_M3`/`PLAN_M3`/`TASKS_M3`,各停审)。立项:E1 是富集链起点(为比对智能体预热),
零 LLM 正则、IR 边界下游——证明加富集步不动状态机/解析器/默认零 LLM。

- **Plan 探针定方向(非拍脑袋)**:batch01 真文本统计「应」分布——690 个「应」中 应当 637(92%),前缀陷阱仅
  相应(15),后缀(应用/应急)近乎不现。据此词表初值固化进 `config/obligation.yaml`,后缀排除**不加**。
- **A1 matcher**:`match_obligation(text,cfg)` 整词 markers + bare「应」边界(前缀排除)。反馈后再调:前缀排除
  **统一作用于 应当 marker**(修 对应当/相应当 子串误命中);3329 真单元验证「含『应当』被排除判 False」0 条(零回归)。
- **A2 装配**:`_structuring` 改 **clear→s3→tag→s4**(clear 先于 s3 `replace_chunks` 避 `clause_tags` FK);E1 异常
  `_safe_e1` 吞掉不阻断终态。**连带**:管线给每件写 clause_tags → 修 4 个 ingest 测试 teardown(FK 子先删)。
- **B1 golden / V8**:人工据语义独立标注 22 正 + 12 负(batch01 真条款,非 matcher 输出),`test_obligation_golden`
  断言 **precision=1.0 / recall=0.955 ≥0.90**。唯一 FN=「用印须填写」(bare 须)——数据查 须全 corpus 仅 6 次且含
  无须(否定义务)陷阱,naive 加会造假阳,**故意不加**留 honest FN 不过拟合 golden。
- **C1/C2 report 打磨**:义务覆盖 / 队列处置 / 版本链 / 按语料 P-INT·P-EXT 拆 + JSON 落 `reports/<batch>.json`,
  纯 PG 聚合不加载模型;e1 关→义务覆盖 None。
- **D1 验收 + 检查点 M3 达成**:全套 **263 passed / 0 skipped**(本地 BGE-M3,11 个 model-gated 全跑;**V1–V8 全过**)·
  `ruff check .` 全绿 · `alembic check` 无漂移。**真 CLI 端到端走查**:ingest 2 件内规(baoxiao/yinzhang)→ INDEXED,
  `demo report` 出**义务覆盖 42.9%(6/14 块标 is_obligation)**/版本链 effective=2/队列 meta_confirm[closed=2]/[P-INT]
  三率 100% + JSON 落文件;`demo search`「报销应当符合开支标准」→ 第四条 四级引用(hybrid)。走查后 FK 序清干净(残留 0)。
  提交锚点:M3-0/A1/A2/B1/C1·C2 + 文档收口。
- **M3 续(可选收尾,用户选)**:**#1 search 出义务标**——hit 回 PG 查 `clause_tags(is_obligation)` 注释 `[义务]`,
  不动 Milvus schema(`_obligation_chunk_ids` 批量查 + `_print_hit` 标);decision B 由「不做」反转为做。**#2 bare 须 泛化**——
  matcher 的「应单字边界排除」泛化为可配 `bare_chars`(应/须),`exclusions` 加 `无须/毋须`(否定义务陷阱;不排会把
  `无须审批` 误标),**golden recall 0.955→1.0**(`用印须填写` FN 消除)。免栈全验 + 模型门控子集(search+管线)10 passed。

### 阶段 W — Web 工作台 + META_REVIEW 双模式 + 目录区域化(2026-06)

Web 工作台落地(`src/pipeline/web/`,标准库 HTTP,thin shell:PG 权威 / Milvus 投影,复用同一套
queue/状态机/`reprocess_to_indexed` 域函数,不复刻 CLI 逻辑)。演示要"无冲突件免逐篇点确认",引出
**META_REVIEW 双模式**这一设计决策。

- **双模式设计(为什么不直接全自动)**:META_REVIEW 闸的本意**不是抓冲突,是权威边界担责**——语料是合规
  四级引用的权威源,"谁把这篇放进 effective 语料"须落到 `pipeline_events` 具名 actor;且 **"无冲突"≠"正确"**
  (L1 交叉校验只比两来源是否一致,manifest 本身对不对/该不该上线它不验)。于是:
  - **A 模式**(默认,`auto_confirm_meta_no_conflict` 关):全件入 meta_confirm 闸,担责语义完整。
  - **B-严**(开关开):例外式审核——无冲突**全新件**直通 EMBEDDING;**冲突件 + 带 `supersedes_version_id`
    的修订件**(supersede 旧版=把一篇 live 文档降级,最有后果的权威变更,即便无冲突也须有人点头)仍入闸。
    取 B-严而非 B-宽,既拿自动化吞吐又保住"版本切换有人担责"+demo 的人工闸卖点。代码默认 `False`,
    `settings.toml` 设 `true`(demo 开 B)。
- **踩坑:簇2 是"半接通",B 模式有真 bug**。初版只改了 s4(返回 EMBEDDING)+ states(放行 STRUCTURING→
  EMBEDDING),**驱动没跟上**:① `ingest` 用轻上下文(无 embedding/milvus)→ 无 s5 stage → 无冲突件流到
  EMBEDDING 后**永久搁浅**(非 META_REVIEW、无队列项,`meta confirm` 捞不到、又无"推进 EMBEDDING"命令);
  ② 即便接上 s5 到 INDEXED,`run_until_idle` **不调 finalize**(finalize 设计上由 CLI 推进到 INDEXED 后显式
  触发、不被轮询,旧实现只在 `_advance_one` 里)→ **版本切换 + T2/T4 留痕全跳过**。`settings.toml` 默认 `true`
  → bug 就在 demo 默认路径上;**s4 单测只断言"返回 EMBEDDING"漏掉它**(无端到端 B 模式 ingest→INDEXED 测试)。
- **修**:`_finalize_if_indexed` 抽出 `_advance_one` 的 finalize 块(CLI/web/单件/整批共用,凡能到 INDEXED 的
  驱动都经它);`_drive_batch` = `run_until_idle` + B 模式(worker ctx)对到 INDEXED 的件**扫尾 finalize**;
  `_ingest_context` 在开关开时给 ingest 用 worker 上下文(即 **B 模式 ingest 时即需模型**)。`ingest` 与 web
  `ingest_upload` 同步走这套。s4 加 `and not dv.supersedes_version_id`(B-严)。
- **测试**:`test_b_mode_ingest`(model-gated)端到端断言——无 `_approve_doc` 即到 INDEXED、无 open meta_confirm
  队列项、`auto_confirmed` 留痕在位、finalize verify 留痕在位——**正是它能抓 strand-at-EMBEDDING bug**。
  **踩坑**:`unique_docx` 首段「第一章 总则」≠ manifest 标题「合同管理办法」→ 天然 **title 冲突**(`ir.title`=
  docx 首段),在 A 模式被"全件入闸"掩盖、从不暴露;B 模式才现形。故端到端须自造"**首段=标题**"的真无冲突件
  (`_clean_docx`)。s4 另加"修订件即便无冲突仍入闸"用例锁 B-严。
- **目录过滤区域化(clause_tree 普适化,与 web 无关的并行修复)**:逐行 `_TOC_TRAILING_PAGE` 正则不普适
  (只认 章/节、漏 条 与小数体例目录项——小数项 `2.17 … 15` 会被误当真 ARTICLE;且孤立一行恰以数字结尾的真
  标题会被误剥)。改 **区域级预扫 `_toc_block_indices`**:抓目录结构不变量——显式「目录」锚(其后候选行阈值
  降为 1)/ 点引导符(≥4 连续点,单行即定)/ 末尾页码簇(连续 ≥3 行「文本+页码」),统一覆盖 章/节/条/小数/
  无编号目录项;`classify_heading` 回归**纯单行**(目录判定全移预扫)。**scheme A**:命中块留作 root body、不当
  标题(chunker 只切 节/条节点,根 body 本就不入 chunk → 目录文字不进检索;A 与"整段丢弃"下游输出等价,A 改动更小)。
  golden set 真跑 **F1 不回归**。
- **代码审查(code-reviewer 双路审 web 后端 + 前端)+ 批1 修复**:
  - **B1(blocker,同类 bug 复现)**:dispose 路径(web `dispose_queue` + CLI `_do_dispose`)与 ingest 是同一个洞——
    B 模式下 fix/degrade/release 重入会自动越过 META_REVIEW → 搁浅 EMBEDDING **却返回成功**(我先前只在 ingest
    泛化了上下文,没泛化到 dispose)。修:① `_advance_one` 加**通用过渡态守卫**——干净停在 EMBEDDING/INDEXING
    即报错(把任何静默搁浅变响亮失败,全调用方受益);② `_do_dispose`/`dispose_queue` 对 fix/degrade/release 用
    `_drive_context`(B→worker、reject 仍轻量);③ `_ingest_context` 泛化更名 `_drive_context`(ingest+dispose 共用)。
    测试 `test_advance_one_guards_against_transient_strand`(model-free 回归);两个 `queue degrade` CLI 测试 pin A 模式
    保 PG-only(B 模式它们会连 Milvus)。
  - **前端 XSS 整类收口**:加 `h` 标签模板(插值**默认转义**)+ `raw()`,7 个 innerHTML 渲染函数全改;关掉
    ~8 处漏转义 sink(最关键 `actor`【用户可控的 operator】,及 `pipeline_status`/`corpus_type`/节点 `key`·`status`/
    `chunk_status`/`queue_id` 属性)。node 断言证明:载荷中和、属性转义、`raw()` 放行。前端无 JS 测试框架,靠断言+审计。
  - **踩坑:全套一次 Milvus 瞬时 gRPC 卡死**——2h 仅 16s CPU、状态 S、PG 侧干净(0 锁等待)、挂 1 条 Milvus 连接睡死;
    杀掉后 Milvus 秒回、重跑子集 5 passed → **环境偶发非代码回归**(诊断法:`ps -o etime,cputime`+`pg_stat_activity`
    +`lsof` 网络连接,CPU 时长 ≪ 墙钟即卡死)。
  - 批1 验证:model-free+PG **49 passed** + model-gated 子集(b_mode/smoke/s5)**5 passed**;全套 model-gated 留**正式提交前**跑。
  - **批2(接口健壮+功能,已做)**:① **H2** `cgi`→纯标准库多部件解析(`_parse_multipart`/`_parse_content_type`,
    3.13 移除 cgi、机器默认 3.14 否则整 app 起不来;**保二进制无损**——只剥框定 CRLF,单测验含 \\r\\n/尾换行的
    文件逐字节回灌)② **H3** 上传/JSON 体大小上限(Content-Length 超限先拒 → 413,`_PayloadTooLarge`)
    ③ **search 结果渲染**——招牌四级引用此前仅 JSON 入日志;`service.search` 复用 `cli._obligation_chunk_ids`
    给 hit 标 `is_obligation`(不动 Milvus schema),前端 `renderSearch` 面板出 条款路径/页/语料/`[义务]`/score
    ④ **`withBusy(btn,fn)`** 套 upload/verify/report/reprocess/队列/search:运行期禁用+「处理中…」,防卡死观感与双击竞态。
    验证:`_parse_multipart` 单测(二进制无损)、`node --check`、ruff、test_web_service+test_cli 20 passed、
    live `service.search` 真模型出 `is_obligation` 标。
  - **批2 跳过/后置**:**H4**(operator 可伪造/无鉴权)——demo 绑 127.0.0.1 已限暴露面,暂不上鉴权;
    中/低项(静态服务 sibling-prefix、report 读触发写、JSON envelope 不一、`_CTX` 无锁、前端可访问性/`allSettled`/
    stale-response 守卫/日志上限)留批3 或按需,见审查记录。

### 阶段 V16 — 生产 v1.6 契约保真 + QA/案例/E2 入库 + 案例调优(2026-06-18/19;PR #4,CI 绿)

**背景**:zy 定调"代码要真实落地,全部按生产 v1.6 保真,触发驱动项除外"(不再以 demo 有无消费方裁剪)。

**契约层 v1.6 保真(迁移 0005)**:Milvus `audit_corpus` 补齐 §8.2(+doc_id/sub_type/effective_date/chunk_type/
text;perm_tag/biz_domain→ARRAY、issuer_level→INT8;entity_type 预留)· PG `chunks` 补 chunk_type/parent_chunk_id/
internal_refs(接线 find_internal_refs)/embed_status/entity_type · `clause_tags` 增类型列(deontic_type/
norm_duration_days/…/entity_type)· version_status 四态(abolish_only→abolished、未来生效日→upcoming + 手动
`demo activate`,延后 supersede)· manifest +sub_type/+effective_date · IR Block.level · E1 期限单位归一化。

**多类语料入库(s3 按 corpus_type profile 路由)**:新增 `chunking/profile_router`——P-INT/P-EXT→条款树(不变)、
P-QA→`qa_chunker`(一问一答=1 chunk + 问答对完整率 QC)、P-CASE→`case_chunker`(要素分段 + 摘要块)+ `cases`
表(迁移 0006)+ `meta/case_extract` L1 要素抽取(s4 分支)。QC 按 corpus_type 选指标集(`indicators_for`),制度件七项不变。

**E2 LLM 条款级打标(默认关)**:`llm_client`(httpx OpenAI 兼容,JSON 模式,gpt-5.4-nano)+ `enrich/e2_tag`(字典
约束 + 服务端强制 + 不臆测 → clause_tags 的 entity_type/部门/事项 + dict_version)· `dict_entity_types`/
`dict_departments` 表(迁移 0007)+ 初版种子(v0-draft 待评审)· config `e2_enabled`(默认关,保零 LLM 默认路径)+
`[llm] model`。key 只走 env `OPENAI_API_KEY`、绝不入库。

**案例真实语料调优**(基于两份北京监管局警示函):light_parser 加**康熙部首字形→CJK 归一**(pdfplumber CID 字体
伪影 ⽉⽇⾏⼈ 致日期/正则失配)· 当事人无前缀回退抬头行 · 文号跳过被引外规令号 · 新增"警示函/监管谈话"类型 ·
**指标7 抽取充分性从 P-QA/P-CASE 移除**(量的是页间密度均匀度、假定制度满版页,误伤短/不均的非制度件)。

**web**:上传"语料类型"下拉补 P-QA/P-CASE。

**测试**:干净栈 + 本地 BGE-M3 真跑**全量 374 passed / 0 failed**(E2 真 smoke 通过)· alembic 0001→0007 干净栈
重放、`check` 无漂移 · ruff 全清 · golden 条款树 F1=1.0、E1 义务 P=R=1.0 不变。CI 修了一处 httpx 未声明依赖。

**待裁决/后续**:实体/部门字典 v0 占位待张老师评审(§16-7)、E1 期限口径待甲方(§16-8);P-CASE"处罚依据"段在依据
埋于段落中间时未单独切出;DeepDoc/OCR 仍搁置。

## 阶段 Q:制度查询智能体 R1+R2 + 协作流程/记忆收口(2026-06-22~23)

摄取侧之上起**功能1 制度查询智能体**(独立 `query/` 包,只读消费 V1.6 产物;DAG `query→pipeline→common` 无环)。
全程 **spec-driven 四阶段门控**(SPEC/PLAN/TASKS/IMPLEMENT,产物入 `docs/query-agent-docs/`)+ **Codex 审查修复闭环**。

- **契约补**:`clause_references` 表 + 迁移 0008 + fixture(R1/R2 多跳预留;**ref_resolver 填充逻辑仍 TODO**,见 pg_models 注释)。
- **R1 依据查询 MVP**(PR #5):混合检索(复用 `milvus_io`/`embedding_client`)→ **引用 ID 注入生成**(`select_faithful` 代码级
  兜底,无忠实引用降级拒答)→ **四级锚点 PG 回查** → §10 契约;**覆盖感知拒答**(exhausted_scope)+ **八路路由分满**
  (R1/R7/R8 实装,R2–R6 诚实占位)+ LangGraph 编排(节点纯函数可换底座)+ LLM 可配置工厂(默认 stub 零网络)。
  Codex 审 4 项 finding(degraded 引用 / 无引用裸答 / scope 空 / 裸结论代码级后检)全修。
- **R2 变更查询**(PR #6):定位 → 版本链回查(logical 的 effective + supersedes 前驱)→ **条款级 diff**(同 clause_path_norm
  多子块按 seq 聚合)→ **修订原因回查**(`revision_notes`,缺失明示、**绝不 LLM 推测**)→ §6.2 四栏。全程零 LLM。
  Codex 审 2 项(条款多子块聚合 / 引用断言强化)全修。
- **协作流程固化(CLAUDE.md)**:Claude 规划+实现 ↔ Codex 审查;审查修复闭环(Codex 审→Claude 改/反驳→复审,
  Codex 不自改);**测试职责分工**(Claude 拥 TDD+模型门控/集成+合并前全仓门一次,Codex/CI 独立单元校验)+ 节流。
- **agent 记忆结构收口**(PR #7):AGENTS.md 入库、10 个模块 devlog 归 `docs/devlogs/`、删升格专用 skill、
  production-fidelity 指令升为 CLAUDE.md 仓库共享。

**状态快照**:八路 4 路实装(R1 依据 / R2 变更 / R7 澄清 / R8 兜底),红线由代码级兜底守(select_faithful/sanitize/覆盖拒答)。
全仓 **458 passed / 0 failed**(本地 BGE-M3 真栈)· CI 绿(已补 `pip install -e query`)· ruff 全仓绿 · DAG 无环 · 迁移至 0008 无漂移。
PR #5/#6/#7 已合入 main。

**踩坑(非显然)**:① **测试文件基名须全仓唯一**(pytest prepend + tests 无 `__init__.py`,撞名致收集报错)·
② CI 安装步骤须加 `pip install -e query`(否则 langgraph 缺失收集报错)· ③ 仓库改名后 `.venv/bin/*` shebang 失效,
用 `python -m` 或重写 shebang · ④ flat 布局下从仓库根 cwd `import query` 解析为 namespace 包(`__file__=None`),与 pipeline/eval 同,非 bug。

**后续 backlog**(`docs/query-agent-docs/GAP.md`):P0 — R5 判定型 / §9.2 多模型复核 / §9.3 权限;P1 — R3 案例桥接 / R4 列举 /
R6 统计 + 重排;依赖缺口 — dict 加载让 N2 真识别事项(清 resolve_scope 兜底)/ clause_references resolver / cases 消费 /
entity_type·biz_domain 检索前置过滤(需扩 milvus_io)。

## 阶段 R:制度查询智能体 R3+R6 + RTM(2026-06-23~24)

延续 spec-driven 闭环,接续 阶段 Q backlog,完成 R3 案例桥接 + R6 统计型 + RTM 全覆盖证明,PR #9–#12 均合入 main。
细节见 `docs/query-agent-docs/query_devlog.md` 的 R3/R6 两节。

- **R3 相似案例 + 案例桥接**(PR #9–#10):case 分区(P-CASE)语义检索 → **一案一卡去重**(`_dedup_by_case` 按
  `doc_version_id`)→ PG 要素回填 → `CASE_CARD`;**附挂通道**:R1 充分 evidence 答复尾挂相关案例卡(门控:充分
  evidence + 非 definition 型才附挂,可关 `query.attach_cases`)。**精确反查桥接**(`bridge.cases_for_clauses`,
  consumed-when-present:L2 默认关 → `cited_regulations` 空 → 反查 `[]` 降级语义-only,**绝不臆造外规引用**)。
  Codex 补审附挂门控单测(PR #10):definition/refuse/toggle-off 不挂,全绿。
  **踩坑**:pymilvus 全局连接顺序依赖——`test_r2_change_integration` 模块级 teardown `mio.disconnect()` 断全局别名,
  R3 集成按字母序后跑首个用 Milvus → `ConnectionNotExist`;修:R3 集成文件 autouse 幂等 `mio.connect()` 重连。
  **后续系统性脆弱**:共享全局别名 + 模块级 disconnect,新增 Milvus 检索集成须注意同模式。

- **RTM 需求可追溯矩阵**(PR #11):建 `docs/query-agent-docs/RTM.md`(v1.0 设计全覆盖证明,R1–R3/R6 已标 test_id)。

- **R6 统计型**(PR #12):规则维度抽取(零 LLM)→ **防注入参数化 SQL**(`GroupBy` 白名单枚举 + SQLAlchemy
  bound params,恶意输入落默认枚举不进 SQL 结构,拒 LLM 生成 SQL)→ **TABLE 输出**(`{columns, rows[, note]}`)。
  两模式:聚合(GROUP BY 维度 count/sum_amount 降序)+ 列表(date 过滤 → 按 penalty_date 降序)。全程零 LLM。
  集成 PG-only(不需 Milvus/embedding),合成 cases 用**哨兵未来年 2098/2099 + 唯一名** + FK 链 fixture 按序 flush。
  **Codex 复审 3 warning(均实 bug)**:①列表统计未进 `STATISTICAL` 路由(缺"处罚有哪些"类触发词,R6 单测直调绕
  过路由漏检)→ 加触发词 + golden + router 回归;②聚合直接 over `cases` 未 join `doc_versions` 过滤可见性
  (INDEXED ∧ effective)→ 把 META_REVIEW/superseded/upcoming 件计入 → 修:两路统一 join 可见性条件;
  ③PG `EXTRACT(year)` 返 `Decimal`,`json.dumps` 抛 TypeError → 修:`cast(..., Integer)` + `_fmt` Decimal 兜底 + 逐年集成测。
  全部修完,Codex 最终 approve。

**状态快照**:八路 **6 路实装**(R1 依据 / R2 变更 / R3 案例桥接 / R6 统计 / R7 澄清 / R8 兜底),R4(列举)/R5(判定)诚实占位。
RTM 全覆盖证明落地。PR #9–#12 合入 main。ruff 全仓绿 · 迁移至 0008 无漂移。
**后续 backlog(已更新 GAP.md)**:P0 — R5 判定型 / §9.2 多模型复核 / §9.3 权限;P1 — R4 列举 + 重排;
依赖缺口 — `violation_category` L2 字典评审、`clause_references` resolver、entity_type·biz_domain 前置过滤。

## 阶段 R4:制度查询智能体 R4 多文档列举(2026-06-24)

第五轮 spec-driven(SPEC/PLAN/TASKS-R4),实装八路最后一个**确定性**路由 R4(列举)——**八路仅剩 R5 占位**。
细节见 `docs/query-agent-docs/query_devlog.md` R4 节。

- **切片**:`route_type=enumerate`——规则维度抽取(`listing/dimensions`)→ **枚举模式高 k**(`retrieve_enumerate`
  50/50,不激进截断)→ 过滤(① **Milvus 标量预过滤** `chunk_type=clause`+`biz_domain`+`entity_type`;② **E1 义务
  PG 后过滤** `clause_tags.is_obligation`)→ 去重 + 按 `doc_version` 聚合 → **TABLE**(制度名/文号/条款/页码/状态)
  + 四级 citations + **不保证穷举外规边界声明**;空→覆盖拒答。**全程零 LLM。**
- **承重(唯一)改动**:`milvus_io.search` 加可选 `extra_expr`(**add-only**,`None` 时 byte 等价,`test_milvus_search_expr`
  守不回归 R1/R3/R6)。其余皆只读 + 新增 `query/query/listing/` 子包。
- **防注入(红线)**:`build_milvus_expr` 字段名白名单(chunk_type/biz_domain/entity_type)+ 值经 `json.dumps` 转义;
  raw user 串在 `dimensions.extract_enum_spec` 即被词典过滤(`extract_terms` 只返词典成员),绝不到 expr。
- **两道 consumed-when-present 降级**:E1 PG 后过滤可后验 → 空集降级不过滤 + note;E2 Milvus 预过滤无法后验 →
  仅当 query 抽到词典词才加 entity/biz 子句(dict 未接 PG 加载 → 默认不命中)。
- **门控**:全仓非模型门 **514 passed / 31 skipped / 0 failed** · ruff 全仓绿 · 查询模型门集成(R1/R3/R4/hybrid/anchors,
  真 PG+Milvus+BGE-M3)**13 passed**(证 `milvus_io` 不回归 + R4 端到端)。RTM reconcile:`R4-filter/mode/bound`→✅、
  `§2-entity/biz/chunktype/tagsE1`/`§5.3`→🟡、GAP #12 ✅;覆盖摘要 36✅/31🟡/48❌/1➖。
- **未做**:LLM 维度抽取、E1 期限数值过滤、E2 真打标/词典加载、sparse 提权(§5.4)/重排(§5.5)、Excel 导出、
  穷举外规保证(§15-③ 声明不做)。待 Codex 复审。

## 阶段 R5:制度查询智能体 R5 判定型路由 —— 八路收官(2026-06-24)

第六轮 spec-driven(SPEC/PLAN/TASKS-R5),实装八路最后一路 R5(判定型)——**八路全实装,无占位**。
细节见 `docs/query-agent-docs/query_devlog.md` R5 节。

- **切片**:`route_type=judgmental` + `review_required=true`(§6.5/§8.3)。桥接入口(复用 R3
  `retrieve_cases`→`cited_regulations` 反查外规条款,consumed-when-present)∥ hybrid(内规+外规)→ **三段式硬约束**
  (① 依据条款四级锚点 ② 构成要件框定 ③ AI辅助/人工复核标识,**无 verdict 槽**)→ §9.2 复核接口。**默认零-LLM**。
  新增 `query/query/judge/`(framing/review/r5_judgment)。
- **红线(不出裸结论)三重保障**:① 形态**无 verdict 槽** ② `strip_bare_conclusion` **always-on**(verdict 词
  违规/违法/合规/合法 + 试探性 可能违反/疑似违规/涉嫌/倾向于不合规 → 替中性"不作判定")③ §9.2 复核接口+toggle
  (`judge_multimodel_review` 默认关)。**安全文案有意避开 verdict 字面** → "输出无裸结论"可被钝断言。
- **决策**(AskUserQuestion):框定=clause直呈(零-LLM)+ LLM toggle(`judge_constituent_llm` 默认关);
  红线=形态+代码后检+§9.2 接口;桥接入口=复用 R3(`resolve_cited_clauses`,`bridge.norm_ref` 归一匹配
  `doc_number`+`clause_path_norm`)。
- **§15-④ 产品形态**:按 §6.5 三段式作 **demo workaround**(人工复核必需 `review_required` + 代码后检无裸结论 +
  AI 辅助标识),**不向甲方承诺判定结论**,交付标注待甲方(张益)确认验收口径。
- **门控**:全仓非模型门 + ruff 全绿;R5 模型门集成(三段式真数据 + **断言无裸结论** + 手插 cited 验桥接)2 passed。
  RTM reconcile:R5 全组(bridge/mix/3seg/noraw/render/noloop→✅、elem/review→🟡)+ §8.3/§7.4/§14-g→✅,
  RL-1 维持 🟡(真 LLM §9.2 复核留后续);覆盖摘要 45✅/33🟡/37❌/1➖。**八路全实装收官**。
- **未做**:§9.2 真 Kimi faithfulness 复核(接口已就位,RL-1 真-LLM 闭环另轮)、LLM 构成要件抽取默认开、
  `cited_regulations` L2 生产打标(§15-⑤)、重生成、bge-reranker/sparse 提权/流式。待 Codex 复审。

## 阶段 RERANK:§5.5 重排(bge-reranker)—— 八路后首个横切检索增强(2026-06-25)

第七轮 spec-driven(SPEC/PLAN/TASKS-RERANK)。八路收官后转向横切能力,先做 §5.5 重排(demo-faithful、惠及全检索)。
细节见 `docs/query-agent-docs/query_devlog.md` §5.5 节。

- **切片**:`rerank_backend=bge` 时主 hybrid `retrieve`(R1/R5)对候选池(~50)用 **bge-reranker-v2-m3** cross-encoder
  重排 → `topk`(8)。新增 `query/query/rerank/`(`RerankerClient` Protocol + `NoneReranker` passthrough **默认** +
  `BGEReranker` 本地 `FlagReranker` 懒载 + `make_reranker` factory,镜像 llm/embedding 接缝)。
- **承重(唯一)改动**:`milvus_io.search` 加 `with_text`(**add-only**,输出 Milvus 截断 text 供"检索-重排一跳");
  `Candidate` +`text`(add-only,默认 None)。**`rerank=none`(默认)byte 等价**(RRF 序 + passthrough,不回归八路)。
- **决策**(AskUserQuestion):文本来源=Milvus rerank-hop(schema 本就预留,热路径免 PG 往返);应用范围=仅主
  `retrieve`(R1/R5)——R4 枚举(§6.4 召回完整性)/ R3 案例不重排;加载失败**抛、不静默退化 none**。
- **门控**:全仓非模型门 + ruff 全绿;rerank 模型门集成(真 PG+Milvus+BGE-M3)**2 passed + 1 skip**——注入 fake
  reranker 在真栈验 `with_text` rerank-hop 返**真 Milvus text** + reranker 真应用(无需本地 reranker 模型),真
  bge-reranker-v2-m3 需 `QUERY_RERANK_MODEL`(本机无、skip,绝不联网)。RTM:§5.5→✅、R1-filter 重排部分→✅;
  覆盖摘要 46✅/33🟡/36❌/1➖。
- **未做**:rerank endpoint/网关(§9.1)、top-k V0 标定(§15)、归一阈值、R4/R3 重排、sparse 提权(§5.4)。待 Codex 复审。

## 阶段 SPARSE:§5.4 sparse 精确通道(发文字号提权 + 词典扩展)—— 八路后第二个横切检索增强(2026-06-26)

第八轮 spec-driven(SPEC/PLAN/TASKS-SPARSE)。worktree `feat/query-docnum-boost`(与并行 P0 工作隔离,同 `.git` 双
工作树)。细节见 `docs/query-agent-docs/query_devlog.md` §5.4 节。**集成 3 passed + 全 query 模型门 226 passed / 2 skipped(干净栈 + 真 BGE-M3),零回归。**

- **切片**:主 hybrid `retrieve`(R1/R5)在 embed 后、search 前对 **query sparse** 做查询层增强 —— 发文字号/全名
  regex 检出 → 重 embed → token 加权并入(提权);`dict_scenario_terms` 口语→法言子串映射 → 注入(扩展)。新增
  `retrieve/sparse_boost.py`(纯函数)+ `seeds/dict_scenario_terms.csv`(v0-draft)。
- **决策**(AskUserQuestion):范围=提权+扩展;机制=**查询层 token 提权**(弃 `WeightedRanker` —— RRF 基于秩无法表达
  通道权重、Milvus 2.4 量级失配;选择性 token 提权等效达意、**保持 RRFRanker、零 pipeline 改动**);应用=仅主 retrieve。
- **零承重改动**:`milvus_io.search` 签名不变(传增强后 sparse 即可);`config` +5 字段(默认关)。**双开关默认关 byte
  等价 + 只动 sparse**(dense 恒等)。`seed_dicts` 显式读命名文件、新 CSV 对 `demo up` 灌库 inert(核实)。
- **门控**:集成 `test_sparse_boost_integration` **3 passed**(端到端召回/不回归/双关等价,干净栈+真 BGE-M3);
  全 query 模型门 **226 passed / 2 skipped** 无回归 + `test_pg_io` 新种子 inert;ruff 全绿。RTM:§5.4 → ✅,计数 47✅/35🟡/33❌。
- **集成 fixture 踩坑**:发文字号嵌正文 → meta L1 抽为 doc_number → 与 manifest 冲突卡 META_REVIEW;修=正文冒号边界使
  L1 干净抽出 = manifest doc_number(详见 query_devlog §5.4)。
- **Codex 复审修复(2 warning)**:发文字号 regex 前缀裁问句词(QUERY-SPARSE-DOCNUM-SPAN);"名次升"集成实为 no-op
  (小语料 §5.1 hybrid 已置顶 off_rank=0)→ 机制非无效改**单元 sparse-IP 严格证**、集成改端到端召回+不回归
  (QUERY-SPARSE-WEAK-INTEGRATION;rank 改善属大语料/§15 V0)。
- **未做**:`WeightedRanker`/检索后提分(弃)、dense 改写/HyDE(N1)、`dict_scenario_terms` PG 表+灌库(GAP #11/§15⑥)、
  R4/R2/R3/R6 提权、系数 V0 标定。待 Codex 复审。

## 阶段 REVIEW:§9.2 Kimi 忠实性复核 —— RL-1 真-LLM 闭环(2026-06-26)

SDD(SPEC/PLAN/TASKS-REVIEW)。worktree `feat/query-faithfulness-review`。接口/toggle/fail-closed/LLM seam 已在 R5 轮实装 →
本切片只**接真复核模型 + 闭环测试**,零接口重写、零 pipeline 改动。细节见 `query_devlog.md` §9.2 节。
**全 query 套件 204 passed / 29 skipped、ruff 净、无回归。**

- **已决(AskUserQuestion)**:① 独立 `review_model`(Kimi)与主答 `llm_model`(Qwen)分离(§9.1);② 不支持 → 降「待人工核实」
  (不重生成);③ 仅 R5 判定型。
- **实现**:`config` +`review_model`(+`QUERY_REVIEW_MODEL`/`OPENAI_REVIEW_MODEL`);`make_llm_client(cfg, *, model=None)` add-only
  (无 model = 主答,向后兼容);`r5_judgment` 复核客户端接线(**toggle 关 → 不建客户端 + passthrough + 零网络**;`review.py` 不改);
  `PROMPTS.md` §9.2 prompt;门控集成 `test_r5_review_integration`(gateway+key 真跑 / 无 key skip)。
- **踩坑**:worktree + editable-install 用 MetaPathFinder 指向主 checkout → 跑测须 `PYTHONPATH=<worktree>/{query,pipeline,libs/common,eval}`
  使 `PathFinder` 先解析到 worktree(详见 query_devlog)。
- **诚实留痕**:真模型门控测**本地无 key 未执行**(只验干净 skip)→ **RL-1 / §9.2 仍记 🟡**(实装+单测+门控就位),
  待**真 gateway+key 跑绿**翻 ✅;RTM 计数不变(47✅/35🟡/33❌)。待 Codex 复审。

## 已建链路与下一步

全链路:`demo ingest`(s0 登记+版本关系+去重审计)→ s1(渲染+解析+对齐)→ s2(七指标质检)→ STRUCTURING 复合
(s3 切块 + s4 元数据校验)→ META_REVIEW(A 模式全件入 meta_confirm 人工闸;**B-严**:无冲突全新件直通,
冲突件+修订件仍入闸——见《阶段 W 双模式》)→ `meta confirm`(approve)→ EMBEDDING(s5 嵌入+冷备)
→ INDEXING(Milvus 索引 + 翻 effective)→ INDEXED → **finalize**(带 supersedes 自动把旧版置 superseded);`search` 混合查出
四级引用(默认 effective,`--include-superseded` 见旧版);degrade 重入索引终于 DEGRADED_INDEXED。失败件入统一队列、`dispose`
处置。INDEXED 后 finalize 跑 T2/T4 留痕;`demo verify smoke/replay/reconcile`、`rebuild`、`report` 出验证指标。
**检查点 B/C/D/M2/M3 达成;M1(V1/V2/V4/V5)+ M2 验证套件(V3/V6/V7)+ M3(E1 义务打标 V8 + report 打磨)完成,V1–V8 全过。**
注:模型门控集成测试假定**干净栈**(SHA 去重);手动 demo 走查残留数据须 `demo down -v` 或清库后再跑测试
(本会话曾因走查残留致 test_version_demo/reprocess SHA 撞车,清库后通过;test_reprocess 已改 unique_docx 自隔离)。

**状态快照(截至 M3,检查点 M3 达成)**:全套 **263 passed / 0 skipped**(本地 BGE-M3 真跑,11 个 model-gated 全跑;
不带 `PIPELINE_EMBEDDING_MODEL` 时这 11 个 skip = 252 passed)· `ruff check .` 全绿(含 alembic/versions)· 迁移至 0004
无漂移(M2/M3 均无新迁移)· **检查点 A/B/C/D/M2/M3 全达成,V1–V8 全过**。**M2 验证套件真栈跑通**:`verify replay` 100%(620/620 含 143 页 ext_sse)· reconcile 一致 ·
`rebuild` 631 块零编码回灌 count 干净 · `verify smoke` 100%(9/9 排除 superseded)· golden F1=1.0 · finalize 留痕→report
聚合 t2/t4=1.0。提交锚点:M1 见前;M2 = M2-A(0e9333b)+ M2-B/C/D(本批)。
(检查点 D 走查发现已修:指标3 插入条误报 + clause_tree 跨法引用过滤 + 小数编号做全;batch01 走查 9 INDEXED+1 DEGRADED+1 QUARANTINED。)
**B2 已补(原唯一待修小项)**:s0 隔离件(格式/密级/疑似重复)置 QUARANTINED 时写 `quarantine` 队列行 →
`queue list` 可见、`queue release` 重入 PARSING / `reject` 退回(dispose 流早支持 quarantine,只差这处写入)。
统一队列三类(qc_fix / quarantine / meta_confirm)至此全部由代码写入。**无已知待修项**(其余皆 spec 故意延后/裁出:
DeepDoc/E2·E3/L2 LLM/perm_tag 过滤/OCR/endpoint 桩/注释保留表/§21 T1·T3·T5·T6)。

## 测试与运行约定

- venv:`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`。
- 集成测试连真栈,栈未起则 skip;各自按 batch_id 反 FK 序清理。
- 迁移 add-only:autogenerate → upgrade → check 无漂移。`alembic/versions` 已纳入 ruff lint,autogenerate 后须
  `ruff check --fix alembic/versions && ruff format alembic/versions`(违规全可自动修,纯格式)再提交。
- 行宽 100,ruff(E/F/I/UP/B);CJK 注释易超行,放独立行或缩短。

## 阶段 S:文档处理管线评测工具(tools/doc_test 第一期,2026-06-24;PR #13)

**背景**:团队需在接入真实 PDF 语料之前,快速评估三件事:① 正则抽取/条款树覆盖是否充分;
② 扫描件 / 版面破碎件是否需要 DeepDoc;③ QC 七指标数值分布 vs 当前阈值是否合理。
目标是产出**易懂中文报告**,无须人工读 pytest log。

**范围与设计原则**:
- `tools/doc_test/`(工具脚本,非生产包,`out/` + `config.yaml` 已 gitignore):
  `run_phase1.py`(入口)/ `metrics.py`(确定性指标)/ `judge.py`(可选 LLM 裁判)/ `report.py`(Markdown 报告)
  / `config.example.yaml`(配置模板)/ `使用指南.md`(团队详版)/ `README.md`(快速参考)。
- **绕过 PG/ObjectStore/Milvus**,只调管线纯函数(`解析→切块→QC→正则抽取`);LLM 走 env
  (`OPENAI_API_KEY`,绝不入库)可关。
- **三目标 → 指标**:要素抽取命中率 + 条款树覆盖 + LLM 核对(① 正则);扫描件/版面破碎启发式 +
  LLM(② DeepDoc 需求);7 指标数值分布 vs 阈值 + LLM 反推松紧(③ 阈值建议)。
- **已冒烟**:4 份真实 PDF,捕获扫描件管线失效(E202→建议 OCR)+ 案例正则缺口(文号/金额漏抽);ruff 全绿。

**决策**:免 Codex 审直接合入(工具脚本,团队自行迭代);无新契约/PG 迁移;不计入正式测试套件(非生产代码)。

**状态**:PR #13 合入 main,`tools/doc_test/` 7 文件齐全。

---

## 本次会话新增基础设施(2026-06-24)

- **`/clear` 自动存档 hook**(`~/.claude/hooks/save-devlog-on-clear.sh`,写入 `.claude/settings.local.json`):
  `/clear` 触发时自动把会话摘要追加到 devlog(当前 session 即由此驱动)。属 Claude Code 配置层,不影响仓库代码。

---

## 阶段 P0 Phase 1:切块内部引用 / 案例对齐 / xlsx parser-only(2026-06-26;PR #18)

**范围**:T1.1–T1.5。主改动在 `pipeline/pipeline/chunking/` + `pipeline/pipeline/meta/` + alembic。

**关键交付**:

| 文件 | 职责 |
|---|---|
| `chunking/ref_resolver.py` | 正则提取切块内 `internal_refs`(`第X条/款/项`) |
| `chunking/ref_render.py` | refs → 可读渲染字符串(前端用) |
| `meta/case_ref_align.py` | 案例 ↔ 条款切块交叉对齐,写 `case_clause_refs` |
| `alembic/0010` | `clause_refs`/`case_clause_refs` ON DELETE CASCADE |

**决策要点**:
- XLSX **收窄至 parser-only**:`detect_format()` 可识别,但 S0 白名单不加 xlsx;端到端路由(§22.3 费用数据)延至 P2。
- `internal_refs` 字段在切块写入时由 `ref_resolver` 填充,不再依赖 `clause_tree` 单独爬取。
- Codex 审查闭环完成(4 条 warning 修复 + xlsx 收窄后文档一致性补全)。

**测试**:5 个新测试文件(200+ 行),改动范围 16 passed;ruff 全绿。

**PR 状态**:PR #18(feat/p0-phase1)待合入 main;全仓模型门控全量门跑完后合并。

详见 `docs/devlogs/structuring_devlog.md` §「P0 Phase 1」。
