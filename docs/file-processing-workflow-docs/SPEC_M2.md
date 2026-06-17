# 规格说明:文档处理管线 · 本地 Demo(M2)

> *做什么*与*为什么*的权威来源:`文档处理管线_本地Demo_开发文档_v0.1.md`(V0.1)。
> M1 规格见 `SPEC.md`(已交付,V1/V2/V4/V5 达成);本规格**仅覆盖 M2**。M3(E1 打标 → V8)后续单出。
> 架构与硬契约见 `CLAUDE.md`;完整开发叙述见 `docs/devlog.md`。
> 状态:**等待人工评审**——评审通过前不进入 Plan/Tasks/Implement。

---

## 目标(Objective)

M2 的差异化价值是**验证套件**——demo 的真正卖点是「可验证」(锚点回放、冒烟、对账、重建),证明
**PG 权威 + Milvus 可投影重建**、**四级锚点可回放**、**批次检索冒烟可断言**。在 M1 已跑通的 S0–S5 全链路 +
真实/自构造语料上,补齐 V3/V6/V7 三个验收点,使 **V1–V7 全部通过**、演示脚本第 1–10 步完整可跑。

**关键立项决定(本轮,基于 M1 检查点 D 走查证据)**:**DeepDoc 降为可选**。走查证明真实外规 PDF 的解析失败
根因都在 `clause_tree`(IR 边界**下游**,已在 M1 用 clause_tree 修复:小数编号 / 跨法引用过滤),**与换不换
DeepDoc 无关**。DeepDoc 的真实增量在 layout/OCR/表格结构/扫描件,不在 clause 结构识别。故 **M2 主体 = 验证套件 +
mini golden set;DeepDoc 作为 `ParserAdapter` 边界后的可选/延后任务,不进 V3/V6/V7 验收依赖**(上游 §M2 的
「>1 天回落 light,IR 边界保证不影响其他验收点」预案已为此背书)。

**面向谁**:内部工程 + 对张翼飞的内部演示。**不**对甲方演示、**不**承诺任何质量指标(V0.1 §0.2)。

### 验收点(V0.1 §0.1,逐字保真)

| # | 验证点 | 对应组件 | 验收方式 |
|---|---|---|---|
| **V3** | 四级锚点(条款→文档→页码→版本)可回放 | §21 **T4 锚点回放** | demo 集锚点回放通过率 **100%**(degraded 文档除外) |
| **V6** | PG 权威 + Milvus 可重建 | §12 **rebuild** | drop collection → `demo rebuild` → 同一查询 **top10 结果一致**(无需重编码,向量从 PG 冷备回灌) |
| **V7** | 批次检索冒烟 | §21 **T2 冒烟** | 批次冒烟通过率 **100%**(demo 集),断言**含 status 过滤位** |

(V1/V2/V4/V5 = M1 已达成;V8 = E1 打标,M3。)

## 范畴(Scope)

**M2 含(交付)**:
- **T2 冒烟** `verify/smoke.py` + `demo verify smoke`,且 finalize 自动触发。
- **T4 锚点回放** `verify/anchor_replay.py` + `demo verify replay`,且 finalize 自动触发。
- **对账 reconcile** `verify/reconcile.py` + `demo verify reconcile`(PG 权威重灌)。
- **rebuild** `verify/rebuild.py` + `demo rebuild`(drop → 冷备零编码回灌)。
- **mini golden set**:5–8 件手工标注条款树(JSON ground truth),`pytest` 断言条款树结构 **F1 = 1.0**。
- **report 扩展**:加 `t2_pass_rate` / `t4_pass_rate` 键(M1 决策 1 预留:M2 接入时再加,不留半成品)。
- D5 占位(smoke/replay/reconcile/rebuild 的 `Exit(2)` 桩)→ 替换为真实实现。

**M2 延后(本轮不做,留独立轮;不进 V3/V6/V7 验收依赖)**:
- **DeepDoc adapter**:本轮**保持 `ParserAdapter` 边界现状**(light 唯一实现,接口不动),DeepDoc 单列后续任务
  (vendored from RAGFlow)。真接入那轮,「light→DeepDoc 切换后 mini golden set 仍全过」是其准入门(parser-swap
  回归);**不接入不影响 V1–V7**(IR 边界保证)。

**M2 不含(延后,非裁掉)**:E1 义务打标(M3 → V8)、L2 LLM 元数据辅助、表格块 LLM 摘要、OCR 分支(扫描件仍
QUARANTINED 演示隔离路径)。生产 §21 的 T1/T3/T5/T6 已在 V0.1 裁掉(只锚定推测失败的机制)。

## 技术栈(Tech Stack)

同 M1(`SPEC.md`):Python 3.11 · typer · SQLAlchemy 2.x + Alembic · PG16 · Milvus 2.4 · 本地 FlagEmbedding
BGE-M3 · rapidfuzz · pydantic。**M2 不引入新运行期依赖**(验证组件复用既有 PG/Milvus/Embedding/ObjectStore)。
DeepDoc(若接入)新增依赖(ONNX runtime + OCR 资产),**单列、需先问**;驻场无外网须文档化离线预置。

## 验证组件(精确行为,V0.1 §21.2 逐字)

| 组件 | 行为 | 触发 |
|---|---|---|
| **T2 冒烟** | 每文档 1 条合成查询 = **标题 + 首条款前 30 字** ⚠,断言 **hit@50** 且携带 `status=effective` 过滤位;失败记 `E801`(未命中)/`E802`(过滤缺失)入报告,**不回退批次** | finalize 自动 + `verify smoke` 手动 |
| **T4 锚点回放** | 逐 chunk:按 `page_start` 取原件该页(**±1 页**)文本 → **剥离面包屑后精确匹配**定位;**degraded 豁免**(且显式标注) | finalize 自动 + `verify replay` 手动 |
| **对账 reconcile** | 逐 `doc_version` 比对 **PG chunk 数 vs Milvus count**,不平 → `E701` + **以 PG 为准重灌** | `verify reconcile` |
| **rebuild** | drop collection → 从 **PG chunks + bytea 冷备**全量重灌(**零编码**) | `demo rebuild` |

**硬约束**:验证组件**对终态无阻断权**——只把结果写入批次报告(V0.1 §21.2)。`E801/E802/E701` 入报告不改
`pipeline_status`。degraded 文档:T4 豁免、仍入 T2/对账/rebuild。

## 命令(Commands · M2 实现 D5 占位的真实版)

```bash
demo verify smoke                 # T2 批次冒烟(全 effective 文档),通过率入报告;非零退出当且仅当有 E801/E802
demo verify replay                # T4 锚点回放(degraded 豁免),通过率入报告;非零退出当且仅当有未匹配
demo verify reconcile             # PG vs Milvus 逐 doc_version 对账,不平以 PG 重灌 + E701
demo rebuild                      # drop audit_corpus → 从 PG chunks + bytea 冷备零编码回灌
demo report <batch>               # 现有四项 + 新增 t2_pass_rate / t4_pass_rate
# verify idempotency(M1 已实现,V5)/ ingest/status/queue/meta/search/reprocess 不变
```

开发命令同 M1:`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`、`alembic upgrade head`。
真模型/向量化测试 gate 在 `PIPELINE_EMBEDDING_MODEL`(本地 BGE-M3),未设则 skip,绝不联网下载。

## 项目结构(Project Structure)

```
src/pipeline/verify/
├── __init__.py
├── idempotency.py     # M1 已建(V5)
├── smoke.py           # M2:T2 冒烟(合成查询 + hit@50 + status 过滤断言)
├── anchor_replay.py   # M2:T4 逐 chunk 取页(±1)剥面包屑精确匹配
├── reconcile.py       # M2:PG vs Milvus 逐 doc_version 对账 + PG 重灌
├── rebuild.py         # M2:drop + 冷备零编码回灌
└── report.py          # M1 已建;M2 加 t2/t4 键
fixtures/golden/        # M2:5–8 件手工标注条款树 ground truth(JSON);或就地标注 batch01 子集
tests/
├── test_smoke.py / test_anchor_replay.py / test_reconcile.py / test_rebuild.py   # M2
└── test_golden_set.py # M2:条款树 F1 = 1.0
```

`verify` 模块为**纯/半纯函数**,签名 `(ctx, ...) -> Report`(同 `idempotency.check_idempotency` / `report.build_report`
范式),只读 PG/Milvus/ObjectStore + 返回结果对象;由 CLI 落报告。**不改 stage、不动状态机、不跨 stage import**。

## 代码风格(Code Style)

复用 M1 既有范式(见 `verify/idempotency.py`、`verify/report.py`)。验证组件返回 dataclass 报告 + 人读检查行:

```python
# src/pipeline/verify/smoke.py
@dataclass(frozen=True)
class SmokeResult:
    passed: bool
    per_doc: list[dict]   # {doc_version_id, hit, rank, has_status_filter, error_code?}
    pass_rate: float | None

def run_smoke(ctx: StageContext, doc_version_ids: list[str]) -> SmokeResult:
    """每文档合成查询(标题+首条款前30字)→ search(topk=50)→ 断言命中 + status 过滤位在。
    失败记 E801/E802 入 per_doc;不改 pipeline_status(评测组件无阻断权)。"""
    ...
```

约定:`snake_case` 函数/变量,`PascalCase` 模型/枚举,错误码沿用 `E7xx`/`E8xx`(§11.2);⚠ 值从 config 读
(T2 合成查询「首条款前 30 字」的 30、hit@50 的 50、T4 的 ±1 页与匹配阈值);行宽 100,`ruff`(E/F/I/UP/B)。

## 测试策略(Testing Strategy)

框架 `pytest`,目录镜像 `src/pipeline/`。M2 新增:
- **mini golden set**(**已定:batch01 内规 docx 子集 + 边界件**):`fixtures/golden/<doc>.json` = 该文档**手工标注
  的完整条款树**(节点类型/编号/层级,= `build_tree` 输出 JSON 镜像作 ground truth schema)。`test_golden_set.py`
  对每件跑 `build_tree` 与 ground truth 比对,断言条款树结构 **F1 = 1.0**(demo 集必须完美解析;生产 50 件集 ≥0.98)。
  覆盖:标准章节条、`第X条之一` 插入条、虚拟根/无章通知。小数体例(ext_sse)/外规 PDF 本轮**不纳入**
  (`test_clause_tree` 单测已覆盖小数;标注成本高)。
- **T2/T4/reconcile/rebuild 集成测试**:连真 PG+Milvus(+ 模型 gate),seed 或复用 ingest 后的批次,断言
  组件行为 + 报告字段;各自按 batch_id 反 FK 序清理(同 M1 集成测试范式)。
- **parser-swap 回归**:DeepDoc 本轮不接,该回归门**留 DeepDoc 真接入那轮**启用(切到 DeepDoc 后 golden set 仍全过)。
- 单元级:T2 合成查询构造、T4 面包屑剥离 + ±1 页匹配、对账计数比对逻辑,均可免栈/免模型纯测。

`demo verify idempotency`(M1)+ 演示脚本第 6 步(report T2/T4 100%)、第 10 步(rebuild top10 一致)为集成门。

## 边界(Boundaries)

**始终(Always)**:
- 验证组件**无终态阻断权**——只写报告(V0.1 §21.2)。`E801/E802/E701` 不改 `pipeline_status`。
- 复用既有接口(`ParserAdapter`/`EmbeddingClient`/`ObjectStore`/`PgIO`/`MilvusIO`),不旁路实现。
- rebuild **零重编码**——只从 PG `chunks` + bytea 冷备回灌(`dense_from_bytes`/`sparse_from_bytes`);冷备是
  「Milvus 不承担数据安全责任」架构原则的演示。
- 硬契约逐字不动:`chunk_id` 公式、写入顺序、Milvus `audit_corpus` schema、PG 字段(add-only)。
- 提交前 `pytest` + `ruff check .` 全绿;`alembic/versions` 纳入 lint(autogenerate 后 `ruff --fix`+`format`)。

**先问(Ask first)**:
- 引入 DeepDoc 及其依赖(ONNX/OCR)、或任何技术栈表外依赖。
- 任何对硬契约 / IR schema / 状态机枚举 / PG 列的改动(均 add-only,改名/删除需批准)。
- mini golden set 的语料构成与标注口径。
- 把 M3(E1/L2)提前并入 M2。

**绝不(Never)**:
- **伪造验证断言**(T2/T4/reconcile/rebuild)让演示看起来完整(D5 占位的非零退出就是此原则的体现)。
- 验证组件回退/改写批次终态。
- 为变绿删除或弱化失败测试;为「简化」删改 PG 列 / IR 字段。
- 在默认路径调用 LLM(M2 仍零 LLM;DeepDoc 的 OCR 非 LLM)。

## 成功标准(Success Criteria)

| # | 标准 | 检查方式 |
|---|---|---|
| V3 | demo 集 T4 锚点回放 100%(degraded 除外) | `demo verify replay` → 通过率 100%;degraded 件显式标注豁免 |
| V6 | drop → rebuild → 同查询 top10 一致(零编码) | `demo rebuild` 后对比 rebuild 前后同 query top10 一致 |
| V7 | 批次 T2 冒烟 100%,断言含 status 过滤位 | `demo verify smoke` → 通过率 100%,每条断言 `status=effective` 过滤在 |
| — | V1–V7 全过 + 演示脚本第 1–10 步端到端 | 按 V0.1 §10 手动走查(含步骤 6 report T2/T4、步骤 10 rebuild) |
| — | mini golden set 条款树 F1 = 1.0 | `pytest test_golden_set.py` |
| — | 单元 + 集成测试 + lint 通过 | `pytest` 与 `ruff check .`;真模型门控测试在本地 BGE-M3 下全跑 |

`demo report <batch>` 输出加 `t2_pass_rate` / `t4_pass_rate`(M1 缺省,M2 接入)。

## 风险(Risks · 据 M1 走查)

- **R-M2-1 T4 对真实外规/小数文档**:T4 按 `page_start` 取原件页 ±1 精确匹配。ext_sse(143 页小数编号)、外规
  PDF 的页码锚点与 chunk 文本须对齐;真实 PDF 排版可能使「剥面包屑后精确匹配」命中率 <100% → 需 rapidfuzz 容差
  口径(阈值 ⚠ 入 config)或界定 degraded。**Plan 阶段先在已索引的 batch01 上探 T4 命中率**。
- **R-M2-2 Milvus `num_entities` 计数语义**:upsert churn 使全集 `num_entities` 虚高(M1 已观察 108>100);
  **reconcile 须用逐 doc `count(dvid)`(query-by-PK,准确)**,不用全集 num_entities;rebuild 后为纯 insert,计数干净。
- **R-M2-3 DeepDoc vendoring**:ONNX/OCR 依赖 + 驻场离线 + >1 天回落预案。可选,不阻 V3/V6/V7。
- **R-M2-4 golden set 标注成本**:5–8 件手工标注条款树是人工活;Plan 阶段定语料子集 + 标注工具/格式。

## 已定决策(本轮,原"开放问题")

1. **mini golden set 语料** = **batch01 内规 docx 子集 + 边界件**(标准章节条 docx 数件 + `第X条之一` 插入条 +
   无章通知/虚拟根),5–8 件。**ground truth schema = `build_tree` 输出的 JSON 镜像**(节点类型/编号/层级),
   `test_golden_set.py` 比对断言条款树结构 F1 = 1.0。小数体例(ext_sse)与外规 PDF **本轮不纳入** golden set
   (标注成本高;小数解析已有 `test_clause_tree` 单测覆盖)。
2. **DeepDoc** = **本轮不做,留独立轮**。`ParserAdapter` 边界保持现状(light 唯一实现,接口不动),DeepDoc 单列
   后续任务。**V1–V7 不依赖 DeepDoc**;parser-swap 回归门(golden set 仍全过)在 DeepDoc 真接入那轮再启用。
3. **T4 命中率口径** = **Plan 阶段先在已索引 batch01 实测精确匹配率,据结果再定**(精确 vs rapidfuzz 容差 vs
   界定豁免)。阈值/容差口径(若需)⚠ 入 config。
4. **演示脚本** = **据本会话 M1 实跑微调措辞**(反映真实终态分布 9 INDEXED + 1 DEGRADED_INDEXED + 1 QUARANTINED
   与实际命令输出),保持与 demo 真实行为一致;骨架仍循 V0.1 §10 第 1–10 步。

---

*下一步:人工评审本规格 → 通过后进入 Phase 2(Plan)。*
