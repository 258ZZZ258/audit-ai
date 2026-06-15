# 任务分解:M2(验证套件 + golden set)

> 依据 `SPEC_M2.md` + `PLAN_M2.md`(均评审通过)。Phase 3(spec-driven)产物,**待人工评审**——通过后逐任务实现。
> 每任务:单次专注会话可完成、≤5 文件、带验收 + 验证步骤;按依赖排序。集成测试连真栈,模型门控按需 skip。

## M2-0 · config(先行)

- [x] **M2-0 验证组件 ⚠ 配置** ✅
  - Acceptance:`settings.toml` 新增 `[verify]` 段 + `config.py` `VerifyConfig`,暴露 `t2_synthetic_query_head_chars=30`、`t2_hit_at=50`、`t4_page_window=1`、`t4_fuzzy_threshold=92`;`Settings.verify` 可读
  - Verify:`pytest tests/test_config.py` ✅
  - Files:`config/settings.toml`、`src/pipeline/config.py`、`tests/test_config.py`

## M2-A · 四验证组件(M2-0 后,彼此并行)

- [x] **A1 · T2 冒烟 `verify/smoke.py`**
  - Acceptance:`run_smoke(ctx, dvids) -> SmokeResult(passed, per_doc[{dvid,hit,rank,has_status_filter,error_code}], pass_rate)`;合成查询 = 标题 + 首条款前 `head_chars` 字 → `search(topk=hit_at)`;断言 dvid 命中(hit@N)+ status=effective 过滤位在(失败 E801/E802);**不阻断终态**
  - 决策点:status 过滤位断言 = `MilvusIO.search` 在 `SearchResult` 回带所用 `expr`,smoke 校验含 `status == "effective"`(顺带证明 staging/superseded 被滤)
  - Verify:`tests/test_smoke.py`(模型门控:编码合成查询;seed 或复用已索引件,断言命中 + 过滤位 + E802 负例)
  - Files:`src/pipeline/verify/smoke.py`、`src/pipeline/index/milvus_io.py`(SearchResult 加 expr)、`tests/test_smoke.py`

- [x] **A2 · T4 锚点回放 `verify/anchor_replay.py`**
  - Acceptance:`run_replay(ctx, dvids) -> ReplayResult(passed, fails[], exempt[], pass_rate)`;逐非 parent chunk:窗 `[page_start-1 .. page_end+1]` 取页文本(docx 用 `rendition.page_texts(rendition)`,pdf 用 raw)→ 剥面包屑得 body → 归一精确子串,未中走 rapidfuzz `partial_ratio≥t4_fuzzy_threshold`;**is_table / degraded 豁免**(计入 exempt 不计 fail);demo 集 pass_rate=100%
  - Verify:`tests/test_anchor_replay.py`(**免模型**,连栈/读 object store;断言 demo 件 100% + 表格块入 exempt + 一条人造错位 chunk 被判 fail)
  - Files:`src/pipeline/verify/anchor_replay.py`、`tests/test_anchor_replay.py`

- [x] **A3 · 对账 `verify/reconcile.py`**
  - Acceptance:`run_reconcile(ctx, dvids) -> ReconcileResult(per_doc[{dvid,pg_count,milvus_count,reconciled}])`;逐 doc 比 PG 非 parent chunk 数 vs **`MilvusIO.count(dvid)`**(非 num_entities);不平 → E701 + `corpus_rows.rows_from_cold` 重灌(按各 chunk 存储 status)+ flush + 复检
  - Verify:`tests/test_reconcile.py`(**免模型**:seed 已索引件 → `milvus.delete` 删部分 → reconcile 检出不平 + 重灌 + 复检平)
  - Files:`src/pipeline/verify/reconcile.py`、`tests/test_reconcile.py`

- [x] **A4 · rebuild `verify/rebuild.py`**
  - Acceptance:`run_rebuild(ctx) -> RebuildResult(before, after)`;`create_collection(drop_existing=True)` → 遍历所有有 chunk 的 doc_version,`rows_from_cold(db, dvid, <该件 chunk_status>)` 重灌(**零编码**,纯 insert)+ flush;断言总 count 恢复 + 固定 query top10(chunk_id 序)一致
  - 决策点:`rows_from_cold` 加「按各 chunk 存储 status」模式(effective/superseded 混存正确还原)
  - Verify:`tests/test_rebuild.py`(**免模型**,合成 query 向量比对 rebuild 前后 top10)
  - Files:`src/pipeline/verify/rebuild.py`、`src/pipeline/index/corpus_rows.py`(按存储 status 重灌)、`tests/test_rebuild.py`

## M2-B · mini golden set(与 M2-A 并行,独立)

- [ ] **B1 · golden set fixtures + F1 测试**
  - Acceptance:`fixtures/golden/<doc>.json` ×5–8(batch01 内规 docx 子集 + `第X条之一` + 无章通知/虚拟根),ground truth = `build_tree` 输出 JSON 镜像(节点类型/编号/层级),**人工校订**;`test_golden_set.py` 对每件 parse(light docx→IR blocks)→ `build_tree` → 与 ground truth 比对,断言条款树结构 **F1 = 1.0**
  - Verify:`pytest tests/test_golden_set.py -q`(**免模型/免 soffice**:build_tree 只用 IR blocks 文本)
  - Files:`tools/build_fixtures.py`(可加 `--gen-golden` 导初稿)、`fixtures/golden/*.json`、`tests/test_golden_set.py`

## M2-C · 装配(M2-A 后)

- [ ] **C1 · report 加 t2/t4_pass_rate**
  - Acceptance:`build_report` 增 `t2_pass_rate`/`t4_pass_rate` 键(M1 决策1 预留);T4 现场跑 replay(免模型)得率,T2 跑 smoke 得率(无模型则 `t2_pass_rate=None` 优雅缺省,与 retrieval_mode 同范式)
  - 决策点:t2/t4 来源 = report 现场计算(本任务采此,简单且与 build_report 纯计算一致);若日后 finalize 存档可改读
  - Verify:`tests/test_report.py`(断言新键存在;有/无模型分别验 t2 率/None)
  - Files:`src/pipeline/verify/report.py`、`tests/test_report.py`

- [ ] **C2 · finalize 自动触发 T2/T4**
  - Acceptance:文档到 INDEXED 后 `finalize.run` 顺带跑 T2+T4(复用 D1 已有触发点),结果记日志/报告;**异常吞掉不阻断终态**(评测组件无阻断权)
  - Verify:`tests/test_atomic_switch.py` 或新测(模型门控:INDEXED 件 finalize 产出 T2/T4 结果且不改 pipeline_status)
  - Files:`src/pipeline/stages/finalize.py`、对应测试

- [ ] **C3 · CLI 替换 D5 占位为真实现**
  - Acceptance:`demo verify smoke|replay|reconcile`、`demo rebuild` 调真实组件、打印报告;退出码非零**当且仅当**有真实失败(E801/E802/E701/不平/top10 不一致);移除对应 `_not_m1` 占位
  - Verify:`tests/test_cli.py`(更新 D5 占位测试为真实退出码语义;`demo verify replay` 免模型可跑)
  - Files:`src/pipeline/cli.py`、`tests/test_cli.py`

## M2-D · 端到端验收

- [ ] **D1 · 演示脚本走查 + V1–V7 验收**
  - Acceptance:重跑演示脚本 1–10 步(真栈 + 本地 BGE-M3),据本会话实跑微调脚本措辞;**V3**(replay 100%)、**V6**(rebuild top10 一致)、**V7**(smoke 100% 含过滤位)+ report 显 T2/T4=100%;V1/V2/V4/V5 仍过
  - Verify:`[需 demo up + 模型]` 手动走查 + 全套 `pytest`/`ruff check .` 全绿
  - Files:`docs/`(演示脚本/devlog)、必要时 `tests/test_version_demo.py` 延伸

- [ ] **✅ 检查点 M2(硬门)**:V1–V7 全过;演示脚本 1–10 步端到端;mini golden set F1=1.0;`pytest` + `ruff check .` 全绿;迁移无漂移(M2 预期**无新迁移**——纯验证组件,不动 schema)。

## 依赖图

```
M2-0 ─┬─ A1 ─┬─ C1(report)
      ├─ A2 ─┤
      ├─ A3  ├─ C2(finalize 触发,需 A1/A2)
      ├─ A4 ─┘
      └─ A1–A4 ─ C3(CLI,需四组件)
M2-0/独立 ─ B1(golden)
A1–A4 + B1 + C1–C3 ─ D1 ─ 检查点 M2
```

## 任务级决策(实现时定,已在对应任务标注)
1. **A1** status 过滤位断言:`SearchResult` 回带 `expr`,smoke 校验含 `status == "effective"`。
2. **A4 / corpus_rows**:`rows_from_cold` 加「按各 chunk 存储 status 还原」模式(rebuild 混存 effective/superseded)。
3. **C1** t2/t4 来源:report 现场跑 smoke+replay(无模型时 t2 优雅缺省 None)。

---

*下一步:人工评审本任务分解 → 通过后逐任务实现(`incremental-implementation` + `test-driven-development`),
从 M2-0 起,每任务实现→验证→停下等审。*
