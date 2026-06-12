# 规格说明：文档处理管线 · 本地 Demo（M1）

> *做什么*与*为什么*的权威来源：`文档处理管线_本地Demo_开发文档_v0.1.md`(V0.1 开发文档)。
> 架构与契约参考：`CLAUDE.md`。
> 本规格**仅覆盖 M1**(骨架 + 基于 light 解析器的 S0–S5)。M2(DeepDoc、完整验证套件)与 M3(E1 打标)在后续轮次单独出规格。
> 状态:**等待人工评审**——评审通过前不进入 Plan/Tasks/Implement。

---

## 目标(Objective)

构建文档处理管线的本地 M1 最小可运行骨架,在自构造的 fixture 语料上端到端证明四件事:

- **V1 — S0–S5 端到端**。`batch01` 中每个文档到达终态(`INDEXED` / `DEGRADED_INDEXED` / `REJECTED` / `QUARANTINED`),无悬挂状态。
- **V2 — 质检硬关卡 + 补录闭环**。坏样例被拦截并给出失败指标 + 定位证据 → CLI 修复 IR → 重入 QC → `INDEXED`;降级入库路径同样走通。
- **V4 — 版本替代原子切换**。`batch02_revision` 入库后,默认检索不命中旧版;`--include-superseded` 可见旧版且带 `superseded` 标注。
- **V5 — 幂等重跑**。同批次重复 ingest 两次:PG chunk 数不变、无重复 `chunk_id`、Milvus 实体数稳定。

**面向谁**:内部工程 + 对张翼飞的内部演示。**不**对甲方演示,**不**承诺任何质量指标(依 V0.1 §0.2 / §16)。成功标准 = 四个验收点通过演示脚本(第 1–9 步)与 `demo verify idempotency` 验证。

**M1 明确不含**(延后,非裁掉):DeepDoc adapter(M2)、T2 冒烟 / T4 锚点回放 / 对账 / rebuild(M2 → V3/V6/V7)、E1 义务打标(M3 → V8)、L2 LLM 元数据辅助(config 默认关)、表格块 LLM 摘要、OCR。IR 边界保证这些后续可平滑接入,不动 M1 代码。

## 技术栈(Tech Stack)

| 项 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11 | |
| CLI | typer | 单一 `demo` 入口 |
| ORM / 迁移 | SQLAlchemy 2.x + Alembic | **add-only** 迁移 |
| 关系库 | PostgreSQL 16(Docker) | 权威库 |
| 向量库 | Milvus 2.4 standalone(Docker) | collection `audit_corpus`,全 schema |
| Embedding | **本地 FlagEmbedding BGEM3**(dense+sparse,CPU)——M1 默认 | endpoint 实现保留在 `EmbeddingClient` 接口后(env 配置),但 **M1 不要求跑通** |
| 解析 | 仅 **light**:python-docx(docx 抽结构)+ pdfplumber(pdf/渲染件抽文本) | DeepDoc adapter 属 M2 |
| 渲染 | LibreOffice `soffice --headless`(docx→规范 PDF 渲染件,页码权威) | **系统依赖**;信创可用性待验证(R5a) |
| 文本对齐 | rapidfuzz(精确未中时局部模糊兜底) | 页码锚点回填(见《页码锚点机制》) |
| 数据校验 | pydantic | IR 模型即契约 |
| 对象存储 | 本地文件系统,封装在 `ObjectStore` 接口后 | key 布局对齐 MinIO |
| 部署 | `docker compose`(pg + milvus)+ 宿主机跑 Python | 无 CI |

**Embedding 离线说明**:本地模型首次运行需下载约 2GB。本规格要求在 README 中写明缓存路径(`HF_HOME` / 模型缓存目录),以便无外网的驻场环境预置。缓存预置后,M1 安装须能完全离线运行。

## 命令(Commands)

```bash
# 环境
demo up                                 # docker compose 拉起 pg+milvus,建库 + 建 Milvus collection
demo down                               # 拆除

# 管线
demo ingest <dir> --manifest <xlsx>     # S0 入口;orchestrator 驱动文档至终态
demo status [batch]                     # 各文档 pipeline_status 表
demo reprocess <doc_version_id>         # 全量重跑 + 按 doc_version_id 清孤儿

# 人工审核队列(所有人工动作的唯一入口)
demo queue list
demo queue show <id>                    # 失败指标 + 定位证据 + IR 片段路径
demo queue fix <id>                     # 人工编辑 IR 后重入 QC
demo queue degrade <id>                 # → DEGRADED_INDEXED
demo queue reject <id>                  # → REJECTED
demo queue release <id>                 # 隔离裁决 → 重入

demo meta list
demo meta confirm <id | --batch>        # META_REVIEW 关卡

# 检索与验证
demo search "<q>" [--include-superseded] [--corpus internal|external] [--topk N]
demo verify idempotency                 # 验证 V5(M1 唯一的验证组件)
demo report <batch>                     # JSON + 控制台:解析成功率、QC 一次通过率、各终态计数、锚点填充率

# 开发
docker compose -f compose.yaml up -d    # 底层 compose(demo up 封装它)
pytest                                  # 单元测试
pytest tests/test_chunk_id.py -q        # 跑单个测试文件
pytest -k determinism -q                # 按名跑单个测试
ruff check . && ruff format .           # lint + 格式化
alembic upgrade head                    # 应用迁移
alembic revision -m "add X" --autogenerate
```

> `demo verify smoke|replay|reconcile` 与 `demo rebuild` 属 **M2**——M1 中它们可以是打印"非 M1 范围"并非零退出的占位,或干脆不存在。**禁止伪造**这些断言。

## 项目结构(Project Structure)

依 V0.1 §8(需新建此布局,当前尚不存在):

```
audit-doc-pipeline-demo/         # 仓库根(本目录)
├── compose.yaml                 # pg16 + milvus2.4
├── config/
│   ├── settings.toml            # 连接串、embedding 模式(local/endpoint)、L2/E1 开关
│   ├── qc_thresholds.yaml       # 7 个 QC 指标阈值 + 边缘带 ε(全部 ⚠,禁止硬编码)
│   └── profiles.yaml            # P-INT / P-EXT 档案差异(抽检率字段保留不消费)
├── seeds/                       # dict_issuers.csv、dict_biz_domains.csv
├── fixtures/
│   ├── batch01/                 # 12 件文档 + manifest.xlsx
│   └── batch02_revision/        # 2 件文档 + manifest.xlsx
├── PROMPTS.md                   # 存在,声明"L2 开启时启用";M1 零 LLM 调用
├── alembic/                     # 迁移 = 生产迁移第一批版本(add-only)
├── src/pipeline/
│   ├── cli.py
│   ├── orchestrator.py
│   ├── ir.py                    # pydantic IR 模型 = 契约
│   ├── stages/                  # s0_register、s1_parse、s2_qc、s3_structure、s4_meta、s5_embed_index、finalize
│   ├── parsing/                 # adapter.py + light_parser.py + rendition.py(soffice 封装)+ page_align.py(文本对齐);deepdoc_parser.py 属 M2
│   ├── chunking/                # clause_tree.py、normalize.py、chunker.py
│   ├── qc/                      # indicators.py、gate.py
│   ├── meta/                    # l1_rules.py、version_chain.py
│   ├── index/                   # embedding_client.py、milvus_io.py、pg_io.py、object_store.py
│   └── verify/                  # idempotency.py(smoke/anchor_replay/reconcile/rebuild 属 M2)
└── tests/                       # 单元测试(见测试策略)
```

ObjectStore key 布局(文件系统,对齐 MinIO):`raw/{corpus_type}/{batch_id}/{doc_version_id}.{ext}`(原件)、`rendition/{doc_version_id}.pdf`(docx 规范渲染件)、`ir/{doc_version_id}.json`。

## 页码锚点机制(规范渲染件 + 文本对齐)

不猜测原 docx 分页;摄取时生成**规范渲染件(canonical rendition)**并定义为页码的唯一权威依据。

- **S0.5 生成渲染件**(实现为 `s1_parse` 的首子步,**不新增状态枚举**,守住状态机硬契约):`soffice --headless --convert-to pdf` 把 docx 转 PDF,落 `rendition/{doc_version_id}.pdf`,与原件并存(原件留证不变)。渲染件**写一次**,`reprocess` 复用不重渲(页码元数据稳定;`chunk_id` 不含 page,故 V5 幂等不受影响)。转换失败 → `PARSE_FAILED(E204-DEMO)` 进队列。pdf 入参无需此步——渲染件即其自身,页码由 pdfplumber 原生给出。
- **结构仍从 docx XML 侧解析**(章节条层级、条款边界——docx 远比 PDF 可靠)。
- **页码靠文本对齐从渲染件回填**:pdfplumber 逐页抽渲染件文本 → 归一化(去空白、全半角统一、按 y 坐标剥页眉页脚带,带宽阈值 ⚠ 入 config)→ 拼全文并记录每页字符偏移区间。对 IR 每个 block 按文档序做**单调两指针精确子串匹配**(从上一命中位置向后查),命中偏移落在哪页区间 → page;跨页得 `page_start`/`page_end`。单调性使整体 O(n),且天然消解重复文本歧义(如多处"第X条 删除"占位)。
- **失败优雅降级,复用既有机制**:精确未中(连字符/空格差异)→ 局部窗口 `rapidfuzz` 模糊兜底(阈值 ⚠);仍未中 → `page=null` → 被 QC 指标4(锚点完整率 =100%)拦截 → 补录队列。**不新增关卡。**
- 归一化函数对 block 文本与渲染件文本**对称施用**(同一函数),是对齐成立的前提。

## 代码风格(Code Style)

各 stage 为**纯函数**,签名统一;只通过 PG 状态 + ObjectStore 产物通信,彼此不互相 import。

```python
# src/pipeline/stages/s2_qc.py
def run(ctx: StageContext, doc_version_id: str) -> StageResult:
    """S2 质检关卡。纯函数:不跨 stage import,无隐藏全局状态。

    从 ObjectStore 读 IR,按 config 阈值评估 7 指标,返回下一状态 + 产物。
    由 orchestrator(而非本函数)执行 DB 状态迁移并写 pipeline_events。
    """
    ir = ctx.object_store.load_ir(doc_version_id)
    thresholds = ctx.config.qc_thresholds          # ⚠ 值从 config 读,绝不写字面量
    report = evaluate_indicators(ir, thresholds)   # -> QcReport(pydantic)

    if report.failed:
        return StageResult(
            next_state=PipelineState.QC_FAILED,
            error_code="E301",
            evidence=report.to_evidence(),          # 失败指标 + 页码/条号定位
            queue=QueueItem(queue_type="qc_fix", doc_version_id=doc_version_id),
        )
    return StageResult(next_state=PipelineState.STRUCTURING, marginal=report.marginal)
```

约定:函数/变量用 `snake_case`,pydantic 模型与枚举用 `PascalCase`,状态/枚举成员用 `UPPER_SNAKE`。错误码遵循生产 `E1xx–E8xx` 体系;demo 专属码带 `-DEMO` 后缀(`E202-DEMO`、`E101-DEMO`)。用 `ruff` 格式化与 lint。无魔数——每个 ⚠ 值从 `config/` 读。

## 测试策略(Testing Strategy)

框架:`pytest`。测试置于 `tests/`,目录镜像 `src/pipeline/`。

M1 必需的单元覆盖(S3 的确定性内核——便宜且把关):
- 中文数字归一化——**全分支**(一二三…十百、`第X条之一` 插入条、`21bis`/`21.1b`)。
- 七类节点正则(章/节/条/款/项/目/虚拟根),含虚拟根与插入条边界。
- `chunk_id` 确定性——同输入两次调用同输出(把关 V5)。
- 超长条拆分的条头续接;超短条不合并。
- manifest 9 列校验:缺列/多列整批拒收。
- 文本对齐(页码回填):单调两指针命中、跨页 `page_start/page_end`、重复文本消歧(多处"第X条 删除")、`rapidfuzz` 兜底、未中 → `page=null` → QC 指标4 拦截。

`demo verify idempotency` 是 M1 对 V5 的集成检查(chunk_id 集合不变、Milvus `num_entities` 不变、第二次运行有 `pipeline_events` 记录)。

> 完整 **mini golden set**(5–8 件人工标注条款树,F1 = 1.0 门禁)与 light→DeepDoc 切换回归属 **M2**。M1 交付上述单元测试,暂不要求标注好的 golden-set fixtures。

## 边界(Boundaries)

**始终(Always):**
- 每个 ⚠ 可调值从 `config/` 读(QC 阈值、边缘带 ε、token 区间、批量参数、超时、对齐带宽/模糊阈值)。绝不硬编码。
- 页码权威 = 规范渲染件,结构权威 = docx XML,两者经文本对齐绑定;归一化函数对 block 文本与渲染件文本**对称施用**。渲染件写一次、reprocess 复用不重渲。
- 保持 stage 纯函数且不跨 stage import;所有状态变更 + `pipeline_events` 写入都经 orchestrator。
- 走 `ParserAdapter` / `EmbeddingClient` / `ObjectStore` 接口——绝不直连实现。
- 逐字保留硬契约:`chunk_id` 公式 `sha1(doc_version_id + "|" + clause_path_norm + "|" + seq)[:24]`、manifest 9 列契约、PG 字段名/类型/枚举、Milvus `audit_corpus` schema、写入顺序 PG→Milvus→flush→`INDEXED`。
- 任何提交前先跑 `pytest` 与 `ruff check`。

**先问(Ask first):**
- 任何对硬契约、IR schema、状态机枚举、PG 列的改动(均 add-only;改名/删除需批准)。
- 引入技术栈表以外的依赖。
- 把 M2/M3 范围(DeepDoc、验证套件、E1、L2 LLM)提前并入 M1。
- 改动演示脚本(第 1–9 步)或验收映射。

**绝不(Never):**
- 实现 `perm_tag` 过滤(字段全链路写入;逻辑刻意预留不实现)。
- 在默认路径调用 LLM(M1 零 LLM)。
- 伪造 M2 验证断言(smoke/replay/reconcile/rebuild)来让演示看起来完整。
- 为了变绿而删除或弱化失败的测试。
- 为"简化"而删/改 PG 列或 IR 字段。

## 成功标准(Success Criteria)

| # | 标准 | 检查方式 |
|---|---|---|
| V1 | `batch01` 全部文档到达终态,无悬挂状态 | `demo ingest fixtures/batch01` → `demo status batch01`:预期约 10 件 `INDEXED`、1 件 `QC_FAILED`→修复→`INDEXED`、1 件 `QUARANTINED`;无文档卡在中间态 |
| V2 | QC 关卡拦截跳号文档并给出指标 + 定位;CLI fix 重入达 `INDEXED`;降级路径达 `DEGRADED_INDEXED` | `demo queue show <id>` 打印失败指标 + 页码/条号区间 → `demo queue fix <id>` → `INDEXED`;另 `demo queue degrade <id>` → `DEGRADED_INDEXED` |
| V4 | `batch02_revision` 入库后默认检索不命中旧版;`--include-superseded` 可见旧版且标 `superseded` | `demo ingest fixtures/batch02_revision` → `demo search "<q>"`(仅新版)vs `demo search "<q>" --include-superseded`(旧版可见且带标注) |
| V5 | 重复 ingest 幂等 | `demo verify idempotency` 通过:chunk_id 集合不变、Milvus `num_entities` 不变、第二次运行有事件记录 |
| — | 演示脚本第 1–9 步可端到端跑通 | 按 V0.1 §10 手动走查 |
| — | 单元测试 + lint 通过 | `pytest` 与 `ruff check .` |

每个终态写 `pipeline_events`(时间、操作者[system / CLI `--user`]、前后状态、错误码)。`demo report batch01` 输出 JSON + 控制台摘要:解析成功率、QC 一次通过率、各终态计数、锚点填充率。(T2/T4 通过率属 M2。)

## 已定决策(本轮,原"待确认问题")

1. **report 形态**:M1 的 `demo report` JSON **不含** `t2_pass_rate` / `t4_pass_rate` 键(字段缺省),仅输出四项:解析成功率、QC 一次通过率、各终态计数、锚点填充率。M2 接入 T2/T4 时再加键。不留半成品字段。
2. **M1 检索实现**:目标对 `audit_corpus` 做 **dense+sparse 混合检索**(Milvus hybrid,topk=N),默认 `status=effective` 过滤,`--include-superseded` 去掉该过滤。排序质量**不调优**(非验收点)。**已定兜底**:若 Milvus 2.4 hybrid 集成受阻,退化为 dense-only 并在 `report` 标 `retrieval_mode=dense_only`(不静默);sparse 仍入库 + bytea 冷备,schema 不变,M2 启用 hybrid 不改表。V4 验收只看 `status` 过滤,不受此兜底影响。
3. **Milvus collection**:M1 在**自有 compose** 中用**独立** `audit_corpus`,**不**接入制度查询 demo 的共享库;可随意 drop/rebuild 不影响他人。共库为后续决策(§15.3)。
4. **fixtures 归属**:由**本次工作**负责构造全部 fixtures——`batch01` 正常件 ×10 + 两件坏样例(扫描件 pdf → 隔离演示、跳号 docx → QC 拦截演示)、`batch02_revision` 改版 docx + 修订说明,以及全部 `manifest.xlsx`。坏样例人工构造以保证失败模式确定可复现;fixtures 条款号写**字面文本**(不用 Word 自动编号)以规避 R5b。
5. **docx 页码方案**:不猜测原 docx 分页,改为**规范渲染件 + 文本对齐**(见《页码锚点机制》)。新增依赖 LibreOffice(系统)与 rapidfuzz(Python),**本轮批准**。残留:信创 `soffice` 可用性待验证(R5a)、docx 自动编号边界(R5b)——见 `PLAN.md`。
6. **fixtures 来源(真下载 + 自拟)**:外规走证监会/交易所**公开法规真下载**(已验证可达且文本层:信息披露办法 182/226 号、官方修订说明 3 页;投资者适当性、上交所上市规则待 P1 敲定直链——规章库下载按钮 href 由 JS 注入,需解析文件列表接口或换有直链的部门规章);内规 ×6 用 python-docx **自拟生成**(条款号字面文本,其一含"第X条之一"以覆盖解析边界);**batch02 用真实修订对**——信息披露 182(batch01)→226(batch02)+ 官方《修订说明》,226 声明替代 182 的 logical;坏样例 ×2 脚本**确定构造**(栅格化扫描件 + 删条跳号)。合规:政府/交易所公开信息可直接使用、无需脱敏、demo 不外传。注:部分规章 PDF 逐字加空格排版,`normalize` 去空白须先于 `clause_tree`。详见 `TASKS.md` P1–P4。

---

*下一步:Phase 2(Plan)——见 `PLAN.md`。*
