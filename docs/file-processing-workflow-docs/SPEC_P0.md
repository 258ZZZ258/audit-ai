# SPEC: 文档处理管线 v1.6 — P0 缺口落地

> SDD 阶段 1(Specify)。依据 `docs/文档处理与语料库构建_技术框架设计_v1.6.md`(生产 v1.6 保真)+ 本目录 `GAP.md` §Z / `RTM.md` P0 缺口清单。
> 协作流程:本 SPEC 经人工批准 → `planning-and-task-breakdown`(PLAN/TASKS)→ `incremental-implementation`+`test-driven-development` 逐任务落地 → 交 Codex 复审。**本阶段只写规格,不写代码。**
> 产物落 `docs/file-processing-workflow-docs/`(不覆盖 M1-era `SPEC.md`)。

## 0. 决策记录(已与用户确认)

| # | 决策点 | 选定 |
|---|---|---|
| D1 | SPEC 范围 | **全部 P0**:A 生产解析栈 + B LLM P0 四项 + C ref_resolver |
| D2 | LLM 触点交付形态 | **接真模型 + 真实 key**(非 stub-only):实现真链路,env 提供 key,集成测试有 key 时真跑、无 key 时 skip(对齐 BGE-M3 模型门控,绝不在 CI 无凭据时联网) |
| D3 | dict_violation_types 来源 | **样例聚类 v0-draft 种子** + 建表 + seed;代码 consumed-when-present 不阻塞;待张老师评审(§16-6) |
| D4 | 业务域来源现实(Q5 定调) | 原始文档库多**不带业务域**;20k 外规/10k 案例 manifest 该列**无法人工逐条填** → **LLM 为业务域事实主来源**(manifest 有则优先)。故 LLM 值**写权威 doc 级字段 + 标来源**,确认**按 profile 分档**(非统一"候选挂队列等人工逐件") |

---

## 1. Objective

把 RTM 标 ❌/🟡 的 **P0 三工作流**推进到生产保真可用,各自带测试证明:

- **A 生产解析栈**:消除"仅 docx/pdf-text"限制。**本地可落地子集**(xlsx 直读 / IR `ocr_conf` add-only / 表格 markdown 序列化 / 白名单+路由扩展)直接实现并 TDD;**外部依赖子集**(DeepDoc/PaddleOCR/MinerU 真后端)实现 `ParserAdapter` 真实现 + 路由,集成测试门控在库/GPU/信创可用时跑、否则 skip——接缝已在位(`PIPELINE_PARSER_BACKEND`),本轮把 stub 替换为可门控真后端。
- **B LLM P0 四项**:复用 `enrich/e2_tag.py` 已验证的"prompt + 字典约束 + server-side 校验 + 注入式 client + 幂等 clear + 非阻断"纪律,落地:
  - **B1 (L-1)** 案例引用外规条款抽取 + 归一对齐(全管线最高价值字段)
  - **B2 (L-2)** 案例违规事由分类(+ dict_violation_types v0-draft)
  - **B3 (L-3)** L2 业务域多值打标(字典约束 + AI 标识 + META_REVIEW 人工确认)
  - **B4 (L-4)** E2 条款级打标接真模型(字典 PG 加载 + 真模型集成测试 + 启用路径打通)
- **C ref_resolver**:`clause_references` 空表填充——S3 后纯规则四类指代解析(R1–R3 文档内确定性 + R4 跨文档 dict_aliases/pending_target)+ standoff + 窗口渲染原语。

**成功 = RTM 对应行从 ❌/🟡 翻 ✅ 并挂通过测试**(详见 §12)。

## 2. Tech Stack

- Python 3.11(`.venv`,brew python@3.11);`setuptools<81` 已钉。
- 既有:SQLAlchemy + Alembic(PG add-only)、pymilvus 2.4、pydantic(IR)、httpx(LLM client)、pytest + ruff。
- 新增依赖(走 "Ask first"):`openpyxl`(xlsx 直读,A1)——轻量纯 Python,无外部服务。DeepDoc/PaddleOCR/MinerU **不入默认依赖**(extra / 部署期装,A4 门控)。
- LLM:`pipeline/llm_client.py`(OpenAI 兼容,env `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL`,默认 `gpt-5.4-nano`)。**绝不入库**。

## 3. Commands

```
.venv/bin/python -m pytest -q                          # 全量(testpaths 含 pipeline/libs/common/eval/query)
.venv/bin/python -m pytest pipeline/tests/test_<x>.py -q # 单文件(修复迭代只跑波及范围)
.venv/bin/ruff check . && .venv/bin/ruff format         # lint(E/F/I/UP/B,行宽 100)
alembic revision --autogenerate -m "<msg>" && alembic upgrade head && alembic check  # 迁移 add-only 无漂移
.venv/bin/ruff check --fix alembic/versions && .venv/bin/ruff format alembic/versions # 迁移纳入 lint
demo down -v && demo up                                 # 干净栈(模型门控套件假定 SHA 去重干净栈)
# LLM 集成测试(B,有 key 才真跑):
OPENAI_API_KEY=<key> OPENAI_BASE_URL=<url> OPENAI_MODEL=<m> .venv/bin/python -m pytest pipeline/tests/test_case_l2.py -q
# 生产解析后端(A4,装库后):
PIPELINE_PARSER_BACKEND=deepdoc demo ingest <dir> --manifest <xlsx>
```

## 4. Project Structure(新增/改动)

```
pipeline/pipeline/
  parsing/
    light_parser.py            # 改:xlsx 分支(openpyxl)+ 表格 markdown 序列化
    deepdoc_parser.py          # 新:DeepDoc 真后端(A4,门控 import)
    paddleocr_parser.py        # 新:PaddleOCR OCR 通道(A4,门控)
    mineru_parser.py           # 新:MinerU 兜底(A4,门控)
    factory.py                 # 改:stub → 真后端 + 路由(格式→后端)
  meta/
    case_l2.py                 # 新:案例 L2 LLM(B1 引用外规 + B2 违规事由),镜像 e2 纪律
    case_ref_align.py          # 新:引用外规"《X》第N条"→ doc_no+clause_path_norm 对齐(纯逻辑)
    l2_llm.py                  # 新:L2 业务域多值打标(B3),字典约束 + AI 标识
  chunking/
    ref_resolver.py            # 新:四类指代规则解析(C),写 clause_references
    ref_render.py              # 新:窗口渲染原语(倒序插注释,UNRESOLVED 不渲染)
  enrich/
    e2_tag.py                  # 改:dict PG 加载已在;打通启用路径 + 真模型集成测试(B4)
libs/common/common/
  ir.py                        # 改:Block +ocr_conf(add-only);Table markdown 辅助
  pg_models.py                 # 改:+dict_violation_types +dict_aliases(add-only)
alembic/versions/
  0009_dict_violation_aliases.py   # 新:两字典表
  0010_ir_ocr_conf.py              # (若 IR 落 PG 镜像)—— 评估后定
seeds/
  dict_violation_types.csv     # 新:v0-draft 种子(样例聚类)
  dict_aliases.csv             # 新:制度简称别名种子(人工维护起点)
config/
  settings.toml                # 改:[toggles] +l2_enabled +case_l2_enabled;说明默认关
pipeline/tests/                # 新:test_case_l2 / test_case_ref_align / test_l2_llm /
                               #     test_ref_resolver / test_xlsx_parse / test_ir_ocr_conf …
```

## 5. Code Style(镜像 e2_tag.py 既有纪律)

LLM 触点一律遵循该模式(B 全部):纯函数可单测、client 注入、server-side 字典裁剪、不臆测、非阻断。

```python
def tag_chunk(client, text: str, dicts: Dicts) -> dict[str, list[str]]:
    """调 LLM → 服务端裁字典(绝不信任模型自守约束);返回受约束结果。"""
    system, user = build_prompt(text, list(dicts.allowed))
    raw = client.chat_json(system, user)          # client 注入 → 测试用 fake,免真调用
    if not isinstance(raw, dict):
        raw = {}
    return {k: _enforce(raw.get(k), set(dicts.allowed[k])) for k in dicts.keys}

def _enforce(returned, allowed: set[str]) -> list[str]:
    """只保留落在 allowed 内的字符串(去重、保序)——never trust the LLM。"""
    return [v for i, v in enumerate(returned or []) if isinstance(v, str) and v in allowed
            and v not in (returned or [])[:i]]
```

约定:CJK 注释独立行/缩短防超行宽 100;`known-first-party=[common,pipeline,eval,query]`;测试文件基名全仓唯一。

## 6. Testing Strategy

- **TDD**:每项先写失败测试再实现(`test-driven-development`)。
- **三类测试**(对齐 CLAUDE.md 分工):
  1. **纯逻辑单测**(Claude + CI 都可跑,无栈无模型):IR `ocr_conf`、xlsx 解析、表格 markdown、`case_ref_align` 对齐、`_enforce` 字典裁剪、`ref_resolver` R1–R4 模式、prompt 构造、fake-LLM 驱动的 `tag_chunk`/`case_l2`。
  2. **栈集成测**(连真 PG/Milvus,栈未起 skip):写 clause_references / cases L2 字段 / clause_tags、幂等重打、非阻断(LLMError 不改 pipeline_status)。
  3. **模型门控集成测**(D2:有 `OPENAI_API_KEY` 真跑、无则 skip,**绝不无凭据联网**;A4 后端有库/GPU 才跑):真模型 JSON 输出形态 + server-side 裁剪后落库正确。
- **Golden**:案例引用对齐 + ref_resolver R1–R4 各扩 golden 标注(对齐 §6.7 "golden set 50 件扩展指代解析标注");违规事由 consumed-when-present 不破现 374 全绿。
- **提交前**:全仓门控全量跑一次(无模型/无库项 skip,漏回归)。

---

## 7. 工作流 A — 生产解析栈(§4)

### A1 xlsx 直读(本地,无外部依赖)
- `light_parser` 加 xlsx 分支:openpyxl 读 → 每 sheet → `Table` block(cells row/col)→ IR。
- **SC-A1**:`PIPELINE_PARSER_BACKEND=light` 下 xlsx 入库产 `chunk_type=table` 块;白名单含 xlsx;`test_xlsx_parse` 绿。RTM **S1-4 ❌→✅**。

### A2 IR add-only:ocr_conf + 表格 markdown(本地)
- `Block` 加 `ocr_conf: float | None = None`(add-only,`extra="forbid"` 下安全);light/非 OCR 置 None,OCR 后端回填。
- `Table` 加 markdown 序列化辅助(`cells_md` 派生:合并单元格按 rowspan/colspan 展开补值——cells 已含 span 信息);切块表格块用它替代当前简单行列化(GAP S1-8 / S3-6 增强)。
- QC 指标 6 接 `ocr_conf`(均值校验,OCR 文档才参与;非 OCR None 不计)→ **S2-6 🟡→✅**。
- **SC-A2**:`test_ir_ocr_conf`(字段 add-only + 校验)、`test_table_markdown`(合并单元格展开)绿;`test_v16_fidelity`/`test_ir` 更新通过;指标 6 在有 ocr_conf 时生效。RTM **S1-7 / S1-8 / S2-6**。

### A3 格式白名单 + 路由扩展(本地骨架)
- `WHITELIST_FORMATS` 扩 `{docx, pdf, xlsx, jpg, png}`;magic number 探测加 jpg/png/xlsx。
- factory 路由:format → backend(docx/pdf-text→deepdoc 或 light;pdf-notext/jpg/png→paddleocr;失败→mineru)。**默认仍 light**;jpg/png 在无 OCR 后端时落 E202 隔离(不静默丢)。
- **SC-A3**:`test_s0_register` 扩格式用例绿;路由表单测(format→backend)绿;jpg/png 无 OCR 后端时 QUARANTINED 而非崩溃。RTM **S0-8 🟡→✅ / O-5**。

### A4 DeepDoc / PaddleOCR / MinerU 真后端(外部依赖,门控)
- 把三个 `_StubParser` 换成真实现:各自门控 import(库缺 → 抛清晰 `RuntimeError` 引导装 extra),`parse()` 产 IR(bbox/page/ocr_conf 真填)。
- DeepDoc 后 mini golden set 仍 **F1=1.0**(parser-swap 准入门,§5.4);OCR 回填 ocr_conf 供指标 6/§18.2④。
- 超时分支:扫描件 15min(§4.3)。
- **SC-A4**(门控,验收随部署):`PIPELINE_PARSER_BACKEND=deepdoc` 集成测在库可用时跑、否则 skip;golden F1=1.0 不回归。RTM **S1-1/S1-2/S1-3** 标 🟡(真后端就位但 CI 默认 skip,生产验收)。
- **边界**:DeepDoc/PaddleOCR/MinerU/GPU/信创可部署性是外部前置(§16-1、CP-005);A4 交付"可门控真后端 + 路由",真验收在甲方环境。

---

## 8. 工作流 B — LLM P0 四项(§7.1 / §9 / §19.2)

> 全部镜像 §5 e2 纪律。client 注入 → fake 单测 + 真模型门控集成测(D2)。富集/L2 失败非阻断(不改 pipeline_status)。

### B1 (L-1) 案例引用外规条款抽取 + 归一对齐 — 最高价值
- `case_l2.extract_cited(client, case_text, …)`:LLM 抽 `[{法规标题, 文号?, 条号?}]`(prompt 强制只输出 JSON;不臆测)。
- `case_ref_align.align(cited, pg)`(纯逻辑,无 LLM):三级匹配 文号精确 → 标题精确 → (别名表留 C)→ `clause_path_norm`(复用 `normalize`)→ 命中写 `cases.cited_regulations=[{doc_no, clause_path_norm, …}]`;任一未命中 → `cases.ref_unresolved=true`(低优人工队列,**不阻塞案例入库**)。
- **SC-B1**:`test_case_ref_align`(文号/标题/条号对齐 + 超界→unresolved,纯逻辑无模型)绿;`test_case_l2`(fake-LLM 抽取形态)绿;真模型门控集成测有 key 时验真输出。RTM **S4-12 ❌→✅**。

### B2 (L-2) 案例违规事由分类 + dict_violation_types v0-draft
- 迁移 `0009` 建 `dict_violation_types(code PK, name, dict_version, …)`;`seeds/dict_violation_types.csv` v0-draft(样例聚类,标 `dict_version=v0-draft-2026-06`)。
- `case_l2.classify_violation(client, case_text, allowed)`:LLM 约束在字典名单 + server-side `_enforce` → `cases.violation_category`(单值或主类)。字典空/未命中 → 留 None(**consumed-when-present**,不阻塞)。
- **SC-B2**:`test_case_l2` 违规事由(fake-LLM + _enforce 裁剪 + 空降级)绿;迁移 `alembic check` 无漂移;`dict_violation_types` seed 加载。RTM **S4-11 ❌→✅(consumed-when-present)/ DM-3 ❌→✅**。

### B3 (L-3) L2 业务域多值打标 —— LLM 为事实主来源(D4)
- **来源现实(D4)**:原始文档库多不带业务域;20k 外规 / 10k 案例 manifest 该列无法人工逐条填 → **LLM 是业务域主来源**(manifest 有则优先用,无则 LLM 出)。**不是"候选等人工逐一确认"**——那只在内规 1k(P-INT 逐件,§13.1 ≈5 人日,可行)成立。
- `l2_llm.tag_biz_domain(client, doc_text, allowed_biz)`:LLM 约束 `dict_biz_domains` + server-side `_enforce` → 业务域多值。
- **落库(Q5 定)**:写**权威 doc 级字段**——`doc_versions` add-only 新列 `biz_domains` JSONB(多值;原单值 `biz_domain` 保留不删)+ `biz_domain_source ∈ {manifest, llm, confirmed}` + 记 `dict_version`。下游 chunks/Milvus 的 `biz_domain` ARRAY 从此取。
- **确认分档(复用既有 A/B auto_confirm + profile `sampling_rate`)**:**P-INT 逐件**入 META_REVIEW 确认(`source` 转 `confirmed`);**P-EXT/P-QA/P-CASE LLM 直落不逐件挡**(`source=llm` 即生效),按 `sampling_rate` 抽样核验(命中率/不合格率纳看板,§15)。带 `ai_label`(§14)。manifest 已给业务域 → 优先;LLM 仅在缺失补全,冲突进 META_REVIEW(§7.1 交叉校验口径)。
- `l2_enabled` 默认关(启用即真模型,D2)。
- **SC-B3**:`test_l2_llm`(fake-LLM + 字典裁剪 + `biz_domain_source` 标志)绿;集成测三档行为(P-INT 进 META_REVIEW;P-EXT LLM 直落 + 抽样;manifest 优先/冲突路径)+ 下游 Milvus `biz_domain` 从 `biz_domains` 取。RTM **S4-2 ❌→✅(业务域;摘要/适用对象留 P1 钩子)**。

### B4 (L-4) E2 接真模型打通
- `e2_tag.py` 接缝已完整(prompt/dict 加载/`_enforce`/幂等/非阻断);本项:`e2_enabled=true` 路径端到端打通 + dict PG 加载在真 seed 上验证 + **真模型门控集成测**(D2)。
- **SC-B4**:`test_e2_tag` 现单测保持;新增真模型门控集成测(有 key:真 LLM → server-side 裁剪 → `clause_tags` entity_type/department/matter 行正确;无 key skip)。RTM **E2-1 🟡→✅**。

### §14 AI 标识(B 横切最小项)
- L2/案例 L2 产物在 META_REVIEW 工作台带 `ai_label`,人工确认后转"已人工确认";敏感词过滤留 P2(SEC-4,本轮不做,**Open Question**)。

---

## 9. 工作流 C — ref_resolver(§6.7)

### C1 R1–R3 文档内确定性解析(纯规则)
- `ref_resolver.resolve(chunks, clause_tree, doc_meta)`:四类模式最长匹配优先(复合"本办法第十五条第二款"整体匹配):
  - R1 文档自指(本办法/本条/本章)→ doc_meta / 当前树节点
  - R2 相对条款(前条/前款/前两款)→ 条款树位置运算(首款命中→UNRESOLVED 计数)
  - R3 绝对条款(第X条第X款 / 区间)→ 复用 `normalize` 查 `clause_path_norm`(附件作用域规则)
- standoff:`chunks.text` 不改;结果写 `clause_references`(span/surface_text/ref_type/target/resolution_status/`method="rule"`)。
- **SC-C1**:`test_ref_resolver` R1/R2/R3 模式 + UNRESOLVED 计数(纯逻辑)绿;S3 后 `clause_references` 有 resolved 行。RTM **S3-15 ❌→✅(R1–R3)/ DM-2 🟡→✅**。

### C2 R4 跨文档 + dict_aliases + pending_target
- 迁移 `0009` 建 `dict_aliases(alias, canonical_doc, dict_version, …)`;seed 起点。
- R4`《…》(〔YYYY〕N号)?(第X条)?`:文号精确 → 标题精确 → dict_aliases;均未命中 → `resolution_status="pending_target"`;夜间任务全量重试(随 W2 外规入库收敛);永久未解析导出语料缺口清单(复用 §21.5 T5)。
- **SC-C2**:`test_ref_resolver` R4 三级匹配 + pending_target 绿;`dict_aliases` 建表 seed。RTM **DM-4 ❌→✅**。

### C3 窗口渲染原语
- `ref_render.render(window_text, refs)`:按 span **倒序**插注释(防偏移);gloss≤30 字;UNRESOLVED/ambiguous **不渲染**(宁缺勿错)。供 S6 / 比对交叉验证 / 查询条款跳转复用(本轮只交付原语 + 单测,不接 S6)。
- **SC-C3**:`test_ref_render`(倒序不偏移 + UNRESOLVED 不渲染)绿。

---

## 10. 数据模型改动(全部 add-only)

| 改动 | 表/字段 | 迁移 | 备注 |
|---|---|---|---|
| dict_violation_types | code/name/dict_version | 0009 | B2;v0-draft seed |
| dict_aliases | **alias(PK)**/canonical_doc_number/canonical_title/dict_version | 0009 | C2;别名种子。alias 自然键(同 dict_* 族 + 幂等 seed 必需);canonical 拆文号/标题服务 R4 三级匹配 |
| doc_versions.biz_domains + biz_domain_source | JSONB 多值 + String | 0009/0010 | B3/D4;原单值 `biz_domain` 保留不删;LLM 业务域写此 |
| IR Block.ocr_conf | `float \| None` | (IR 契约,非 PG)| A2;add-only,`test_v16_fidelity` 更新 |
| cases.cited_regulations / violation_category / ref_unresolved | 已存在 | — | B1/B2 填充(无 schema 改) |
| clause_references | 已存在(0008)| — | C 填充(无 schema 改)|

`alembic check` 必须无漂移;`alembic/versions` 纳入 lint。**绝不改名/删列**。

## 11. Boundaries

- **Always**:每项先写失败测试(TDD);LLM 触点 server-side 字典裁剪 + 不臆测 + 非阻断 + 默认关;迁移 add-only + autogenerate→upgrade→`alembic check`;LLM key 仅 env、绝不入库;CJK 注释独立行防超行宽;修复迭代只跑波及范围,合并前全量门控跑一次。
- **Ask first**:加依赖(openpyxl / DeepDoc extra);改 settings.toml 默认开关值;`cases.violation_category` 单值 vs 多值取舍;P-EXT/QA/CASE 业务域 LLM 直落的抽样核验率(profile `sampling_rate` 取值);任何触达硬契约(chunk_id/manifest/Milvus schema)的改动。
- **Never**:把 LLM 解析结果写进 `clause_references.method`(字段恒 `rule`,禁混入不可区分的 LLM 结果,§6.7);删失败测试换绿;默认路径触发任何 LLM 调用;OCR/DeepDoc 真后端设为默认 backend(保持 light 默认)。

## 12. Success Criteria(汇总,可测)

RTM 行翻 ✅ 并挂测试:
- A:**S1-4**(xlsx)✅ · **S2-6**(ocr_conf)✅ · **S1-7/S1-8**(IR/表格 markdown)✅ · **S0-8/O-5**(白名单)✅ · **S1-1/2/3**(真后端门控,记 🟡 生产验收)。
- B:**S4-12**(引用外规)✅ · **S4-11/DM-3**(违规事由+字典,consumed-when-present)✅ · **S4-2**(L2 业务域)✅ · **E2-1**(E2 真模型)✅。
- C:**S3-15/DM-2**(ref_resolver R1–R3 + clause_references)✅ · **DM-4**(dict_aliases)✅。
- 全仓回归:现 **374 passed** 不破;新增测试全绿;`ruff check` 净;`alembic check` 无漂移。
- LLM 集成测:有 `OPENAI_API_KEY` 时真模型跑通(D2),无 key/无栈/无 GPU 时 skip(不联网、不误判绿)。

## 13. Open Questions(需人工/甲方输入)

| # | 问题 | 阻塞项 | §16 |
|---|---|---|---|
| Q1 | 网关轻量模型与配额(L2/E2/案例 L2 用哪个模型、调用量预算)| B 真模型口径 | CP-005-①③ |
| Q2 | dict_violation_types / dict_biz_domains 初版评审 | B2/B3 字典约束空间 | §16-6 |
| Q3 | dict_entity_types 评审(E2 实体类型)| B4 | §16-7 |
| Q4 | 案例自然人姓名脱敏(影响 cases 存储)| B1/B2 落库 | §16-4 |
| ~~Q5~~ | ~~L2 业务域落库位置~~ → **已定(D4)**:写 `doc_versions.biz_domains` 权威字段 + `biz_domain_source` 标来源,按 profile 分档确认 | — | — |
| Q6 | DeepDoc/PaddleOCR/MinerU 在信创 + GPU 可部署性 | A4 验收 | §16-1 |
| Q7 | §14 敏感词进出过滤是否纳入本轮(当前划 P2 不做)| SEC-4 | — |

## 14. 明确不做(Out of Scope,本轮 P0)

- §18 逃逸闭环(quality_tickets / 指标 8·9 / 双解析器仲裁 / 高危 token)→ P1。
- 评测 T1/T3/T5/T6 → P1。
- 修订说明 LLM 对齐(L-8)、L2 摘要/适用对象(L-5)、案例对象类型/金额 L2(L-6/L-7)→ P1。
- §22 P-MISC 路由、§6.6 图谱窗口、E3 探针、§14 敏感词(SEC-4)→ P2/边界外。
- 表格/案例摘要 LLM 升级(L-10/L-11/L-12)→ P2(规则版已可用)。
