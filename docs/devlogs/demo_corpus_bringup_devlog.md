# Demo 语料入库 + 逐节点 LLM 验证 — 开发 devlog

> **定位**:2026-06-29-30,在**无甲方业务配合**下,把一批爬取语料(只外规 + 案例)自动装配、入库到隔离
> demo 栈,并**逐一真栈验证每个需 LLM 的节点**。本 devlog 只记 git 给不了的——**决策 + 否决方案 +
> 非显然踩坑**;时间线/diff 看 `demo/corpus-bringup` 分支 commit。
>
> **产物去向**:工具/真 bug 修复抽成 3 个独立 main PR(#32/#33/#34);语料/manifest/字典值/隔离栈配置
> 留 `demo/corpus-bringup` 分支(demo 专属值,不入 main)。

---

## 0. 背景与总目标

爬取语料 `/Users/apple/东方/demo用文档库`(5177 文件)无登记表、无字典。目标:① 完成入库 ② 同时逐一测
需 LLM 的节点 ③ 自动化获取"智能体运行所需装配件"(manifest + 字典)。LLM 网关用 **DeepSeek V4**
(flash/pro 分档),key 走 env 绝不入库。

---

## 1. 环境隔离与模型分档(决策)

### 1.1 隔离 demo 栈(否决:重置共享栈)
主仓测试栈 `audit-doc-pipeline-demo`(5432/19530)已跑 3 天有数据。**否决**"`down -v` 重置共享栈"——
会毁他人数据 + 仍需全局串行。**采纳**:demo worktree 内改 `compose.yaml`(项目名 `audit-demo`、宿主端口
**5433/19531/9092**),`demo up/down` 即操作隔离栈。**卷按项目名自动隔离**,故只需改 `name` + 3 个发布端口。
- **踩坑**:Milvus `port` 无 env 覆盖(只 `PIPELINE_MILVUS_HOST`),须改 `settings.toml [milvus] port`;
  PG 走 `[db] dsn` 或 `PIPELINE_DB_DSN`(alembic 也读 `load_config().db.dsn`)。
- **踩坑**:`demo up` 硬编码 `REPO_ROOT/compose.yaml`,`REPO_ROOT=parents[2]`=worktree 根 → worktree 内跑
  `python -m pipeline.cli up` 自然用 worktree 的 compose + DSN。64G 机两栈并存无压力。

### 1.2 flash/pro 按任务分档(决策)
原则:**高频/字典约束/检索辅助→flash;低频/高价值/用户可见/吃推理→pro**。
- 管线:E2/L2/案例分类=flash;**case_l2 T2.1 引用外规抽取=pro**(全管线最高价值字段,法条抽取+模糊对齐)。
- 查询:N0/N1/N3=flash;R1 主答 + R5 框定/复核=pro。
- **踩坑(关键)**:`OPENAI_MODEL` 是**管线+查询共享旋钮**(两侧 config 都读它),无法用一个 env 把"管线 flash、
  查询主答 pro"分开 → 管线走 `[llm] model`、查询主答走 `[query] llm_model`、查询各节点走 `QUERY_*_MODEL`,
  **绝不设 `OPENAI_MODEL`**。case_l2 单独档需 add-only 加 `LlmConfig.case_l2_model`(PR #32)。

---

## 2. 自动登记链(无甲方装配自动化)

把"过滤→分类→去重→字典→manifest→装配"做成 5 个工具(扩展 `tools/doc_test`,→ PR #33)。

### 2.1 语料真相推翻"目录=类型"(踩坑)
**目录名严重误导**:`beijing_regulatory_pdfs`(名字带 regulatory)其实全是**案例**(警示函决定);`case/` 是
大杂烩(交易所自律规则 + 国家法律 + 司法解释 + 案例)。→ **corpus_type 必须按内容(LLM)判,不能信目录**。
启发式按文件名分类有真错(《行政处罚法》《处分条例》被"处分/处罚"误判成案例),`classify.py` 的 LLM 纠正了 29 处。

### 2.2 跨格式去重 + 格式归一(决策 + 踩坑)
- 5177 文件含 **2268 pdf + 1446 txt + 994 docx + 450 doc**;同一文档常 pdf+txt 双份(案例 980 件如此)。
  去重 5177→**3080 唯一**。**决策**:案例留 PDF(否决留 txt:无页码 → 毁四级回溯)。
- **踩坑**:S0 格式白名单 = `{pdf,docx,jpg,png}` 且按 **magic number** 探测;`.doc`(OLE)/`.txt` → unknown
  → **整件隔离**。样本里 ~69 件只有 doc/txt → **soffice 转 pdf**(否决直接丢:损失 29% 覆盖 + 部分只此格式
  的外规)。`stage_corpus.py` 转换 62/62 成功。
- **踩坑**:13 件"pdf"其实是**爬坏的非真 PDF**(magic 非 `%PDF-`)→ S0 正确隔离(E101)。过滤奏效。

### 2.3 引用感知抽样(决策)
**否决**外规随机抽样:case_l2 T2.1 要把案例引用对齐到外规库,随机抽外规会让 T2.1 大多 unresolved、showcase
成色差。**采纳**:先从案例 txt 正则采集引用题名/文号,外规抽样**优先覆盖被引外规**。结果 250 样本里 84 件外规
覆盖案例引用 → T2.1 实测 259 引用、**97 条 resolved 条款级锚定**。

### 2.4 manifest 全量生成(决策 + 踩坑)
`gen_manifest.py`:corpus_type/sub_type 来自分类;title/issuer 走 L1 正则 + L2 LLM(issuer **修好了** light
正则的 penalty_org 粒度——"证监会"→"中国证监会北京监管局");perm_tag 默认"公开";supersedes 空。
- **踩坑(关键)**:初版 manifest 的 `issue_date` 取**文件名日期**,与管线 S4 的 **L1 正文日期**系统性冲突
  → 大量 META_REVIEW。**改为 issue_date/effective_date 留空交 L1 抽正文权威日期**,冲突大减。
- **契约**:manifest 11 列**精确匹配**(多/缺列整批拒);perm_tag 空 → 隔离"密级缺失",故须默认填。

### 2.5 字典自举(决策)
`bootstrap_dicts.py` 从样本反推 4 个强信号字典(violation_types 15/issuers 14/aliases 70/biz_domains 19,
标 `v0-draft-demo` **待甲方评审**)。`entity_types`/`departments` 是**券商内部分类、为内规设计**,外规+案例
信号弱 → 沿用现有 v0-draft,不覆盖(见 §4 E2 结果)。

---

## 3. 入库工作流(确立)

`ingest <批目录> -m <manifest>` → **`meta confirm --batch`**(放行 manifest/L1 元数据冲突,人工闸等价)→
QC_FAILED **`queue degrade`**(残破件转 DEGRADED_INDEXED 全文可检索)。外规**先入**(case_l2 T2.1 要对齐
已索引外规),案例后入。
- **踩坑**:`queue degrade` 把 QC_FAILED → STRUCTURING → 又撞元数据冲突 → META_REVIEW,需**再 meta confirm**
  才到 DEGRADED_INDEXED;且逐件 reprocess 各自加载 BGE-M3,批量慢。
- **踩坑**:E2 若对全部外规逐 chunk 调 LLM(数千 chunk)要数小时 → **大批量关 E2,单独小样本验证**。

---

## 4. 逐节点验证结果(真栈 + 真 LLM)

入库:**185 INDEXED · 3547 chunks** · 17 QUARANTINED(13 爬坏 + 4 扫描)· 36 QC_FAILED · 1 DEGRADED。

| 节点 | 档 | 结果 |
|---|---|---|
| manifest L1/L2 | flash | ✅ issuer 精确;biz_domain 约束命中 85% |
| E1 义务(规则) | — | ✅ 2114 义务标 + 614 期限 |
| **case_l2 T2.1 引用外规对齐** | **pro** | ✅ **showcase**:259 引用、97 resolved 条款级(神雾环保→《信披办法》3/30、4/48) |
| case_l2 T2.2 违规分类 | flash | ✅ 81/85,全约束在自举 dict 内 |
| E2 实体/部门/事项 | flash | ✅ **机制正确**(对含"合规部/C类营业部"文本正确抽取+裁剪);本语料产出空——dict 为内规设计 |
| N0 多轮归并 | flash | ✅ 指代"它"消解为上轮《信披办法》→ 检索到第五十五条 |
| N1 HyDE / N3 分解 | flash | ✅ 查询内运行 |
| R1 主答 | pro | ✅ 中性答复(无裸结论)+ 5 引用四级回溯 + 3 案例卡 |
| R5 框定 + 复核 | pro | ✅ 复核降级无依据表述为"待人工核实";红线无裸结论 |
| R8 拒答 | — | ✅ 覆盖感知拒答 |

四红线全过:无编造引用 / 无裸结论 / 可解释拒答 / 四级回溯。

---

## 5. 关键踩坑汇总(易再踩)

1. **DeepSeek JSON 模式硬要求**:`response_format=json_object` 时 **prompt 必须含 "json" 字样 + 示例**,
   否则 **400 Bad Request**;且**偶发返回空 content**(JSON 解析失败)。
   - R5 `framing._llm_constituent` 内联 prompt 漏了 → 400;且无 fail-safe → 崩 R5。**已修(PR #34)**:加
     json+示例 + try/except 回落 clause直呈。其它节点 prompt 在 `PROMPTS.md` 都有 json,故未踩。
   - **教训**:凡 `chat_json` 的 prompt 都要含 json+示例;查询侧增强节点都要 fail-safe(对齐 N0/N1/N3)。
2. **`OPENAI_MODEL` 共享旋钮**(§1.2):分档靠 settings + `QUERY_*_MODEL`,绝不设 `OPENAI_MODEL`。
3. **目录名不可信**(§2.1):corpus_type 按内容判。
4. **S0 格式白名单 magic-number 探测**(§2.2):doc/txt/损坏件会隔离;doc/txt 须先转 pdf。
5. **manifest 日期宜交 L1**(§2.4):文件名日期 ≠ 正文发文日 → 系统性 META_REVIEW。
6. **`query/query/cli.py` 无 `__main__` guard**:`python -m query.cli` 不触发 app();用
   `python -c "from query.cli import app; app()"` 或装好的 `query` 控制台脚本。
7. **degrade 二次冲突**(§3):degrade 后需再 meta confirm 才到终态。

---

## 6. main vs demo 归属

- **→ main(生产可复用)**:`tools/doc_test/{curate,classify,bootstrap_dicts,stage_corpus,gen_manifest}.py`
  (**PR #33**);`LlmConfig.case_l2_model` + `.env*` gitignore(**PR #32**);R5 framing 修复(**PR #34**)。
- **→ demo(`demo/corpus-bringup` 分支,专属值)**:语料/manifest/字典值;隔离栈 `compose.yaml`(端口)+
  `settings.toml`(DeepSeek 激活 + 端口);qc 阈值 `page_anchor_complete_min` **1.0→0.8**(渲染件实证,
  **未动 main 默认**,作为"目标③"发现供讨论)。

**候选回 main 的发现**(未在 PR 改默认):页锚阈值对渲染件过严;复杂法律/交易所规则需 DeepDoc(36 件 QC 失败)。

---

## 7. 复现(demo worktree 内)

```bash
cd /Users/apple/Projects/audit-ai-demo
set -a; . ./.env.local; set +a                 # DeepSeek key + 网关 + BGE-M3 路径 + 离线
export PYTHONPATH=$PWD/libs/common:$PWD/pipeline:$PWD/eval:$PWD/query
PY=<主仓>/.venv/bin/python
# 装配(已有产物在 tools/doc_test/out/):curate → classify → bootstrap_dicts → stage_corpus → gen_manifest
$PY -m pipeline.cli up                          # 隔离栈 + 灌 demo 字典
$PY -m pipeline.cli ingest tools/doc_test/out/batch -m tools/doc_test/out/manifest_ext.xlsx   # 外规先
$PY -m pipeline.cli meta confirm --batch <bid>  # 放行冲突
# … 案例同理(manifest_case.xlsx,case_l2 开)
$PY -c "from query.cli import app; app()" ask "<问句>" --indent   # 查询节点
```

---

## 8. 待办

- R1 主答 prose 偏中性模板(受引用约束),确认是否真走 pro 链路(若想更丰富答复)。
- 36 QC_FAILED:接 DeepDoc/OCR 提升复杂文档条款级覆盖;扩样本提升外规/T2.1 覆盖。
- 3 个 main PR 交 Codex 审 → 跟修闭环。
- 字典值待甲方评审转正(v0-draft-demo → 正式 dict_version)。
