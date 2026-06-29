# 开发日志(devlog)— 阶段索引

文档处理管线 → audit-ai monorepo → 制度查询智能体(功能1)的**按时间轴阶段索引**。
**本文件已瘦身为索引**:每阶段只留 名称 + 日期 + PR + 一句产出 + 指针;**决策/踩坑的 git 给不了的细节已下沉到各模块 `*_devlog.md`**(见 `CLAUDE.md`「模块开发记忆索引」),改某模块前读对应 devlog。
机械叙述(改了哪些文件 / 测试数 / 迁移号 / 加了什么回归测试)一律以 git log/diff 为准,本文不复述。
> 规格:`file-processing-workflow-docs/SPEC*.md` / `PLAN*.md` / `TASKS*.md`;查询侧 SDD:`query-agent-docs/`;升格:`migration_devlog.md` + `CP-009`;上游生产设计:`文档处理与语料库构建_技术框架设计_v1.6.md`、`制度查询与制度比对智能体_RAG技术框架设计_v1.5.md`。

## 工作方式(贯穿全程)

spec-driven:`SPEC` → `PLAN`(分阶段)→ `TASKS`(任务级验收)→ 逐模块 TDD 实现 → 验证(pytest + ruff,集成测连真栈)→ 停下等用户审批 → 下一个。
- **决策逐个用问答定,不打包**;用户常自带技术方案(如页码对齐、双模式),给空间先听其思路。
- 起步范围 = M1(骨架 + light 解析跑通 S0–S5);M2/M3/查询侧/V16/P0 逐轮追加,各停门控。
- 分工(Claude 规划+实现 ↔ Codex 审查)、测试职责、审查修复闭环 — 见 `CLAUDE.md`「开发协作流程」(已固化,不在此复述)。

## 关键决策记录(按时间,带 why;细节见模块 devlog)

1. **范围 = M1 起步**(验收 V1/V2/V4/V5),M2/M3 后续。
2. **嵌入默认本地 FlagEmbedding(BGE-M3)**,endpoint 留 env(env 桩 fail-fast 在 `__init__`)→ `index_devlog`。
3. **fixtures = 真下载外规 + 自拟内规 + 脚本构造坏样例**(`build_fixtures.py --all` 一键重建)。
4. **页码 = 规范渲染件 + 文本对齐**(用户提出):不猜 docx 分页,soffice 渲染 PDF 作页码权威,结构从 docx XML 抽,`page_align` 单调两指针回填 → `parsing_devlog`。
5. **检索遇阻显式退化 dense-only**(不静默,schema 不变)→ `index_devlog`。
6. **Milvus 独立 collection**(不与查询 demo 共库)。
7. **batch02 用真实修订对**(信息披露 182→226 + 官方修订说明,226 声明替代 182)。
8. **chunker 条内尾块合并**(`target_token_min` 原是死参)→ `structuring_devlog`。
9. **clause_tree bis/.1b 接通**(normalize 早支持、classify 入口够不着)→ `structuring_devlog`。
10. **单段超长条语义边界拆 + 硬切兜底(标 oversize),token_count 量内容** → `structuring_devlog`。
11. **META_REVIEW 双模式(A 默认 / B-严)**:闸的本意是权威边界担责,非抓冲突;"无冲突"≠"正确" → `metadata_devlog`。
12. **查询侧弃 WeightedRanker、选择性 sparse token 提权**(RRF 基于秩无法表达通道权重)→ `query_devlog §5.4`。
> 决策 1–10 = 摄取侧 M1;11 = 阶段 W;12 = 查询侧 SPARSE。后续轮次决策(consumed-when-present、防注入参数化 SQL、不出裸结论三重保障…)见对应模块 devlog。

## 阶段索引

### 摄取管线(M1–M3 + V16 + P0)
| 阶段 | 日期/PR | 一句产出 | 详见 |
|---|---|---|---|
| A 底座 | M1 | config/ir/states/pg(0001)/milvus/objectstore/pg_io | contracts / index / orchestration devlog |
| 流 L 纯逻辑 | M1 | normalize / clause_tree / chunker(chunk_id)/ page_align | structuring / parsing devlog |
| 流 P/SP fixtures+渲染 | M1 | 真外规下载 + 自拟内规 + 坏样例 + soffice 渲染对齐 | parsing devlog;git |
| B 接入到质检 | M1 | orchestrator / s0 登记去重 / light_parser / s1 / s2 七指标 / queue / CLI | orchestration / parsing / qc devlog |
| C 结构化·元数据·向量化 | M1 | s3 切块 / s4+L1 元数据 / version_chain / 嵌入 / milvus / s5 / search·meta CLI | structuring / metadata / index devlog |
| D 版本切换·幂等·报告 | M1 | finalize 原子切换 / idempotency / reprocess / report / M2 占位 | index(finalize)/ eval(report)devlog |
| 检查点 D 走查 | M1 | batch01 = 9 INDEXED+1 DEGRADED+1 QUARANTINED;修指标3 插入条 + 跨法引用 + 做全小数 | qc / structuring devlog |
| M2 验证套件 | M2 | T2 smoke / T4 replay / reconcile / rebuild / golden / finalize 跑 T2·T4 留痕 | eval / structuring(golden)devlog |
| M3 E1 义务打标 | M3 | 零-LLM 正则义务打标(探针定词表)+ report 全量打磨;V8 | enrich / eval devlog |
| W Web 工作台 + 双模式 + 目录区域化 | 2026-06;PR #1 另分支 | demo-web(thin shell)+ META_REVIEW 双模式 + clause_tree 目录区域化 | web / metadata / orchestration / structuring devlog |
| V16 生产 v1.6 保真 | 2026-06-18/19;PR #4 | Milvus/PG/manifest v1.6 全字段(0005–0007)+ 四类语料 profile 路由 + E2 LLM 打标 + cases 表 + 案例语料调优 | contracts / structuring / metadata / enrich / qc / index devlog |
| S 评测工具 doc_test | 2026-06-24;PR #13 | `tools/doc_test/` 真实 PDF 三目标评测(非生产包,免审合入) | git;parsing devlog(冒烟发现) |
| P0 Foundation | 2026-06-26;PR #17 | 字典/业务域迁移 + IR ocr_conf/表格 markdown(T0.1/T0.2,0009) | contracts / structuring devlog |
| P0 Phase 1 | 2026-06-26;PR #18 | 切块 internal_refs / case_ref_align / xlsx parser-only(收窄)(0010) | structuring devlog |
| P0 Phase 2 案例 L2 | 2026-06-26;PR #20 | 案例引用外规对齐 + 违规事由分类(默认关,0011) | metadata / enrich devlog |
| P0 Phase 2 续 业务域 L2 | 2026-06-26;PR #22 | L2 业务域多值打标 + profile 分档(P0 LLM 4 触点全清) | metadata / index devlog |
| P0 续 ref_resolver R4 | 2026-06-28;feat/ref-resolver-r4 | 跨文档指代三级查(文号→标题→dict_aliases 别名)+ 四态 standoff(resolved/ambiguous/pending_target/unresolved)+ R3/R4 span 去重(零迁移) | structuring devlog |
| P0 续 扫描件 OCR | 2026-06-29;feat/ocr-mineru | MinerU pipeline 后端(in-process do_parse → IR + ocr_conf + 表格)+ s1 路由(扫描件/图片→OCR,PIPELINE_OCR_BACKEND 默认关向后兼容)+ 白名单 jpg/png;spike risk-first(multiprocessing spawn 约束)+ 零迁移 | parsing devlog |

### 制度查询智能体(功能1,独立 `query/` 包;DAG `query→pipeline→common`)
> 全部细节在 `query-agent-docs/query_devlog.md`(每路一节)+ SPEC/PLAN/TASKS/RTM/GAP。本表仅时间线。
| 阶段 | 日期/PR | 一句产出 | 详见 |
|---|---|---|---|
| Q R1+R2 + 协作/记忆收口 | 2026-06-22~23;PR #5/#6/#7 | R1 依据查询(覆盖感知拒答 + 八路骨架 + LangGraph)+ R2 变更(零 LLM 条款级 diff)+ 协作流程入 CLAUDE.md + devlog 归位 | query_devlog R1/R2 |
| R R3+R6 + RTM | 2026-06-23~24;PR #9–#12 | R3 相似案例+桥接(一案一卡)+ R6 统计(防注入参数化 SQL)+ RTM 全覆盖证明 | query_devlog R3/R6 |
| R4 多文档列举 | 2026-06-24;PR #14 | enumerate 高 k + Milvus 标量/E1 义务过滤 + TABLE;`milvus_io.search` 加 extra_expr(add-only) | query_devlog R4 |
| R5 判定型(八路收官) | 2026-06-24;PR #15 | judgmental + 三段式 + 不出裸结论三重保障 + §9.2 接口;八路全实装 | query_devlog R5 |
| RERANK §5.5 | 2026-06-25;PR #16 | bge-reranker-v2-m3 重排(默认 none byte 等价);FlagReranker 不兼容 transformers 5.x→直载 | query_devlog §5.5 |
| SPARSE §5.4 | 2026-06-26;PR #19 | sparse 发文字号提权 + 词典扩展(弃 WeightedRanker);worktree 隔离 | query_devlog §5.4 |
| REVIEW §9.2 | 2026-06-26;PR #21+#23 | Kimi 忠实性复核接真模型(独立 review_model + 喂条文原文);RL-1 翻 ✅、⏳ 待真 gateway 跑绿 | query_devlog §9.2 |
| N0 多轮归并 + R7 闭环 | 2026-06-28;worktree feat/query-n0-multiturn | N0 实装(LLM 为主默认开 + 规则版离线兜底 + fail-safe)+ R7 澄清闭环(跨请求重入,非图内环);ask(history)+CLI --history-json;状态契约零改、单轮 byte 等价;真-LLM 门控⏳待跑绿 | query_devlog N0 |

### 升格 + 基础设施
| 项 | 详见 |
|---|---|
| audit-ai 原地升格(Step 0–7) | `migration_devlog.md` + `CP-009` + `migration-manifest.md` |
| `/clear` 自动存档 hook | `~/.claude/hooks/save-devlog-on-clear.sh`(CC 配置层,不入仓库;空 commit 门控 + 只记 git 给不了的内容) |

## 已建链路(当前全貌,live reference)

`demo ingest`(s0 登记+版本关系+SHA 去重审计)→ s1(渲染+解析+page_align)→ s2(七指标质检)→ STRUCTURING 复合(s3 切块 + E1 义务打标 + s4 元数据校验)→ META_REVIEW(**A 模式**全件入 meta_confirm 人工闸;**B-严**:无冲突全新件直通、冲突件+修订件仍入闸)→ `meta confirm`(approve)→ EMBEDDING(s5 嵌入+冷备)→ INDEXING(Milvus 索引 + 翻 effective)→ INDEXED → **finalize**(带 supersedes 自动置旧版 superseded;跑 T2/T4 留痕)。
`search` 混合查出四级引用(默认 effective,`--include-superseded` 见旧版);degrade 重入索引终于 DEGRADED_INDEXED;失败件入统一队列(qc_fix/quarantine/meta_confirm 三类)经 `dispose` 处置;`demo verify smoke/replay/reconcile`、`rebuild`、`report` 出验证指标。
四类语料按 `corpus_type` profile 路由(P-INT/P-EXT 条款树、P-QA 问答对、P-CASE 要素+cases 表);E2/L2/案例 L2 LLM 富集默认关。
**检查点 A/B/C/D/M2/M3 全达成,V1–V8 全过;查询侧八路全实装。**

## 测试与运行约定

- venv:`.venv/bin/python -m pytest -q`、`.venv/bin/ruff check .`(testpaths 含 pipeline/common/eval/query)。
- 集成测连真栈、栈未起则 skip;各自按 batch_id 反 FK 序清理。**测试文件基名须全仓唯一**(pytest prepend + tests 无 `__init__.py`,撞名致收集报错)。
- 模型门控集成假定**干净栈**(SHA 去重):跑前 `demo down -v && demo up` 或清库,否则走查残留致去重撞车。**提交前必跑模型门控全量**(无模型时 skip,漏回归)。
- 真模型:`PIPELINE_EMBEDDING_MODEL` 指 modelscope 本地缓存(完整)+ `HF_HUB_OFFLINE=1`;未设则相关测试自动 skip,绝不联网。
- 迁移 add-only:autogenerate → upgrade → `alembic check` 无漂移;`alembic/versions` 纳入 ruff,autogenerate 后 `ruff check --fix alembic/versions && ruff format alembic/versions` 再提交。
- 行宽 100,ruff(E/F/I/UP/B);CJK 注释易超行 → 独立行/缩短。
- Milvus standalone 偶发瞬时 gRPC 卡死:`ps -o etime,cputime` CPU≪墙钟即卡 → `demo down -v && demo up`(详见 `web_devlog`)。
