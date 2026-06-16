# 规格说明:文档处理管线 · 本地 Demo(M3)

> *做什么*与*为什么*的权威来源:`文档处理管线_本地Demo_开发文档_v0.1.md`(V0.1,§19.1 / §23 V8)。
> M1 规格见 `SPEC.md`(V1/V2/V4/V5 达成);M2 规格见 `SPEC_M2.md`(V3/V6/V7 达成,检查点 M2)。
> 本规格**仅覆盖 M3**(E1 义务预打标 → V8 + report 全量打磨)。
> 架构与硬契约见 `CLAUDE.md`;完整开发叙述见 `docs/devlog.md`。
> 状态:**等待人工评审**——评审通过前不进入 Plan/Tasks/Implement。

---

## 目标(Objective)

M3 补齐**最后一个验收点 V8**:**E1 义务条款预打标**——零 LLM 的正则 + 词表,把每个(非 parent)chunk
标注是否为「义务条款」(`is_obligation`),写入已建的 `clause_tags` 表。其价值不在打标本身,而在
**为后续「比对智能体」demo 预热**(V0.1 §19.1:E1 是富集链 E1→E2→E3 的起点,E2/E3 留独立轮);并借此
证明:**IR 边界下游可平滑加富集步、不动状态机 / 不动解析器 / 默认仍零 LLM**。

第二部分**report 全量打磨**:把现有批次报告(解析/QC/锚点/T2/T4/retrieval_mode)扩成一份**可对外演示的
批次质量快照**——加义务覆盖、队列处置、版本链、按语料(P-INT/P-EXT)拆分,并 JSON 落文件。

**面向谁**:内部工程 + 对张翼飞的内部演示。**不**对甲方演示、**不**承诺任何质量指标(V0.1 §0.2)。
V8 的「准确率」是 demo 集上的可复现门,非生产 SLA。

### 验收点(V0.1 §23,逐字保真)

| # | 验证点 | 对应组件 | 验收方式 |
|---|---|---|---|
| **V8**(可选开关) | E1 义务条款预打标 | §19.1 **E1 obligation** | 抽 20 条 `is_obligation` 标记人工核对,准确率 **≥90% ⚠** |

(V1/V2/V4/V5 = M1;V3/V6/V7 = M2;V8 = 本轮 M3。)

**本轮对 V8 验收的落地口径**(已定决策 1):上游「抽 20 条人工核对」改为**自动 golden set**——手工标注
fixture 条款的 `is_obligation` 真值,`pytest` 断言 E1 在该集上 **precision ≥ 阈值 ⚠ 且 recall ≥ 阈值 ⚠**
(默认 0.90,config 可调),CI 可复现、不依赖人工。**比上游字面(仅核对「标了的」=precision)严一档**:加 recall
门防「少标保精度」把 V8 刷过去(纯正则若只认 `禁止` 不认 `应当` 也能 precision=100%)。

## 范畴(Scope)

**M3 含(交付)**:
- **E1 打标** `src/pipeline/enrich/e1_obligation.py`:纯函数 `tag(ctx, dvid)` / `clear(ctx, dvid)`,正则 + config
  词表判 `is_obligation`,写 `clause_tags`(零 LLM)。在 `_structuring` 装配层调用(详见「流水线接入」)。
- **config 词表** `config/obligation.yaml`:义务情态词表(markers)+ 排除表(exclusions,解「应」的歧义)+
  准确率阈值 ⚠(镜像 `qc_thresholds.yaml` 范式);`config.py` 加 `ObligationConfig`。
- **golden set**:手工标注 `is_obligation` 真值(JSON),`test_obligation_golden.py` 断言 precision/recall ≥ 阈值。
- **report 全量打磨** `verify/report.py`:加 ① 义务覆盖(命中块数 / 占比,有 golden 时附 E1 precision/recall)
  ② 队列处置统计(`review_queue` 按 queue_type × status)③ 版本链(effective/superseded 计数)
  ④ 按语料 P-INT/P-EXT 拆分核心指标 ⑤ JSON 快照**落文件**(`reports/<batch>.json`,现有落库不变)。
- **演示脚本补步**:在现有 1–10 步后补 E1 打标 + report 全量展示(措辞据实跑)。

**M3 延后(本轮不做,留独立轮)**:
- **E2/E3/E4 富集**(LLM 事项/部门打标、图谱探针)——V0.1 §19.2–19.4,触发式建设(比对智能体启动 / 图谱 POC)。
- **`obligation_keywords` 词典表**——本轮用内置正则 + `config/obligation.yaml` 词表(V0.1 §1.3:词典表随比对智能体建)。
- **search 出义务标**(hit 附 `is_obligation`)——需 PG 回查 clause_tags 注释 hit(不动 Milvus schema)。**本轮不做**
  (决策 B 已定);本轮 report 已覆盖义务可见性。
- **DeepDoc**(M2 已延后,独立轮)、**L2 LLM 元数据辅助**(config 默认关)。

**M3 不含(裁掉/非本轮)**:义务条款的**道义子类型**(义务/禁止/许可分类)——本轮只二元 `is_obligation`(已定决策 2,
贴上游字面 + V8 只验 is_obligation);道义分类正则更复杂、准确率更难守,留 E2 那轮带字典做。

## 技术栈(Tech Stack)

同 M1/M2:Python 3.11 · typer · SQLAlchemy 2.x + Alembic · PG16 · Milvus 2.4 · 本地 BGE-M3 · rapidfuzz · pydantic ·
PyYAML(已用于 qc_thresholds/profiles)。**M3 不引入新运行期依赖**——E1 是纯正则 + 词表,**默认路径仍零 LLM 调用**
(V0.1 §19.1:E1 正则,非 LLM)。

## E1 行为(精确行为,V0.1 §19.1)

| 项 | 行为 |
|---|---|
| **输入** | 某 `doc_version_id` 的**非 parent chunk**(与 `indexable_chunks` 同口径;parent=节级仅 PG,不打标)。degraded 件**照打**(有文本即判)。|
| **判定** | chunk 文本命中 ≥1 个义务情态词(config markers,如 应当/应/必须/须/不得/禁止/严禁/不应/不准…)且不落排除表(exclusions,如 相应/适应/对应/响应/反应/供应/答应),即 `is_obligation`。零 LLM、纯正则。|
| **写出** | **仅命中件写行**:`clause_tags(chunk_id, tag_type="is_obligation", tag_value="true", evidence=<命中词,多则取首/拼接 ≤256>)`。**缺行 = 非义务**(不写否定行,稀疏存储)。|
| **开关** | 复用已有 `[toggles] e1_enabled`(默认 true)。关时:`tag` no-op、不写任何行;report 义务区显 N/A。|
| **幂等** | 重跑同输入产同结果。`clear` 删该 dvid 全部 chunk 的 `is_obligation` 行 → `tag` 重插;`clear`-先于-s3 避 FK(已定决策 6)。|
| **阻断权** | **无**。E1 是富集副作用,不参与状态机迁移、不改 `pipeline_status`、不影响 `StageResult` 终态(与验证组件同纪律,V0.1 §21.2 精神)。|

## 流水线接入(无新状态枚举)

E1 在 **`_structuring` 装配复合**里跑(`cli.py::_structuring`,守 CLAUDE.md「stage 之间不得互相 import」——E1 是
独立 enrich 模块,由装配层调度,不被 s3/s4 import):

```python
def _structuring(ctx, dvid):
    if ctx.config.toggles.e1_enabled:
        e1_obligation.clear(ctx, dvid)   # ① 先清旧 is_obligation(reprocess 重入:避免 s3 删 chunk 撞 FK)
    s3_structure.run(ctx, dvid)          # ② 切块(replace_chunks:删旧 chunk 再插)
    if ctx.config.toggles.e1_enabled:
        e1_obligation.tag(ctx, dvid)     # ③ chunks 已在 → 正则打标,写 clause_tags
    return s4_meta.run(ctx, dvid)        # ④ 终态仍由 s4 决定(E1 不参与)
```

- **不新增状态**:E1 在既有 `STRUCTURING → META_REVIEW` 迁移内完成,状态机硬契约不动。
- **reprocess/重入安全**:`clear` 在 s3 的 `replace_chunks`(删 chunk)**之前**跑,避开 `clause_tags.chunk_id`
  外键(旧 tag 引用即将删除的 chunk)。**这是本规格识别出的一个真问题**,已定取 `clear`-先于-s3(零迁移,见已定决策 6);
  **不取** `ON DELETE CASCADE`(免改 FK)。

## 命令(Commands)

```bash
# E1 打标无独立顶层命令——e1_enabled 时随 ingest/_structuring 自动跑、随 reprocess 重打
demo report <batch>     # 全量打磨:原有指标 + 义务覆盖 + 队列处置 + 版本链 + 按语料拆 + JSON 落 reports/<batch>.json
# V8 验收 = pytest(golden set),非 CLI
```

开发命令同 M1/M2:`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`。**M3 无新迁移**(`clause_tags` 表已建,
取 `clear`-先于-s3 不改 FK)。真模型测试 gate 在 `PIPELINE_EMBEDDING_MODEL`,未设则 skip;**E1 与 report 的
golden/单元测试免栈免模型**(纯 PG + 正则)。

## 项目结构(Project Structure)

```
src/pipeline/enrich/
├── __init__.py
└── e1_obligation.py          # M3:正则+词表义务打标(纯函数 tag/clear),写 clause_tags
config/
└── obligation.yaml           # M3:markers + exclusions + accuracy_threshold ⚠
src/pipeline/config.py        # +ObligationConfig(load obligation.yaml)
src/pipeline/cli.py           # _structuring 装配里插 clear/tag(e1_enabled gate)
src/pipeline/verify/report.py # M3:义务覆盖 + 队列/版本链/按语料 + JSON 落文件
fixtures/golden/obligation/   # M3:手工标注 is_obligation 真值(JSON;复用 batch01 子集条款)
tests/
├── test_e1_obligation.py     # 单元:markers 命中 / exclusions 排除 / 幂等 clear+tag(连 PG)
└── test_obligation_golden.py # golden:E1 在标注集上 precision/recall ≥ 阈值(免模型)
```

`enrich` 模块为**纯/半纯函数**,签名 `(ctx, dvid) -> Result`(同 verify 范式),只读 chunks + 写 clause_tags;
**不改 stage、不动状态机、不跨 stage import**。

## 代码风格(Code Style)

复用既有范式(`verify/idempotency.py`、`chunking/clause_tree.py` 的正则风格)。返回 dataclass 报告:

```python
# src/pipeline/enrich/e1_obligation.py
@dataclass(frozen=True)
class TagResult:
    dvid: str
    tagged: int          # 命中(写行)块数
    total: int           # 受检非 parent 块数

def tag(ctx: StageContext, dvid: str) -> TagResult:
    """非 parent chunk 命中义务情态词(markers 去 exclusions)→ 写 clause_tags(is_obligation, evidence=命中词)。
    e1_enabled 关时不应被调用(由装配层 gate)。零 LLM;幂等由调用前 clear() 保证。"""
    cfg = ctx.config.obligation                  # markers / exclusions / accuracy_threshold(⚠ from yaml)
    ...
```

约定:`snake_case` 函数/变量,`PascalCase` 模型/枚举;⚠ 值从 config 读(markers/exclusions/阈值 全在
`obligation.yaml`,**正则与词表不硬编码**);行宽 100,`ruff`(E/F/I/UP/B)。正则注释密度对齐 `clause_tree.py`。

## 测试策略(Testing Strategy)

框架 `pytest`,目录镜像 `src/pipeline/`。M3 新增:
- **golden set(V8 门)**:`fixtures/golden/obligation/*.json` = 标注条款的 `is_obligation` 真值(取 batch01 内规
  子集,含义务句「应当/不得」与非义务句「本办法自…起施行」「释义」等**负例**)。`test_obligation_golden.py` 跑
  `tag` 后比对真值,断言 **precision ≥ threshold 且 recall ≥ threshold**(⚠ from config,默认 0.90)。负例必须含,
  否则 recall 门无意义。**标注量**:≥30 条(覆盖 ≥20 正例 + ≥10 负例),Plan 阶段定具体件与标注口径。
- **单元(免栈/免模型)**:markers 命中、exclusions 排除「应」歧义(相应/适应/对应…不误判)、多词命中 evidence、
  空/纯表格块不误标——纯函数对字符串可测。
- **集成(连 PG,免模型)**:`clear`+`tag` 幂等(同 dvid 跑两次,clause_tags 行集不变);reprocess 重入不撞 FK
  (`clear`-先于-s3,已定决策 6);`e1_enabled=false` 时不写行。
- **report 单元/集成**:义务覆盖率数学、队列/版本链计数、按语料拆分、JSON 文件落地(`test_report.py` 扩展)。

## 边界(Boundaries)

**始终(Always)**:
- E1 **无终态阻断权**——只写 `clause_tags` + 报告,不改 `pipeline_status`、不动 `StageResult` 终态。
- 正则 / 词表 / 阈值**全从 config 读**(`obligation.yaml`),零硬编码;`e1_enabled` gate 在装配层。
- **默认路径仍零 LLM**(E1 是正则;L2 仍默认关)。
- 硬契约逐字不动:`chunk_id` 公式、写入顺序、Milvus `audit_corpus` schema、IR 边界;PG add-only。
- 复用既有接口(`PgIO`/`StageContext`/config loader),不旁路。
- 提交前 `pytest` + `ruff check .` 全绿;若引迁移则 `alembic upgrade head` + `alembic check` 无漂移,`ruff --fix`+`format` 迁移文件。

**先问(Ask first)**:
- 给 `clause_tags` 或任何表改 schema / 约束(本轮已定**不**改:取 `clear`-先于-s3,无迁移;任何 add-only 外的 PG 改动需批准)。
- golden set 的语料子集与标注口径(正/负例配比、边界句归类)——Plan 阶段细化。
- 把 search 出义务标、E2/E3、或道义子类型提前并入 M3(本轮均不做)。

**绝不(Never)**:
- **伪造 V8**:为过门放宽 golden 真值、或只标极易判的正例刷 precision(故设 recall 门)。
- 在默认路径调用 LLM(E1 必须纯正则)。
- 改 Milvus `audit_corpus` schema 塞 `is_obligation`(违硬契约;要可见走 PG 回查)。
- 为变绿删/弱化失败测试;为「简化」删改 PG 列 / IR 字段。
- E1 异常阻断 `_structuring` 终态(打标失败只记日志 + report,文档照进 META_REVIEW——同验证组件纪律)。

## 成功标准(Success Criteria)

| # | 标准 | 检查方式 |
|---|---|---|
| **V8** | demo 集 `is_obligation` precision ≥ 0.90 ⚠ 且 recall ≥ 0.90 ⚠ | `pytest test_obligation_golden.py` |
| — | E1 随管线自动跑、reprocess 重打且幂等、`e1_enabled=false` 时零写入 | `test_e1_obligation.py`(连 PG) |
| — | `demo report <batch>` 出义务覆盖 + 队列处置 + 版本链 + 按语料拆 + `reports/<batch>.json` 落地 | 手动走查 + `test_report.py` |
| — | 默认路径零 LLM 调用;状态机 / IR / Milvus schema / chunk_id 均未动 | 代码走查 + 既有 V1–V7 回归全过 |
| — | 单元 + 集成 + lint 通过;迁移(若有)无漂移 | `pytest` + `ruff check .` + `alembic check` |

## 风险(Risks)

- **R-M3-1 情态词「应」的歧义(核心风险)**:「应」是义务高频词,但「相应/适应/对应/响应/反应/供应/答应/理应」
  全含「应」→ 纯子串匹配 precision 崩。需正则边界(如「应当」整词 + 「应」后接动词、配 exclusions 表),**Plan 阶段
  在 golden set 上实测 precision/recall 迭代词表**。这是 V8 能否达标的关键。
- **R-M3-2 reprocess FK 撞车**:`clause_tags.chunk_id` → `chunks.chunk_id`;s3 `replace_chunks` 删 chunk 时旧 tag 仍引用
  → FK 违例。已识别并解决:`clear`-先于-s3(已定决策 6,零迁移);集成测试须覆盖 reprocess 重入不撞 FK。
- **R-M3-3 golden 负例不足致 recall 门虚高**:若标注集只含正例,recall 无意义。**标注必须含足量负例**(非义务句),
  Plan 阶段定配比(本规格定 ≥20 正 + ≥10 负)。
- **R-M3-4 report 打磨范围蔓延**:「全量打磨」易无边界扩张。本规格已圈定五项(义务/队列/版本链/按语料/JSON 落文件),
  **超出此五项需 Ask first**;report **绝不现场加载模型**(M2 既定:只聚合读取,不触发 HF 下载)。

## 已定决策(本轮)

1. **V8 验收 = 自动 golden set**(非人工抽 20):标注 is_obligation 真值,断言 **precision ≥ 阈值 且 recall ≥ 阈值**
   (⚠,默认 0.90)。比上游字面严一档(加 recall 门),理由见「验收点」。
2. **打标粒度 = 二元 `is_obligation`**(非道义子类型):贴上游 §19.1 + V8 只验 is_obligation;子类型留 E2 轮。
3. **report 范围 = 全量打磨**五项:义务覆盖 + 队列处置 + 版本链 + 按语料 P-INT/P-EXT 拆 + JSON 落文件。
4. **词表/阈值落 `config/obligation.yaml`**(markers/exclusions/accuracy_threshold),镜像 `qc_thresholds.yaml`;
   `e1_enabled` 复用已有 `[toggles]`。
5. **E1 接入点 = `_structuring` 装配复合**(s3 后、s4 前),不新增状态枚举,不跨 stage import。
6. **reprocess FK 方案 = `clear`-先于-s3**(零迁移):`_structuring` 在 s3 `replace_chunks` 前先 `e1.clear(dvid)`
   清旧 `is_obligation` 行,避开 FK。**不取** `ON DELETE CASCADE`(免改 FK / 免迁移)。
7. **search 不出义务标(本轮)**:M3 只管打标 + report 覆盖;义务可见性由 report 承载。search hit 注释 `is_obligation`
   留下轮(需 PG 回查,不动 Milvus schema)。

## 留待 Plan 细化(非设计分叉,实现口径)

- **golden set 语料**:取 batch01 哪几件、正/负例配比(本规格定 ≥20 正 + ≥10 负)、边界句归类口径。

---

*下一步:人工评审本规格 → 通过后进入 Phase 2(Plan)。决策 A/B 已拍(已定 6/7),仅 golden 语料口径留 Plan。*
