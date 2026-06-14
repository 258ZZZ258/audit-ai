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

### 阶段 C — 结构化 / 元数据 / 向量化(进行中)
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

## 已建链路与下一步

链路:`demo ingest`(s0 登记 + 版本关系)→ s1(渲染+解析+对齐)→ s2(七指标质检)→ STRUCTURING 复合(s3 切块 +
s4 元数据交叉校验)→ META_REVIEW;失败件入统一队列(qc_fix / quarantine / meta_confirm),`dispose` 处置。
**检查点 B 达成**;C1–C3 完成(过 QC 件现切块 + 元数据校验后停 META_REVIEW)。
下一步:**C4 EmbeddingClient BGEM3**(需 SP2 + 装 torch/FlagEmbedding ~2GB + 模型下载 ~2GB)→ C5 milvus
upsert/冷备/混合查 → C6 s5_embed_index → C7 search/meta CLI → 检查点 C(V1 主干);之后阶段 D(原子切换/幂等/报告)。

## 测试与运行约定

- venv:`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`。
- 集成测试连真栈,栈未起则 skip;各自按 batch_id 反 FK 序清理。
- 迁移 add-only:autogenerate → upgrade → check 无漂移。
- 行宽 100,ruff(E/F/I/UP/B);CJK 注释易超行,放独立行或缩短。
