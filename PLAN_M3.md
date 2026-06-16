# 实施计划:M3(E1 义务打标 + report 全量打磨)

> 依据 `SPEC_M3.md`(已评审通过)。Phase 2(spec-driven)产物,**待人工评审**——通过后进 Phase 3(Tasks)。
> 目标:补 V8(E1 义务预打标,golden set precision/recall ≥0.90 ⚠)+ report 全量打磨。零新依赖、零新迁移、默认零 LLM。

## 方法与总体形状

M3 = **一个富集步(E1)+ 报告扩展**,落在新 `src/pipeline/enrich/` 与既有 `verify/report.py`、`cli.py` 装配层,
**不改 stage、不动状态机、不动硬契约、不动 Milvus schema、零新运行期依赖**(纯正则 + PyYAML 词表;`clause_tags`
表已建)。E1 在 `_structuring` 装配复合内调度(`clear→s3→tag→s4`),与 stage 互不 import。

**R-M3-1(「应」歧义)已由 Plan 探针实测消解**(见下「实测结论」):真实内规/外规上「应」歧义稀疏,整词义务
词表 + 小排除表可压住朴素子串假阳;精确 precision/recall 在 golden set(M3-B)卡死。**这是 M3 唯一的核心不确定性,
已落地为可控工程量**。

## 组件图与依赖

| 组件 | 文件 | 依赖 | 复用 |
|---|---|---|---|
| **config 词表** | `config/obligation.yaml` + `config.py` | — | 镜像 `qc_thresholds.yaml` 加载范式;加 `ObligationConfig`(markers/exclusions/threshold) |
| **E1 打标** | `enrich/e1_obligation.py` | config | `PgIO.get_chunks` + `corpus_rows.indexable_chunks` 口径(非 parent);写 `clause_tags`;`tag`/`clear` 纯函数 |
| **装配接入** | `cli.py::_structuring` | E1 | `clear→s3→tag→s4`;`e1_enabled` gate;不跨 stage import |
| **golden set** | `fixtures/golden/obligation/*.json` + `tests/test_obligation_golden.py` | E1 | `tag()`;真值=人工标注 is_obligation(≥20 正 + ≥10 负) |
| **report 打磨** | `verify/report.py` | E1(义务覆盖项) | `clause_tags`(义务)/`review_queue`(队列)/`DocVersion.version_status`(版本链)/`Document.corpus_type`(语料拆)/JSON 落 `reports/<batch>.json` |
| **CLI/演示** | `cli.py` + 演示脚本 | report | `demo report` 输出扩展;演示补 E1 + report 展示步 |

## 实施顺序(分阶段 + 并行)

- **M3-0 config + 词表先行**(小):建 `config/obligation.yaml`(markers/exclusions/accuracy_threshold ⚠,初值见下),
  `config.py` 加 `ObligationConfig` 并接 loader。验证:config 加载含 obligation 段;既有 V1–V7/ruff/pytest 仍绿。
- **M3-A E1 打标**(M3-0 后):`enrich/e1_obligation.py`(`tag`/`clear` 纯函数,正则全从 config)+ `_structuring` 装配接入
  + 单元测试(markers 命中 / exclusions 排「应」歧义 / 多词 evidence)+ 集成测试(连 PG:`clear`+`tag` 幂等、reprocess
  重入不撞 FK、`e1_enabled=false` 零写)。
- **M3-B golden set**(标注可与 M3-A **并行预备**;断言测试 M3-A 后):标注 batch01 内规子集 + 外规取样的 is_obligation
  真值(含足量负例),`test_obligation_golden.py` 断言 precision ≥ 阈值 且 recall ≥ 阈值。
- **M3-C report 打磨**(队列/版本链/语料拆/JSON 可与 M3-A **并行**;义务覆盖项依赖 M3-A):`verify/report.py` 加五项 +
  `reports/<batch>.json` 落文件;`test_report.py` 扩展。**report 绝不现场加载模型**(M2 纪律)。
- **M3-D 端到端验收**(全部后):干净栈跑 ingest→…→INDEXED,E1 随管线打标;`demo report` 出全五项;V8 golden 绿;
  V1–V7 回归全过;据实跑微调演示脚本措辞。

```
M3-0(config+词表) ──┬─ M3-A(E1 tag/clear + 装配 + 单测/集成)──┬─ M3-B(golden: P/R ≥0.90)──┐
                     │                                          └─ M3-C(report 五项 + JSON)──┴─ M3-D 验收
                     └─(M3-B 标注 / M3-C 队列·版本·语料部分 可与 A 并行预备)
```

## 验证检查点(阶段间)

1. **M3-0 后**:`load_config().obligation` 含 markers/exclusions/threshold;既有套件 + ruff 全绿。
2. **M3-A**:单元(markers/exclusions/应边界)+ 集成(tag/clear 幂等、reprocess FK-safe、e1_enabled=false 零写)通过;
   E1 异常不阻断 `_structuring` 终态(文档仍进 META_REVIEW)。
3. **M3-B**:`test_obligation_golden.py` precision ≥0.90 且 recall ≥0.90(⚠ from config)。
4. **M3-C**:`demo report` 出义务覆盖/队列处置/版本链/按语料拆 + `reports/<batch>.json`;report 不触发模型加载。
5. **M3-D 硬门**:演示端到端;V8 + V1–V7 全过;`pytest` + `ruff check .` 全绿;`alembic check` **无漂移(M3 无新迁移)**。

## 风险与缓解

- **R-M3-1 「应」歧义(已实测消解)**:整词义务词表 + 排除表压住朴素子串假阳(内规 0 陷阱、外规 ext_sse 525「应」仅
  ~11 朴素假阳全被 STRONG 排除)。**精确 P/R 在 golden set 卡**;词表初值据真文本给(见下)。Task 阶段在 golden 上迭代。
- **R-M3-2 reprocess FK(已定)**:`clause_tags.chunk_id`→`chunks.chunk_id`;`clear`-先于-s3 删旧 tag 后再 `replace_chunks`,
  零迁移。集成测试必须覆盖「INDEXED 件 reprocess→重打→不撞 FK + tag 行集幂等」。
- **R-M3-3 chunk 级 vs 行级**:Plan 探针是 PDF 行级(续行噪声);真 E1 在 clause 级 chunk(整条款文本,义务词必在条款内)
  → chunk 级应**比行级更干净**。golden set 用真 chunk 文本验,消除此差。
- **R-M3-4 golden 负例不足→recall 门虚高**:标注必须含足量负例(施行日期句/释义句/纯定义句),≥20 正 + ≥10 负;
  Plan 圈定 batch01 内规子集 + 外规取样,Task 定具体件。
- **R-M3-5 report 蔓延**:圈定五项,超出 Ask first;report 只聚合读取、不加载模型(M2 既定,避免无模型卡住)。

## config 新增(⚠ 值,M3-0)

`config/obligation.yaml`(镜像 `qc_thresholds.yaml`):

| 键 | 用途 | 初值(据 Plan 探针真文本) |
|---|---|---|
| `markers` | 强义务情态词(整词) | 应当 / 应该 / 必须 / 不得 / 禁止 / 严禁 / 不应 / 不准 / 应予 / 须经 / 有义务 / 负有 / 责令 |
| `bare_ying` | 是否启用「应」单字边界匹配(前不接排除字) | true(配 exclusions 用) |
| `exclusions` | 「应」歧义排除(子串) | 相应 / 适应 / 对应 / 响应 / 反应 / 供应 / 答应 / 顺应 / 效应 / 感应 / 呼应 / 映应 |
| `accuracy_threshold` | V8 precision/recall 门 | 0.90(V0.1 §23) |

`config.py`:`ObligationConfig(markers: list[str], bare_ying: bool, exclusions: list[str], accuracy_threshold: float)`;
`[toggles] e1_enabled` 已存在,不新增开关。

## Plan 阶段实测结论(E1 正则探针,batch01 真文本)

- **内规**(7 件 docx,49 条款段):精炼整词命中 8 条,肉眼**全为真义务**(应当/应/不得);陷阱词(相应/适应…)
  **0 次出现** → 内规上「应」几乎专表义务。
- **外规 ext_xxpl_182**(428 行,「应」99 次):朴素 116 / 强义务 114 行,陷阱触发假阳**仅 1**(相应债权)。
- **外规 ext_sse_listing**(2852 行,「应」525 次):陷阱词仅 15 次、朴素假阳仅 ~11 行(相应决定/相应程序/对应的公司
  /相应审议程序),**STRONG 整词词表全数排除**。
- 结论:**「应」歧义真实但稀疏(<3% 的「应」),整词义务词表 + 小排除表可压住**;V8 的 P/R 决于 golden set 标注质量与
  词表微调(Task 工程量,非研究风险)。词表初值已据真文本固化(见 config 新增)。

---

*下一步:人工评审本计划 → 通过后进入 Phase 3(Tasks),按 M3-0/A/B/C/D 拆任务级验收(每任务带验收 + 验证步骤)。*
