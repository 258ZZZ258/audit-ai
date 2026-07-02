# 结构化层 devlog(pipeline/pipeline/chunking)

**职责**:S3 = 条款树构建 + 切块。`normalize.py`(中文数字/条款号归一)· `clause_tree.py`(七类节点建树)· `chunker.py`(六规则 + 确定性 chunk_id 调用)。s3_structure 是薄装配(`stages/s3_structure.py`)。

## normalize / clause_tree
- **L1 normalize**:中文数字→int;条款号→规范形(`之一`/bis/小数式统一 `N-K`);全半角 + 去空白。
- **L2 clause_tree**:七类节点正则、栈式建树、虚拟根、`clause_path(_norm)`、`internal_refs`。**bug**:`第X条之一` 的 `之一` 在「条」**之后**,初版 refs 正则写反。bis/.1b 经 `_ART_NUM` 接通(normalize 早支持、classify 入口够不着)。
- **做全小数规则(检查点 D 发现 2,根因在 IR 边界下游、与换 DeepDoc 无关)**:
  - **跨法引用过滤**:`第X条` 紧跟枚举标点 `、，,;；`(`_REF_PUNCT`)判引用列举、非条标题(否则 `…第一百九十六条、依照《证券法》…` 碎片落块首被当条标题撑假缺口)。
  - **小数编号**(交易所规则 `2.17`/`3.1.2`,章[.节].条):classify 加小数分支——号后**强制空白**避 `2.17%`/`1.5亿`,`(?!条)` 排 `10.1.3 条…` 引用碎片,号取**全小数**保排序;`_key` 改**变长元组**(`10.1.3`→(10,1,3))跨节排序正确。ext_sse 0→401 条。
  - **目录剥离(阶段 W 区域化)**:逐行正则不普适 → 改**区域级预扫 `_toc_block_indices`**(目录锚 / ≥4 连续点引导符 / 末尾连续 ≥3 行页码簇),统一覆盖 章/节/条/小数;`classify_heading` 回归纯单行。**scheme A**:命中块留 root body、不当标题(chunker 只切节/条,根 body 不入 chunk)。golden F1 不回归。

## chunker(六规则 + chunk_id)
- 原子=条;超长按款拆 + **条头续接**;超短独立;父块=节级仅 PG;表格独立块;**面包屑前缀**(合成 `章 > 条` 路径,T4 回放须剥它)。
- **`target_token_min`(决策 8)**:原是死参 → 实现**条内尾块合并**(尾组 <min 并回前组,仅同条内)。
- **单段超长(决策 10)**:语义边界(项（N）/句末；。)拆 + 字符硬切兜底(标 `oversize`);`token_count` 改**量内容**(不含面包屑/条头续接,使「≤target_max」为干净不变量)。
- **C1 s3**:载 IR → `build_chunks` → `pg_io.replace_chunks`(同事务删旧插新,确定性 id 重跑幂等)。chunk_status=staging;父/表格块仅 PG;`oversize` 落库(迁移 0004)。

> chunk_id 公式本体是契约,在 `libs/common/common/`(见同目录 `contracts_devlog.md`)。
> 时间轴:`docs/devlog.md` 并行流 L(L1/L2/L3)、阶段 C(C1)、检查点 D(发现 2)、阶段 W(目录区域化)。

## P0 Phase 1:ref_resolver / ref_render / case_ref_align / xlsx(2026-06-26;PR #18)

**背景**:P0 Phase 1(T1.1–T1.5)补齐切块层对内部引用、案例对齐、xlsx 格式支持的生产契约要求。

**主要新增文件**:

- **`chunking/ref_resolver.py`(153 行)**:从切块文本自动提取内部引用(`第X条`/`第X款`/`第X项`等正则),返回 `internal_refs` 列表;与 `clause_tree` 的 `internal_refs` 字段对接写入 PG(`chunks.internal_refs`)。
- **`chunking/ref_render.py`(35 行)**:将 `internal_refs` 列表格式化为面向前端的可读字符串(`"见第X条"`)。
- **`meta/case_ref_align.py`(91 行)**:S4 阶段将 `cases` 表里的案例与已入库的条款切块做交叉对齐;写 `case_clause_refs` 关联表。
- **`alembic/versions/0010_clause_refs_cascade.py`(39 行)**:为 `clause_refs`/`case_clause_refs` 加 `ON DELETE CASCADE`,确保 `reprocess` 幂等清理时级联删旧引用关系。

**测试(5 个新文件,200+ 行)**:
- `test_ref_resolver.py`(205 行)—— 覆盖多种正则边界、跨法引用过滤
- `test_ref_render.py`(23 行)—— 渲染格式回归
- `test_case_ref_align.py`(85 行)—— 对齐逻辑 + 幂等
- `test_chunker.py` 补充 —— 六规则验证
- `test_xlsx_parse.py`(46 行)—— `detect_format()` 格式探测

**XLSX 决策(T1.5 收窄)**:`detect_format()` 可识别 `.xlsx`,但**不加入白名单**;端到端入库(§22.3 费用数据路由)留 P2。故 S0 仍拒 xlsx、parser 仅做能力验证。文档/注释已对齐此决定。

**Codex 审查闭环**:Phase 1 提交后 Codex 发现 4 条 warning → 逐条修复(类型注解缺失、注释/文档与代码不一致)→ xlsx 收窄后再做一轮文档一致性补全 → 复审通过。

**状态**:PR #18(feat/p0-phase1)待合并;本地 `ruff` 全绿,16 passed(改动范围单元)。下一步:全仓模型门控全量门跑一次后合 main。

## P0 续:ref_resolver R4 跨文档指代(2026-06-28;feat/ref-resolver-r4,T2.4)

**背景**:R1–R3(文档内)P0 Phase 1 已实装;本轮补 R4 跨文档「《X办法》(文号)?第N条」三级匹配填充(§6.7 收尾)。**零迁移**(`clause_references.resolution_status` 早已 `String(16)` 含 ambiguous/pending_target、`dict_aliases` 表 0009 已建)。SDD 四件 `SPEC/PLAN/TASKS_REF_R4` + 本段。

**主要决策(why)**:
- **新建专用 `XRefLookup`,不扩展案例侧 `PgRegLookup`**:后者限 P-EXT + `.first()` 不报多命中,语义不合;扩展会牵动案例 L2 链路。R4 lookup **不限 corpus**(内规可引内规/外规,与案例只引外规有意不同)、排除 self_dvid(自引归 R1)、某级 ≥2 命中报 multiple。
- **不复用 `case_ref_align.align_cited`**:它只 resolved/未解析二态、无 span,无法表达 R4 四态 standoff。R4 自写 `align_xref`,仅复用底层 `normalize_clause_no` / 条号归一 / 超界校验。
- **四态精度是 R4 核心**:`pending_target`(三级全未命中 = 引用未入库外规,夜间重试 / 缺口清单的来源)与 R1–R3 的 `unresolved`(目标在库但定位失败)**有意区分**;`ambiguous`(多命中)不臆测 target。夜间重试 / 缺口清单导出本轮不做(另起一轮),四态正确落库即其前置。

**非显然踩坑**:
- **R3/R4 span 重叠双写**:`《X》第十五条` 里的「第十五条」会被既有 R3 正则也抓(→ R3 unresolved + R4 resolved 双写同一处)。**修**:`run_resolver` 里 R3 候选 span 若落在某 R4 候选 span 内 → 丢弃(跨文档优先)。R1/R2 不与 R4 重叠,无此问题;既有 R1–R3 用例无《》→ xspans 空,行为零回归。
- **测试唯一后缀**:R4 lookup 不限 corpus 全库查,集成 fixture 的 title/doc_number/alias 须带 ULID 唯一后缀,否则撞库中真实 effective doc → 误判 multiple。

## PR #35(`fix/clause-tree-law-conventions`,条款树补国家法律/司法解释体例)合并(2026-06-30)

- **合并时分支落后 main 10 个提交**,`main` 侧另有 chunk_id 撞车修复(`be7dd64`)与小数混排体例(`836beb7`)同改 `clause_tree.py`。
  `clause_tree.py` 自动合并无冲突;`test_clause_tree.py` 冲突(两边各在同位置新增一个测试函数)手解,**两条测试都保留**,非二选一。
- **⚠ 合并前只跑了非栈门,全量模型门控未跑**:因本机 PG/Milvus 栈当时**正被另一并行会话占用**(demo/corpus 批量入库工作),
  按"绝不在别人占着的栈上并发跑集成"的约定放弃了全量集成门,只跑了 `--collect-only`(824 collected,验证 10 提交合并无 import
  断裂)+ 条款树/golden(41 passed)+ common(20 passed)+ ruff + CI 的 `lint-and-test`。**全仓模型门控全量门这次没有跑**,欠账,
  下次拿到干净栈时应补跑一次做确认。

**测试**:`test_ref_resolver.py` +23 用例(extract×8 / align 四态×6 / PgXRefLookup×6 / run_resolver R4×3);全 36 passed;案例侧零回归;`alembic check` 无漂移。
