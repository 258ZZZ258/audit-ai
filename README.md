# audit-ai · 智能审计平台(monorepo)

智能审计平台的代码仓库。**整个平台的 agent 相关代码都归集于此仓**(Python monorepo,由"文档处理管线 demo"
原地升格而来——见 `docs/CP-009-仓库与升格规范.md` / `docs/migration_devlog.md`)。

当前已落地 **文档处理与语料库构建** 子系统(S0–S5 管线 + 验证套件 + Web 工作台,生产设计主干的最小可运行实现);
**制度查询 / 制度比对等智能体代码后续加入本仓**(布局约定与抽包触发见 CP-009)。

> 架构与硬契约见 `CLAUDE.md`(底部「模块开发记忆索引」→ 各包内 `*_devlog.md`);文档处理子系统规格见
> `docs/file-processing-workflow-docs/SPEC*.md` / `docs/file-processing-workflow-docs/PLAN*.md` / `docs/file-processing-workflow-docs/TASKS*.md`;设计依据 `docs/文档处理与语料库构建_技术框架设计_v1.6.md`、
> `docs/制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`。本文件只讲怎么跑起来。

## 仓库结构(workspace)

```
libs/common   契约承重层(IR / chunk_id / PG 模型 / Milvus schema / manifest),不依赖任何上层
pipeline      文档处理管线(S0–S5/finalize · 解析/编排接缝 · web 工作台)          → common
eval          验证组件(冒烟 / 锚点回放 / 对账 / 重建 / 幂等 / 报告)                → pipeline → common
config/ · seeds/ · alembic/ · compose.yaml    workspace 级配置 / 数据 / 运维(置 repo 根)
```

**约定但未建**(待第一份真实代码 / 第二个消费方出现再建,见 CP-009 §1/§3):`libs/rag` · `libs/orchestration` ·
`libs/doc_compare` · `libs/report_gen` · `services/*`——后续智能体子系统在此扩展。依赖方向只能向下(`eval→pipeline→common`)。

## 环境前置

- **Python 3.11**(`grpcio`/`torch` 在更高版本暂无 wheel;详见 SPEC)
- **Docker**(`docker compose` 起 pg16 + Milvus 2.4 standalone)
- 本地嵌入(可选)需 `BAAI/bge-m3` 模型缓存,见下「离线嵌入缓存」

## 安装(workspace 各成员 editable)

```bash
python3.11 -m venv .venv
# 顺序敏感:先 common(pipeline/eval 依赖它)
.venv/bin/pip install -e libs/common
.venv/bin/pip install -e pipeline
.venv/bin/pip install -e eval
.venv/bin/pip install -e ".[dev]"          # 根:dev 工具(pytest/ruff)+ 运维(alembic)
# 本地嵌入(local 模式)再装(含 torch,较重):
.venv/bin/pip install -e "pipeline[embed]"
```

## 起停与建库

```bash
.venv/bin/demo up      # docker compose 起 pg+milvus,健康等待,alembic upgrade head 建库
.venv/bin/demo down    # 拆除(保留数据卷);加 -v 连卷一起删
```

> 首次 `demo up` 会拉 Milvus/etcd/minio/pg 镜像(~1GB)并等 Milvus 启动(~90s)。

## Web 工作台(`demo-web`)

栈起来后,可用浏览器工作台代替 CLI 驱动整条管线(纯标准库 HTTP,无构建步骤):

```bash
.venv/bin/demo-web                         # 默认 127.0.0.1:8765
.venv/bin/demo-web --host 0.0.0.0 --port 8800
```

打开 http://127.0.0.1:8765。它是管线域逻辑的**薄壳**(PG 为权威、Milvus 为投影,复用与 CLI 同一套
状态机 / 统一队列 / 检索):

- **上传入管线**:拖拽 docx/pdf(可附 `manifest.xlsx`)→ S0 登记 → 自动推进
- **统一人工复核队列**:`qc_fix` / `quarantine` / `meta_confirm` 三类在一处处置(修复重试 / 降级 / 驳回 / 放行 / 确认)
- **检索**:混合查出四级引用(文档+文号 / 条款路径 / 页码 / 版本+状态),义务条款标 `[义务]`
- **批次 / 文档详情**:管线节点状态、产物(原件 / 渲染件 / IR / 分块 / Milvus)、事件流、分块
- **验证 / 报告**:smoke / replay / reconcile + 批次报告

> 需先 `demo up`。检索与 B 模式(`config/settings.toml` 的 `auto_confirm_meta_no_conflict`,无冲突件
> 自动放行)自动入库需本地嵌入模型(见下「离线嵌入缓存」);其余功能免模型。

## 配置

所有 ⚠ 可调值在 `config/`(`settings.toml` / `qc_thresholds.yaml` / `profiles.yaml`)。
连接串与密钥可用环境变量覆盖:`PIPELINE_DB_DSN`、`PIPELINE_MILVUS_HOST`、
`PIPELINE_EMBEDDING_MODE`、`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`HF_HOME`。

## 离线嵌入缓存(驻场无外网)

本地嵌入默认用 `BAAI/bge-m3`(dense+sparse),首次需联网下载 ~2GB。驻场内网无外网时:

1. 在有网机器:`export HF_HOME=/some/cache && python -c "from FlagEmbedding import BGEM3FlagModel; BGEM3FlagModel('BAAI/bge-m3')"`
2. 将 `$HF_HOME` 整目录拷贝到驻场机器;
3. 驻场机器 `export HF_HOME=/拷贝路径`,`config/settings.toml` 保持 `[embedding] mode = "local"`。

或改用网关:`mode = "endpoint"` + `OPENAI_BASE_URL`/`OPENAI_API_KEY`(对齐生产 CP-005)。

## 测试

```bash
.venv/bin/pytest          # 单元测试
.venv/bin/ruff check .    # lint
```

## 代码图谱(codegraph,可选)

仓内已带 codegraph 配置(`.mcp.json` + `.claude/`,团队共享);**索引本体 `.codegraph/` 不入库,各自本地建**。启用:

```bash
npm i -g @colbymchenry/codegraph    # 装 CLI(一次)
codegraph init                      # 建本地索引(.codegraph/,已 gitignore)
```

装好后:命令行 `codegraph query|explore|node <…>` 可用;重启 Claude Code 后其 MCP 工具(只读,已 auto-allow)即生效。
`.githooks/` 的 `codegraph sync` 钩子有 `command -v codegraph || exit 0` 守卫——**未装 codegraph 不影响任何流程**。
启用钩子:`git config core.hooksPath .githooks`。详见 `docs/CP-009-仓库与升格规范.md §5`。
