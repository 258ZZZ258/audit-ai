# Web 工作台 devlog(pipeline/pipeline/web)

**职责**:`demo-web` 标准库 HTTP 工作台,**thin shell over 域函数**(PG 权威 / Milvus 投影,复用同一套 queue/状态机/`reprocess_to_indexed`,不复刻 CLI 逻辑)。`app.py`(HTTP/路由/多部件)· `service.py`(域调用)· `static/`(前端)。

## 关键决策 / 踩坑
- **后端硬化(批 2)**:`cgi`→纯标准库多部件解析(`_parse_multipart`/`_parse_content_type`;3.13 移除 cgi、机器默认 3.14)——**保二进制无损**(只剥框定 CRLF,单测验含 `\r\n`/尾换行文件逐字节回灌);上传/JSON 体上限(Content-Length 超限先拒 → 413)。
- **前端 XSS 整类收口(批 1)**:加 `h` 标签模板(插值**默认转义**)+ `raw()`(放行已构好的安全片段),所有写 innerHTML 的渲染函数走 `h`;关 ~8 处漏转义 sink(最关键 `actor`=用户可控 operator)。前端无 JS 测试框架,靠断言 + 审计。
- **search 结果面板 + withBusy(批 2)**:招牌四级引用从仅 JSON 入日志 → `renderSearch` 面板(条款路径/页/语料/`[义务]`/score),`service.search` 复用 `cli._obligation_chunk_ids` 标 `is_obligation`(不动 Milvus schema);`withBusy(btn,fn)` 套慢操作防卡死观感 + 双击竞态。
- **B 模式驱动正确性(B1 blocker)**:dispose/ingest 重入在 B 模式用 worker 上下文过 s5+finalize,`_advance_one` 过渡态守卫兜底(详见 `../orchestration_devlog.md`)。
- **踩坑**:`unique_docx` 首段「第一章 总则」≠ manifest 标题 → 天然 title 冲突(`ir.title`=docx 首段),在 A 模式被「全件入闸」掩盖、B 模式才现形 → 端到端须自造「首段=标题」的真无冲突件。

## 升格
web 随 pipeline 包内迁(`pipeline/pipeline/web/`);`service.REPO_ROOT = parents[3]`、`app.STATIC_DIR = __file__.with_name("static")` 深度巧合不变;**暂留 pipeline、不抽 `services/`**(决策⑥,禁建 services/*;待独立部署再抽)。

> 时间轴:`docs/devlog.md` 阶段 W(web + 双模式 + 审查批 1/2)、升格。
> 注:错误码可读提示 + 元数据冲突一键采用是**另一分支** `feat/web-error-hints-and-conflict-resolve`(PR #1,未并入升格分支)。
