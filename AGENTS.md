# AGENTS.md

本文件指导 Codex(及其它编码代理)在本仓工作。**架构 / 契约 / 状态机 / 配置 / 测试约定以
`CLAUDE.md` 为单一事实源**(本文件不重述,以免再次过时)——动代码前先读 `CLAUDE.md`,改契约前
读 `docs/file-processing-workflow-docs/SPEC*.md`("裁机制不裁契约")。

## 本仓是什么(一句话)

`audit-ai` monorepo:文档处理/语料构建管线(`libs/common` 契约 → `pipeline` S0–S5 → `eval` 验证)+
制度查询智能体(`query/`,功能1 MVP)。详见 `CLAUDE.md`。

## 开发协作分工(与 CLAUDE.md 一致)

- **Claude Code(规划 + 实现)**:需求规划、计划/任务分解、代码生成。用 skills
  `spec-driven-development` → `planning-and-task-breakdown` → `incremental-implementation` +
  `test-driven-development`,每阶段门控待人工批准。
- **Codex(代码审查)—— 本文件的主对象**:负责开发生命周期中的代码审查,用 skills
  `code-review-and-quality` + `security-and-hardening`。
- **审查修复闭环**:你(Codex)审查 → 发现写 `.review/findings.json`(按 `.cursor/rules/review-output.mdc`)→
  **由 Claude Code(原作者)逐条修复或带 `spec_ref` 理由反驳** → 你**复审**新 diff,直至无 critical/warning。
  **你只审不改:绝不自行修改实现代码**(修复归实现侧,保审查独立性——改动也须被独立验证);
  纯机械项(格式 / lint)交 `ruff --fix` 等工具。

## Codex 审查时的硬约束(务必校核,细节见 CLAUDE.md「硬契约」)

- **契约不可改**:`chunk_id` 公式、manifest 9 列、PG 字段(add-only)、Milvus `audit_corpus` schema、
  IR schema、写序(PG→Milvus upsert→flush→INDEXED)。PR 若触碰这些,按高危项标出。
- **依赖 DAG 无环**:`eval`/`query` 不得被 `pipeline`/`common` 在 import 期反依赖;`pipeline` 调 `eval`
  须函数级懒导入。审查跨包 import 时校核方向。
- **stage 纯函数**:`(ctx, dvid)->StageResult`,只经 PG 状态 + ObjectStore 通信,互不 import。
- **默认零 LLM / 零网络**:LLM 默认全关(摄取侧)/ stub(查询侧);审查新代码不得在默认路径引入网络调用。
- **测试**:`.venv/bin/python -m pytest -q` + `.venv/bin/ruff check .`;**测试文件基名须全仓唯一**
  (pytest prepend 模式 + tests 无 `__init__.py`);迁移 add-only、`alembic check` 无漂移。

## 审查产出约定

代码审查完成后按 `.cursor/rules/review-output.mdc` 将发现写入 `.review/findings.json`(供 Review Lens 消费):
`version=1`、`findings[]` 含 file/start_line/end_line/severity/rule_id/spec_ref/message/anchor_text;
`anchor_text` 必须是目标文件逐字原文,写入前重读核对行号。
