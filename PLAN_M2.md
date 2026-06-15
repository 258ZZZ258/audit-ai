# 实施计划:M2(验证套件 + golden set)

> 依据 `SPEC_M2.md`(已评审通过)。Phase 2(spec-driven)产物,**待人工评审**——通过后进 Phase 3(Tasks)。
> 目标:补齐 V3(T4)/ V6(rebuild)/ V7(T2),使 V1–V7 全过、演示脚本 1–10 步完整。DeepDoc 本轮不做。

## 方法与总体形状

M2 全部是**验证组件 + golden set**,落在 `src/pipeline/verify/` 与 `tests/`,**不改 stage、不动状态机、不动硬契约、
零新运行期依赖**(rapidfuzz 已在;复用 PgIO/MilvusIO/EmbeddingClient/ObjectStore/corpus_rows/rendition)。
组件间彼此独立,主要依赖既有基础设施,故大部分可并行;report / finalize / CLI 装配在组件之后。

**T4 口径已据实测定**(Plan 阶段探针,见下「实测结论」):窗口 `[page_start-1 .. page_end+1]`、复用
`rendition.page_texts`(同 page_align,剥页眉页脚)、精确未中走 rapidfuzz `partial_ratio ≥ 阈值(config ⚠)`、
**is_table 与 degraded 豁免** → demo 集 100%。

## 组件图与依赖

| 组件 | 文件 | 依赖 | 复用 |
|---|---|---|---|
| **config ⚠ 值** | `config/*.yaml/toml` + `config.py` | — | 加 T2(合成查询长度 30 / hit@50)、T4(fuzz 阈值、窗口 ±1)字段 |
| **T2 冒烟** | `verify/smoke.py` | config | `EmbeddingClient` + `MilvusIO.search`(断言 `status=effective` 过滤位在 + hit@50) |
| **T4 锚点回放** | `verify/anchor_replay.py` | config | `PgIO.get_chunks` + `rendition.page_texts` + `rapidfuzz`;is_table/degraded 豁免 |
| **reconcile** | `verify/reconcile.py` | — | `MilvusIO.count(dvid)`(逐 doc,**非** num_entities)+ `corpus_rows.rows_from_cold` 以 PG 重灌 |
| **rebuild** | `verify/rebuild.py` | — | `MilvusIO.create_collection(drop_existing=True)` + `corpus_rows.rows_from_cold`(零编码)+ flush |
| **report 扩展** | `verify/report.py` | T2/T4 | 加 `t2_pass_rate`/`t4_pass_rate` 键(M1 决策1 预留) |
| **finalize 自动触发** | `stages/finalize.py` | T2/T4 | INDEXED 后自动跑 T2+T4,结果入报告(**不阻断终态**) |
| **CLI 装配** | `cli.py` | 全部组件 | 替换 D5 占位(`verify smoke/replay/reconcile`、`rebuild` 真实现) |
| **mini golden set** | `fixtures/golden/*.json` + `tests/test_golden_set.py` | — | `build_tree`;ground truth = build_tree JSON 镜像 |

## 实施顺序(分阶段 + 并行)

- **M2-0 config + 复用审计**(先行,小):加 T2/T4 的 ⚠ 配置字段;确认 reconcile/rebuild 复用 `corpus_rows.rows_from_cold`、
  T4 复用 `rendition.page_texts`(无需新基础设施)。
- **M2-A 四验证组件**(M2-0 后,**彼此并行**):smoke / anchor_replay / reconcile / rebuild,各为纯/半纯函数返回报告 +
  各自集成测试(连真栈,模型门控按需)。
- **M2-B golden set**(与 M2-A **并行**,独立):选 batch01 内规 docx 子集 + 边界件(标准条 / `第X条之一` / 无章通知)
  5–8 件,生成 build_tree JSON 镜像 ground truth、人工校订,`test_golden_set.py` 断言 F1=1.0。
- **M2-C 装配**(M2-A 后):report 加 t2/t4 键 → finalize 自动触发 T2/T4 → CLI 替换 D5 占位。
- **M2-D 端到端验收**(全部后):重跑演示脚本 1–10 步(含步骤6 report T2/T4=100%、步骤10 rebuild top10 一致),
  据本会话实跑微调演示脚本措辞;V1–V7 全过。

```
M2-0 ──┬─ M2-A(smoke ∥ replay ∥ reconcile ∥ rebuild)──┬─ M2-C(report→finalize→CLI)── M2-D 验收
       └─ M2-B(golden set)────────────────────────────┘
```

## 验证检查点(阶段间)

1. **M2-0 后**:config 加载含新字段、ruff/pytest 既有套件仍绿。
2. **每个 M2-A 组件**:其集成测试通过(smoke 命中+过滤位 / replay 100% 含豁免 / reconcile 造不平→PG 重灌 /
   rebuild drop→回灌→count 与 top10 一致)。
3. **M2-B**:`test_golden_set.py` F1=1.0。
4. **M2-C**:finalize 自动产出 T2/T4 入 report;`demo verify *` 退出码语义正确(有失败→非零)。
5. **M2-D 硬门**:演示脚本 1–10 步端到端;V1–V7 全过;`pytest` + `ruff check .` 全绿。

## 风险与缓解(多数已由 Plan 实测消解)

- **R-T4 命中率(已消解)**:实测 `[ps-1..pe+1]` 窗 + rendition.page_texts + rapidfuzz≥阈值 + is_table/degraded 豁免
  → demo 集 100%。阈值/窗口 ⚠ 入 config。
- **R-reconcile 计数(已定)**:用逐 doc `MilvusIO.count(dvid)`(query-by-PK,准确),**不用**全集 num_entities(upsert
  churn 虚高)。造不平的测试:手动 `milvus.delete` 部分块 → reconcile 检出 E701 → 从冷备重灌 → 复检平。
- **R-rebuild 一致性**:top10 一致需确定性对比——固定一条 query,rebuild 前后各 search 取 top10 chunk_id 列表比对。
  rebuild 用纯 insert(非 upsert)→ 计数干净;冷备零编码保证向量 bit 一致 → 同序。
- **R-golden 标注量(中)**:用 `build_tree` 输出做初稿再人工校订,降低工作量;只 5–8 件、只内规 docx + 边界件。
- **R-finalize 触发面**:T2/T4 在 INDEXED 后自动跑——须确保不阻断(异常吞掉记报告)、且 reprocess/meta confirm 路径
  到 INDEXED 都触发(复用 D1 已有的 `_advance_one` finalize 钩子点)。

## config 新增(⚠ 值,M2-0)

| 值 | 用途 | 初值(合成启发式 ⚠) |
|---|---|---|
| `t2_synthetic_query_head_chars` | T2 合成查询「首条款前 N 字」 | 30(V0.1 §21.2) |
| `t2_hit_at` | T2 命中判定 hit@N | 50 |
| `t4_page_window` | T4 取页窗口(page_start/end 各 ±N) | 1 |
| `t4_fuzzy_threshold` | T4 精确未中的 rapidfuzz partial_ratio 阈值 | 92 |

## Plan 阶段实测结论(T4 探针,batch01 已索引件)

- 固定 ±1(从 page_start)窗:docx 多 100%,pdf 94–97%,int_quanxian 表格块 75%。
- 改 `[page_start-1 .. page_end+1]` 窗:**非表格块 602/620 精确(97.1%)**,18 条近似未中**全部** rapidfuzz
  `partial_ratio≥92` 可救回;唯一表格块精确/模糊均难中(rendition 表格重排)。
- 结论:窗口用 page_end + rapidfuzz 容差 + **is_table 豁免**(连同 degraded)→ 100%。与 M1 page_align 的 rapidfuzz
  兜底机制一致(复用同函数同阈值思路)。

---

*下一步:人工评审本计划 → 通过后进入 Phase 3(Tasks),按 M2-0/A/B/C/D 拆任务级验收。*
