# 文档处理管线 · 本地 Demo(M1)

生产设计 S0–S5 主干的本地最小可运行实现。设计与决策见 `SPEC.md` / `PLAN.md` / `TASKS.md`,
开发约定见 `CLAUDE.md`。本文件只讲怎么跑起来。

## 环境前置

- **Python 3.11**(`grpcio`/`torch` 在更高版本暂无 wheel;详见 SPEC)
- **Docker**(`docker compose` 起 pg16 + Milvus 2.4 standalone)
- 本地嵌入(可选)需 `BAAI/bge-m3` 模型缓存,见下「离线嵌入缓存」

## 安装

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"     # 核心 + 开发工具(pytest/ruff)
# 本地嵌入(local 模式)再装(含 torch,较重):
.venv/bin/pip install -e ".[embed]"
```

## 起停与建库

```bash
.venv/bin/demo up      # docker compose 起 pg+milvus,健康等待,alembic upgrade head 建库
.venv/bin/demo down    # 拆除(保留数据卷);加 -v 连卷一起删
```

> 首次 `demo up` 会拉 Milvus/etcd/minio/pg 镜像(~1GB)并等 Milvus 启动(~90s)。

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
