# audit-ai 原地升格 devlog

**职责**:把单包 demo 原地升格为 audit-ai monorepo(分支 `migrate/audit-ai-skeleton`,Step 0–7,13 commits)。**完整规范见 `CP-009-仓库与升格规范.md`,文件级映射见 `migration-manifest.md`**;本文只记关键决策 + 踩坑。

## 9 项决策(Step 0 锁定,全采纳推荐)
① 无 demo 代码的 Checkpointer/GraphStore 接缝**不建**(仅 CP-009 约定)· ② `eval→pipeline→common` · ③ 整个 `verify/` 搬 `eval/` · ④ `states` 暂按机制进 pipeline · ⑤ config/seeds(**修订**,见下)· ⑥ web 暂留 pipeline · ⑦ 测试按包共置 · ⑧ alembic 留 repo 根 · ⑨ v1.6/v1.5 入库 docs。

## 关键执行 / 踩坑
- **契约迁移(Step 2)**:`ir`/`pg_models` 纯文件 git mv;`chunk_id`/`milvus_schema`/`manifest` 从机制文件 surgical 抽取;**byte 守恒**(pin 钉死);`common` 零上行依赖。
- **整树搬迁(Step 3a)**:`src/pipeline → pipeline/pipeline`,**import 名 `pipeline` 不变 → 零 import 改动**。`parents[N]` 深度巧合不变(`src/pipeline/X` 与 `pipeline/pipeline/X` 同深),故 `REPO_ROOT`/`DEFAULT_CONFIG_DIR` 等不动。
- **断 `pipeline⇄eval` 环(Step 4,懒导入)**:cli/web/finalize 对 eval 组件改**函数级懒导入** → `import pipeline.*` 零拉入 eval(实测 sys.modules 无 eval.*),声明依赖无环。
- **决策⑤修订(最关键踩坑)**:config/seeds 原定迁 pipeline,但 **flat 布局下成员目录 `pipeline/` 与 import 包 `pipeline` 同名**——`config/` 置 `pipeline/` 内,则 cwd=repo 根在 `sys.path` 时 `pipeline/config` 作**命名空间包遮蔽 `pipeline.config` 模块** → **实测 break `python -m alembic`(=`demo up` 建库)**。editable finder 追加在 `sys.meta_path` 尾、cwd 路径优先,重装无效。**故 config/seeds 作 workspace 级置 repo 根**(与 alembic/、compose.yaml 一致);`config.py` 模块仍属 pipeline。
- **验证(Step 5)**:干净栈(`demo down -v && demo up`)+ 本地 BGE-M3 全量 **282 passed / 0 failed**(13min);chunk_id pin byte-exact、golden F1=1.0、eval 全过。修 2 处测试共置后路径陈旧(`test_static` 写死 `src/`、`test_seed_dicts` parents 深度)。
- **codegraph(Step 6)**:本机联网装 1.0.1 + `codegraph init` 建基线索引(108 files / 1,663 nodes;query 命中迁移后路径);`.codegraph/` gitignore;`.githooks/`(post-merge/post-checkout/pre-push → `codegraph sync`,`command -v codegraph || exit 0` 守卫);MCP 装进**项目级** CC(`.mcp.json` + `.claude/settings.json` + `.claude/CLAUDE.md` 共享入库;索引 + `.claude/settings.local.json` 不入库)。

## 工具链
setuptools 无原生 workspace:root `pyproject` = `audit-ai` 聚合(`packages=[]`,仅 alembic + dev 工具 + `[tool.audit_workspace] members`);成员各 `pip install -e`;pytest `pythonpath/testpaths` 列三成员;ruff `known-first-party=[common,pipeline,eval]`。

> 完整:`CP-009-仓库与升格规范.md`(布局/依赖/接缝/codegraph/三信创确认)+ `migration-manifest.md`(每文件映射)+ 分支 git log(Step 0–7 原子提交)。
