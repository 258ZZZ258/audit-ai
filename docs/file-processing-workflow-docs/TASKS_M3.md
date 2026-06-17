# 任务分解:M3(E1 义务打标 + report 全量打磨)

> 依据 `SPEC_M3.md` + `PLAN_M3.md`(均评审通过)。Phase 3(spec-driven)产物,**待人工评审**——通过后逐任务实现。
> 每任务:单次专注会话可完成、≤5 文件、带验收 + 验证步骤;按依赖排序。集成测试连真栈,模型门控按需 skip。
> **零新迁移**(`clause_tags` 表已建,`clear`-先于-s3 不改 FK);**默认零 LLM**(E1 纯正则)。

## M3-0 · config 词表(先行)

- [x] **M3-0 · E1 ⚠ 配置 + 词表**
  - Acceptance:建 `config/obligation.yaml`(`markers` 整词义务词 / `bare_ying` bool / `exclusions` 应歧义排除 /
    `accuracy_threshold=0.90`,初值据 PLAN 探针真文本);`config.py` 加 `ObligationConfig` 并接 loader,`Settings.obligation` 可读;
    **`e1_enabled` 复用已有 `[toggles]`,不新增开关**
  - Verify:`pytest tests/test_config.py`(断言 obligation 段加载、字段类型、markers/exclusions 非空、阈值=0.90)
  - Files:`config/obligation.yaml`、`src/pipeline/config.py`、`tests/test_config.py`

## M3-A · E1 打标(M3-0 后)

- [x] **A1 · `enrich/e1_obligation.py`(matcher + tag/clear)**
  - Acceptance:`match_obligation(text, cfg) -> (bool, evidence|None)` 纯函数(整词 `markers` 命中 + `bare_ying` 时「应」
    单字加边界、前不接 `exclusions` 字 → 排除 相应/适应/对应…);`tag(ctx, dvid) -> TagResult(dvid, tagged, total)` 对
    **非 parent chunk**(`corpus_rows.indexable_chunks` 口径)打标,命中写 `clause_tags(tag_type="is_obligation",
    tag_value="true", evidence=命中词 ≤256)`,**仅写命中行**;`clear(ctx, dvid)` 删该 dvid 全部 is_obligation 行;
    **正则/词表全从 cfg,零硬编码**
  - 决策点:chunk 文本取 `chunk.text`;多词命中 evidence 取首词(或拼接 ≤256)
  - Verify:`pytest tests/test_e1_obligation.py`——单元(免栈:markers 命中 / exclusions 排「相应/适应/对应」不误判 /
    多词 evidence / 空·纯标点块不命中)+ 集成(连 PG 免模型:seed 含义务+非义务 chunk → tag → 断言命中行数 + evidence;
    `clear`+`tag` 跑两次 clause_tags 行集不变=幂等)
  - Files:`src/pipeline/enrich/__init__.py`、`src/pipeline/enrich/e1_obligation.py`、`tests/test_e1_obligation.py`

- [x] **A2 · `_structuring` 装配接入(clear→s3→tag→s4)**
  - Acceptance:`cli.py::_structuring` 改为 `e1_enabled` 时:`clear(ctx,dvid)` → `s3_structure.run` → `tag(ctx,dvid)` →
    `s4_meta.run`(终态仍由 s4 决定);`clear` **先于** s3 `replace_chunks`(避 `clause_tags` FK);E1 **异常不阻断**
    (吞掉记日志,文档仍进 META_REVIEW);`e1_enabled=false` 时 clear/tag 均不调
  - 决策点:E1 富集无阻断权——同验证组件纪律(异常只记日志,不改 pipeline_status / StageResult 终态)
  - Verify:`pytest tests/test_e1_obligation.py`(扩展,免模型):① seed INDEXED 件(含 chunks+clause_tags)→ 模拟
    `clear`+s3 `replace_chunks` 顺序 → **不撞 FK** + tag 行幂等;② `e1_enabled=false` 走 `_structuring` 零写;
    ③ monkeypatch `tag` 抛错 → `_structuring` 仍返 s4 终态(不阻断)
  - Files:`src/pipeline/cli.py`、`tests/test_e1_obligation.py`

## M3-B · golden set(标注与 A1 并行预备;断言测 A1 后)

- [x] **B1 · obligation golden set + precision/recall 测试(V8)**
  - Acceptance:`fixtures/golden/obligation/*.json` = 人工标注条款的 `is_obligation` 真值,**≥20 正 + ≥10 负**
    (负例含「本办法自…起施行」/释义句/纯定义句;取 batch01 内规子集 + 外规 ext_sse/ext_xxpl 取样条款);
    `test_obligation_golden.py` 对每条喂 `match_obligation` 比对真值,断言 **precision ≥ threshold 且 recall ≥ threshold**
    (config,默认 0.90);失败时打印误判条款便于迭代词表
  - 决策点:golden **直接喂 `match_obligation` 纯函数**(免栈/免 PG/免模型,纯正则评测);标注口径=条款是否含课以义务的规范句
  - Verify:`pytest tests/test_obligation_golden.py -q`(免栈免模型)
  - Files:`fixtures/golden/obligation/obligation_truth.json`、`tests/test_obligation_golden.py`、可选 `tools/build_fixtures.py`(--gen 初稿)

## M3-C · report 全量打磨(义务覆盖依赖 A1;其余可与 A 并行)

- [x] **C1 · report 数据扩展四项**
  - Acceptance:`build_report` 加 ① 义务覆盖(`clause_tags` is_obligation 命中块数 / 非 parent 块占比)② 队列处置
    (`review_queue` 按 `queue_type × status` 计数)③ 版本链(`DocVersion.version_status` effective/superseded 计数)
    ④ 按语料(P-INT/P-EXT 拆解析/QC/锚点核心率);**纯 PG 聚合,不加载模型**(M2 纪律)
  - Verify:`pytest tests/test_report.py`(扩展:义务覆盖率数学、队列/版本计数、按语料拆;seed 含义务 tag 的件 + 无 tag 件)
  - Files:`src/pipeline/verify/report.py`、`tests/test_report.py`

- [x] **C2 · JSON 快照落文件 + CLI 展示**
  - Acceptance:`demo report <batch>` 把快照 JSON 落 `reports/<batch>.json`(现有落库 `import_batches.report` 不变);
    CLI 控制台输出展示义务覆盖 + 队列/版本/语料四项
  - Verify:`pytest tests/test_report.py`/`test_cli.py`(断言 `reports/<batch>.json` 写出且含五项);手动 `demo report` 目检
  - Files:`src/pipeline/cli.py`、`src/pipeline/verify/report.py`、`tests/test_report.py`

## M3-D · 端到端验收

- [x] **D1 · 演示走查 + V8 + V1–V7 回归**
  - Acceptance:干净栈 + 本地 BGE-M3 跑 ingest(e1_enabled)→ E1 随管线打标;reprocess 件重打且幂等;`demo report` 出
    全五项 + `reports/<batch>.json`;**V8**(golden P/R ≥0.90)达成;V1–V7 回归全过;演示脚本补 E1 + report 展示步、据实跑微调措辞
  - Verify:`[需 demo up + 模型]` 手动走查 + 全套 `pytest` / `ruff check .` 全绿;`alembic check` 无漂移(无新迁移)
  - Files:`docs/`(演示脚本 / devlog)

- [x] **✅ 检查点 M3(硬门)达成**:V8(golden P=1.0/R=0.955 ≥0.90)· 全套 **263 passed**(含 11 model-gated,
  本地 BGE-M3)· V1–V8 全过 · E1 随管线自动打标 + reprocess 幂等 + `e1_enabled` gate + 异常不阻断 · 真 CLI 走查
  (`demo report` 义务覆盖 42.9%/版本链/按语料 + JSON 落文件 + `search` 四级引用)· `ruff check .` 全绿 ·
  `alembic check` 无漂移(**无新迁移**)· 默认零 LLM、状态机/IR/Milvus schema/chunk_id 均未动。

## 依赖图

```
M3-0 ─┬─ A1(e1 模块:matcher+tag/clear)─┬─ A2(_structuring 装配)──┐
      │                                  ├─ B1(golden P/R,需 A1.matcher)│
      │                                  └─ C1(report 义务覆盖需 A1)─ C2(JSON+CLI)
      └─(C1 队列/版本/语料部分可与 A 并行预备)
A2 + B1 + C1 + C2 ─ D1 ─ 检查点 M3
```

## 任务级决策(实现时定,已在对应任务标注)

1. **A1**:`match_obligation(text, cfg) -> (bool, evidence)` 纯函数;chunk 文本取 `chunk.text`;evidence 多词取首/拼接 ≤256。
2. **A2**:`clear`-先于-s3 避 FK;E1 异常不阻断 `_structuring` 终态(同验证组件纪律)。
3. **B1**:golden 直接喂 `match_obligation` 纯函数评测(免栈),≥20 正 + ≥10 负、负例必含。
4. **C1**:report 纯 PG 聚合,**不加载模型**(M2 纪律,避免无模型卡住)。

---

*下一步:人工评审本任务分解 → 通过后逐任务实现(`incremental-implementation` + `test-driven-development`),
从 M3-0 起,每任务实现→验证→停下等审。*
