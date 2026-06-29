# SPEC: ref_resolver R4 跨文档指代(§6.7 / CP-001,T2.4)

> SDD 阶段 1(Specify)。依据 `docs/文档处理与语料库构建_技术框架设计_v1.6.md` §6.7(生产 v1.6 保真)+ 本目录 `GAP.md` 第 4 节/§Z L-1 邻接项/`RTM.md` §6.7 行。
> 协作流程:本 SPEC 经人工批准 → `planning-and-task-breakdown`(PLAN/TASKS)→ `incremental-implementation`+`test-driven-development` 逐任务落地 → 交 Codex 复审。**本阶段只写规格,不写代码。**
> 产物落 `docs/file-processing-workflow-docs/`(`SPEC_REF_R4` / `PLAN_REF_R4` / `TASKS_REF_R4`;不覆盖既有 P0 三件)。
> 工作树:`feat/ref-resolver-r4`(隔离;集成栈全局单例,跑前与并行会话对齐、串行)。

## 0. 决策记录(已与用户确认)

| # | 决策点 | 选定 | 理由 |
|---|---|---|---|
| D1 | R4 三级匹配的 lookup 实现 | **新建 R4 专用 `XRefLookup`**(包 PG 查询 + dict_aliases 第三级 + ambiguous 多命中检测);案例侧 `case_ref_align.py` / `case_l2.py` **零改动** | blast radius 最小,本轮只动 `chunking/ref_resolver`;不碰案例 LLM 链路(避免一轮交付牵动两个富集子系统)。案例侧接别名作独立后续(`case_ref_align.py:4` 的 TODO 继续保留) |
| D2 | 本轮范围 | **核心对齐 only**:正则提取「《标题》(文号)?第N条」+ 三级对齐 → 写 `clause_references` 四态(resolved/ambiguous/pending_target/unresolved) | 边界最清、TDD 可闭环。`pending_target` 夜间全量重试任务 + 永久未解析「语料缺口清单」导出 CLI 两个配套子系统**另起一轮**(§6.7 它们随 W2 外规分批入库逐步收敛,本轮只把状态正确落库即满足其前置) |
| D3 | 与 `case_ref_align.align_cited` 的关系 | **复用底层工具**(`normalize_clause_no` / `_clause_no` 条号归一 / 超界校验思路),**不复用 `align_cited` 本体** | `align_cited` 输出 `{doc_no,title,clause_path_norm,resolved}` 且只有 resolved/未解析二态,无法表达 R4 的 ambiguous/pending_target 四态、也不产 standoff span。R4 自写 align 产 `ParsedRef`(四态 + span) |
| D4 | `method` 字段 | **恒 `rule`** | §6.7:字段预留以**禁止**未来混入不可区分的 LLM 解析结果。R4 别名表是人工维护规则查表,非 LLM |

---

## 1. Objective

填充 `clause_references` 表的 **R4(跨文档)** 行:S3 切块后,对内规/外规**条文块**正文里**字面写出**的跨文档引用「《X办法》(〔YYYY〕N号)?第N条」做纯规则 standoff 解析,经三级匹配(文号精确 → 标题精确 → `dict_aliases` 简称别名)归一到 `target_doc_version_id` + `target_clause_path_norm`,按命中情况落**四态** `resolution_status`,写入独立 standoff 表(逐字原文不动)。

**边界澄清(§6.7 + 模型 docstring `pg_models.py:228`)**:R4 仅解析正文**已写出的字面引用**,**不是**"内规覆盖了哪条外规义务"的语义映射(后者属功能2 比对智能体「必要性覆盖」,不在本管线)。

**成功 = `RTM.md` §6.7「R4 跨文档」行从 ❌ 翻 ✅ 并挂通过测试**(详见 §10)。

## 2. 范围边界(In / Out)

**In(本轮交付)**
- `extract_xrefs(text, body_offset)`:纯函数,正则提取正文里的「《标题》(文号)?第N条?」候选 + span(跳面包屑前缀)。
- `XRefLookup`:三级匹配 lookup(文号→标题→`dict_aliases` 别名;多命中→ambiguous 信号)。Protocol + PG 实现 + fake 可测。
- `align_xref(candidate, lookup, self_dvid)`:候选 → `ParsedRef`(R4,四态,跨文档 target)。
- `run_resolver` 集成:R1–R3 之后追加 R4 段,构造 `XRefLookup(ctx.db)`,写 `clause_references`;幂等(沿用既有 `clear_refs` 全 dvid 清,无新清理)。
- `dict_aliases` 种子样例补充(`seeds/`,人工维护起点 + 集成测试可命中数据)。

**Out(本轮不做,留后续轮次)**
- `pending_target` 夜间全量重试任务(§6.7;随 W2 外规分批入库收敛)。
- 永久未解析「语料缺口清单」导出 CLI(§6.7;供金总补采)。
- 案例侧 `case_ref_align` 接 `dict_aliases` 别名第三级(D1:案例侧零改动)。
- R4 的窗口渲染注释(`ref_render` 对「《X》→〖文档标题+文号〗」的渲染;查询侧 S6 窗口装配消费,本轮聚焦填充表)。
- `chunks.internal_refs[]`:§6.7「保留不删、停止新写」,本轮不碰。

## 3. 契约与依赖(全部已就位,**预期零迁移**)

| 依赖 | 位置 | 状态 |
|---|---|---|
| `clause_references` 表(span/ref_type/target_doc_version_id/target_clause_path_norm/resolution_status/method) | `pg_models.py:223`(迁移 0008/0010) | ✅ `resolution_status` 已 `String(16)`、注释含 `ambiguous/pending_target`;`target_doc_version_id` 应用层引用(非 FK,可跨文档/指向未入库外规);`method` 默认 `rule` |
| `dict_aliases` 表(alias PK → canonical_doc_number / canonical_title / dict_version) | `pg_models.py:306`(迁移 0009) | ✅ 表建;本轮补样例 seed |
| `normalize_clause_no` / `to_halfwidth` / `strip_ws` | `chunking/normalize.py` | ✅ 复用(条号归一,与 R1–R3 / 案例侧一致) |
| `run_resolver` 集成点 + `_safe_refs` 非阻断包裹 | `cli.py:153–155`(`_structuring` 内,s3 之后) | ✅ 已挂;R4 加进 `run_resolver` 内即可,集成点签名不变 |
| `clear_refs`(幂等重打,先于 s3 删 chunk) | `ref_resolver.py:111` | ✅ 删全 dvid 的 `clause_references`,已覆盖 R4 行,无需新增清理 |

> **若实现中发现需迁移**(如新增索引/列),立即停下走 "Ask first"——本轮设计目标是零迁移。

## 4. 解析规则(R4 核心规格)

### 4.1 正则提取(纯函数,无栈)
从 `body_offset` 起扫描(跳过面包屑前缀,沿用 R1–R3 的 `_in_body` 纪律),识别:

```
《(标题)》  [紧邻可选]（?〔YYYY〕N号 | [YYYY]N号?）?  [可选] 第(条号)条(之(N))?
```

- 标题 = 书名号 `《…》` 内文本(非贪婪,不跨另一个 `《`)。
- 文号 = 紧邻标题后的括号内发文字号(中文〔〕或方括号 []),可缺省。
- 条号 = 标题/文号后紧邻的「第X条(之N)?」,可缺省(只引文档不引条)。
- 一条正文可含多个跨文档引用 → 多 `ParsedRef`,各带独立 span。
- `surface_text` = 完整匹配原文(截断 256,与既有列宽一致)。

### 4.2 三级匹配(`XRefLookup`)
按顺序,任一级命中即停:
1. **文号精确**:`dict`/`doc_versions.doc_number == 文号`(effective)。
2. **标题精确**:`doc_versions.title == 标题`(effective)。
3. **别名**:`dict_aliases.alias == 标题` → 取 `canonical_doc_number`(优先)/`canonical_title` → 回到第 1/2 级精确查。

**corpus 范围**:R4 匹配 effective 文档,**默认不限 corpus_type**(内规可引内规或外规;与案例侧有意不同——案例只引外规故限 P-EXT)。排除指向当前 dvid 自身(自引属 R1)。→ **见 §11 Open Q1**。

### 4.3 四态语义(`resolution_status`)
| 状态 | 触发 | target_doc_version_id | target_clause_path_norm |
|---|---|---|---|
| `resolved` | 命中唯一 doc + 条号在该 doc 内命中;或只引文档不引条(文档级命中) | 命中 doc | 命中 path / None(文档级) |
| `ambiguous` | 某一级 **多 doc 命中**(同标题/别名跨多 effective 文档) | None(不臆测) | None |
| `unresolved` | 命中唯一 doc 但**条号超界**(doc 在库、该条不存在)/ 条号无法归一 | 命中 doc | None |
| `pending_target` | 三级**全未命中**(引用了尚未入库的外规) | None | None |

- `pending_target` 与 R1–R3 的 `unresolved` 语义有别:前者="目标文档不在库"(夜间重试 + 缺口清单的来源),后者="目标在库但定位失败"。**四态精度是 R4 的核心价值,测试逐态钉死。**
- 条号归一/超界校验复用案例侧思路(`normalize_clause_no` + 目标 doc `clause_path_norm` 末段比对)。

### 4.4 作用域
- 仅扫 `chunk_type == "clause" and not is_parent` 块(`run_resolver` 既有过滤)。案例/QA 块的「第X条」是引用外规、走 `case_ref_align`,不重复。
- R4 与 R1–R3 在同一 `run_resolver` 内产出,合并按 span 排序写入。

## 5. lookup 设计(`XRefLookup`,镜像 `RegLookup` 注入纪律)

```python
class XRefLookup(Protocol):
    def resolve(self, doc_number: str | None, title: str | None) -> XRefHit: ...

@dataclass(frozen=True)
class XRefHit:
    status: str          # "single" | "multiple" | "none"
    doc_version_id: str | None
    doc_number: str | None
    clause_norms: frozenset[str]   # 命中 doc 全 chunk 的 clause_path_norm(超界校验)
```

- **PG 实现 `PgXRefLookup(db, self_dvid)`**:三级查 effective 文档(不限 corpus,排除 self_dvid);`multiple` 经 `.all()` 计数判定(≥2 → ambiguous)。
- **fake 实现**:单测注入,免栈断言四态(对齐 `case_ref_align` 的 fake-lookup 模式)。
- 不复用 `PgRegLookup`(限 P-EXT + `.first()` 不报多命中,语义不合);但二者**接口形状对齐**,便于将来若决定合并。

## 6. 集成点(`run_resolver`,签名不变)

```
clear_refs(ctx, dvid)        # 既有,删全 dvid(含 R4)
... R1–R3 段(既有 resolve_refs)...
... R4 段(新):lookup = PgXRefLookup(ctx.db, dvid);逐 clause 块 extract_xrefs → align_xref → rows ...
s.add_all(rows)              # R1–R4 合并写
```
- `_safe_refs` 既有非阻断包裹不变(R4 失败不阻断 _structuring,同富集纪律)。
- R4 引一次 PG(lookup),但仍在 `run_resolver`(有 ctx)层;提取/对齐纯函数可单测。

## 7. Code Style(镜像 `ref_resolver` / `case_ref_align` 既有纪律)

- 纯逻辑(extract/align)无栈、可直接单测;PG 经 Protocol 注入。
- 四态显式分支,不臆测(ambiguous/pending_target 一律 target 留 None)。
- CJK 注释行宽 ≤100(超则独立行)。`method="rule"` 硬写。
- 复用既有 `_tail` / `_clause_no` / `normalize_clause_no`,不另造轮子。

## 8. Testing Strategy

- **纯单元(无栈,必跑)**:
  - `extract_xrefs`:有文号/无文号/无条号(文档级)/多引用/书名号相邻/插入条「之N」/面包屑跳过/非引用噪声不误抓。
  - `align_xref`(注入 fake lookup):resolved（条号命中）/ resolved(文档级)/ ambiguous(多命中)/ unresolved(超界)/ unresolved(条号无法归一)/ pending_target(全未命中)。
- **集成(连 PG,栈未起 skip)**:`run_resolver` 写 R4 行——`PgXRefLookup` 真查 `dict_aliases`+`doc_versions`+`chunks`;别名级命中;ambiguous(造同标题两 effective doc);pending_target;幂等(重跑不翻倍);R1–R3 行不回归。
- **回归**:案例侧 `test_case_ref_align` / `test_case_l2` 零改动零回归(D1 验证)。
- **门控**:波及范围 `pytest pipeline/tests/test_ref_resolver.py`;合并前全仓 + 模型门控全量跑一次(干净栈)。`ruff check` 绿。
- 测试加在既有 `test_ref_resolver.py`(基名全仓唯一约束;R4 与 R1–R3 同模块)。

## 9. Boundaries

- **Always**:TDD 先写失败测试;提取/对齐纯函数可单测;非阻断(`_safe_refs`);`method="rule"`;add-only;改 `chunking/` 前已读 `structuring_devlog`;`ruff` 绿;集成测按 batch_id 反 FK 序清理。
- **Ask first**:**任何 Alembic 迁移**(本轮目标零迁移,一旦需要就停);改 `case_ref_align`/`case_l2`(D1=不改);新增依赖(本轮无)；改 `run_resolver` 对外签名。
- **Never**:把 R4 LLM 化(method 恒 rule);改 `chunk_id` 公式;动案例 LLM 链路;并发跑集成栈(worktree 隔离 + 串行,跑前 `demo down -v && demo up`);给 ambiguous/pending_target 臆测 target。

## 10. Success Criteria(具体可测)

1. `RTM.md` §6.7「R4 跨文档」行翻 ✅,挂本轮新增测试 id。
2. `extract_xrefs` 正则单测覆盖 §8 全部边界,绿。
3. `align_xref` 四态单测(6 态场景)逐态断言 status + target,绿。
4. `run_resolver` 集成测:R4 四态正确落 `clause_references`(含别名级命中 + ambiguous + pending_target)+ 幂等 + 仅 clause 块,绿(栈起时)。
5. R1–R3 既有 10 单测 + 3 集成测**零回归**;案例侧测试零回归。
6. `alembic check` 无漂移(**零迁移**);`ruff check .` 绿。
7. 合并前全仓 + 模型门控全量一次通过(无模型时相关 skip)。

## 11. 门控决策(已与用户确认 2026-06-28)

- **Q1(corpus 范围)→ 定案:不限 corpus_type**。R4 lookup 匹配 effective 任意语料文档(内规可引内规/外规),排除 self_dvid 自引(属 R1)。同标题跨多 corpus → ambiguous。与案例侧限 P-EXT 有意不同。
- **Q2(dict_aliases 种子)→ 定案:补真实样例 v0-draft**。`seeds/dict_aliases.csv` 补少量常见简称(证券法/公司法等)作人工维护起点 + 集成测试命中数据,标 v0-draft 待评审(对齐 `dict_violation_types` 口径,§16-6 类比)。
- **Q3(ambiguous 处置)→ 定案:`status=ambiguous` + target 留 None**。多命中不臆测,留人工/夜间裁决;standoff 表无候选列,不记多候选明细(保持不臆测纪律)。

## 12. 假设(ASSUMPTIONS — 不批即按此推进)

1. `clause_references`/`dict_aliases` 现有 schema 足够承载 R4,**无需迁移**(§3 已核对)。
2. R4 仅在 `run_resolver` 内消费 PG 一次(lookup),不改 `_structuring` 编排顺序、不改 `run_resolver` 对外签名。
3. 不动 `case_ref_align`/`case_l2`/`ref_render`/`chunks.internal_refs`(D1 + Out 范围)。
4. 测试加进既有 `test_ref_resolver.py`,不新建测试文件(同模块 + 基名唯一约束)。
