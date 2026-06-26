# 元数据 / 版本链 devlog(pipeline/pipeline/meta)

**职责**:S4 = L1 规则元数据抽取 + manifest 交叉校验(`l1_rules.py`)+ 版本关系解析(`version_chain.py`)。s4_meta 决定 META_REVIEW 终态。

## 关键决策 / 踩坑
- **L1 抽取 + 交叉校验(C2)**:抽发文字号 / 成文日期 / 发文机关(字典)/ 标题,与 manifest 比对——**冲突 = L1 候选非空且 manifest 非空值(归一后)不在候选中**。日期用成员判定,文号统一中西括号变体。**踩坑**:文号/日期须**逐块**匹配——拼接 head 块后 `strip_ws` 粘连标题,文号正则的贪婪机构前缀会吃进标题。
- **`version_chain`(C3)**:`supersedes` 编码 → 关系(空/单文件 `revise_replace`、`abolish:` `abolish_only`、多文件 `merge`;`split`=批次内 ≥2 新件指同一旧件)。revise 继承 logical_id、abolish 新 logical + 记被废止版、merge/split 登记 + 入 meta_confirm 队列「demo 不支持」。原子切换在 `finalize`(见 `../index/index_devlog.md` D1)。

## META_REVIEW 双模式(阶段 W,设计决策)
闸的本意**不是抓冲突,是权威边界担责**——"谁把这篇放进 effective 语料"须落 `pipeline_events` 具名 actor;且 **"无冲突"≠"正确"**(L1 只比两来源一致性,不验 manifest 本身对不对)。
- **A 模式**(默认,`auto_confirm_meta_no_conflict` 关):全件入 meta_confirm 闸。
- **B-严**(开关开,settings.toml 设 true):无冲突**全新件**直通 EMBEDDING;**冲突件 + 带 `supersedes_version_id` 的修订件**(supersede 旧版=最有后果的权威变更)仍入闸。s4 判据:`not conflicts and toggle and not dv.supersedes_version_id`。
- B 模式的**驱动正确性 bug**(strand-at-EMBEDDING)详见 `../orchestration_devlog.md` / `../web/web_devlog.md`。

## P0 Phase 2:案例 L2 LLM 富集(T2.1 引用外规 + T2.2 违规事由,2026-06-26;PR #20)

**背景**:案例库 §9 的两个最高价值字段在 L1 仅留占位(`cited_regulations=[]` / `violation_category=None`),T2.1/T2.2 接真 LLM 把它们补齐。新模块 `meta/case_l2.py`(默认关 `case_l2_enabled`)。

**镜像 E2 纪律(见 `enrich_devlog.md` / `enrich/e2_tag.py`)**:字典约束服务端二次裁剪(never trust LLM)+ 不臆测 + 富集无状态机阻断权(`apply` 吞一切异常)+ 默认关零 LLM。

**T2.1 引用外规 + 归一对齐**:
- `extract_cited(client, case_text)` → `[{title, doc_number?, clause?}]`(`chat_json`,只输出 `{"cited":[...]}`;无 title 也无 doc_number 的项丢弃 = 无对齐锚点)。
- `PgRegLookup`(实现 T1.2 `case_ref_align.RegLookup`,docstring 早标"生产=PG 查询见 T2.1"):按文号精确 → 标题精确命中 **effective** 外规,聚合其 chunk 的 `clause_path_norm` 成 frozenset 供超界校验。
- 装配 `l2_fields` → `align_cited`(复用 T1.2 三级匹配 + 条号归一)→ 写 `cases.cited_regulations`(JSONB,单条 `{doc_no, title, clause_path_norm, resolved}`);任一 miss → **置 `ref_unresolved=True` 标记**,不阻塞案例入库(低优补录队列消费待 quality_tickets 建表 §18.3,**本阶段仅置标记不入队**)。

**T2.2 违规事由分类**:`classify_violation(client, case_text, allowed)` LLM 单值 + 服务端裁 `dict_violation_types`;**字典空 → 不调 LLM 直接 None**(consumed-when-present);越界/未命中 → None。

**踩坑 / 决策**:
- **dict_version 持久化(超 TASKS 文件范围,生产保真)**:`cases` 无 evidence 列,T2.2 要求"dict_version 记入"→ add-only 加 `cases.violation_category_dict_version`(迁移 0011),案例侧落为 typed 列(对应 E2 把 dict_version 写 `clause_tags.evidence`)。
- **迁移 revision id ≤ 32 字符**:`alembic_version.version_num` 是 `VARCHAR(32)`,初版 id `0011_cases_violation_dict_version`(33)撞 `StringDataRightTruncation`(事务性 DDL 整体回滚,无残留)→ 收窄为 `0011_cases_violation_dictver`(28)。**后续命名迁移注意**。
- **非阻断边界**:case L2 在 `s4_meta._extract_case` 内调(非 cli 装配层),故 try/except 落在 `case_l2.apply` 自身,失败保留 L1 占位、不失败 STRUCTURING stage。

**测试**(`test_case_l2.py`):14 纯单元(prompt/裁剪/降级/对齐/非阻断)+ 真栈 fake-LLM 集成(真 `PgRegLookup` + 真 dict 加载,无需 key)+ 门控真模型(有 `OPENAI_API_KEY` 才跑)。

**Codex 复审闭环(3 warning,全采纳)**:
- **CITED-REGULATIONS-SHAPE**:`cited_regulations` 单条目键 `doc_number` → **`doc_no`**,对齐 query 反查消费者(`query/case/bridge.py`、`query/judge/r5_judgment.py` 读 `doc_no` + `clause_path_norm`);源头改 `case_ref_align._row`(Phase 1 文件)。加跨模块契约回归 `query/tests/test_cited_regulations_bridge_contract.py`(case_l2 产出喂 bridge/r5)。
- **REGLOOKUP-CORPUS-SCOPE**:`PgRegLookup` join `Document` 钉死 `corpus_type="P-EXT"`——案例引的是外规,同文号/同标题的内规(P-INT)/案例(P-CASE)不得被当外规条款落库污染反查。加 `test_reglookup_scopes_to_p_ext_only`(同号 P-INT/P-EXT 各一,验只取 P-EXT)。
- **UNRESOLVED-QUEUE**:docstring「进低优队列」收窄为**仅置 `ref_unresolved` 标记**(队列消费 quality_tickets deferred,§18.3),不夸大未建的工作流。

## P0 Phase 2(续):业务域 L2 + profile 分档(T2.3a/T2.3b,2026-06-26;PR 待开)

**背景**:§7.1 L2 业务域多值打标(L-3,最后一个 P0 LLM 触点)。新模块 `meta/l2_llm.py`(默认关 `l2_enabled`),完成 **P0 LLM 4 触点全清**(E2 / 案例引用外规 / 违规事由 / L2 业务域)。

**T2.3a 打标**:`tag_biz_domain(client, doc_text, allowed)` LLM + 服务端裁 `dict_biz_domains`(镜像 E2/case_l2:不臆测 + 字典空不调 LLM)。`dict_biz_domains` 无 dict_version 列 → provenance 落 `biz_domain_source` 标志(不另记版本)。

**T2.3b profile 分档**(核心,**纯逻辑 `biz_l2_decision` + 确定性抽检 `_sampled`**,免栈 8 单测穷举):
- **manifest 优先**:`dv.biz_domain`(单值)有 → 权威用 manifest(`source=manifest`);LLM 不一致 → 冲突 → META_REVIEW(§7.1 交叉校验)。
- **manifest 无 → LLM 主来源**(`source=llm`):**P-INT 候选恒入 META_REVIEW**(内规权威担责,即便 auto_confirm 开);P-EXT/QA/CASE **直落 effective** + `profiles.yaml sampling_rate` 确定性抽检 spot-check。
- 写权威字段经新 `pg_io.set_biz_domains(dvid, biz_domains, source)`;`s4_meta._safe_biz_l2` 非阻断(LLM 失败吞掉,不写不复核)。biz_review 并入自动放行判据(`not conflicts and not biz_review and auto_confirm and not supersedes`)。

**下游取值**(`corpus_rows.build_rows`):Milvus `biz_domain` ARRAY 优先 `dv.biz_domains`(L2 多值),空则**回落 manifest 原单值** `dv.biz_domain`(向后兼容,默认路径 biz_domains 为 None → 行为不变)。

**决策 / 踩坑**:
- **sampling_rate 语义**(`profiles.yaml` T2.3b 起消费):直落 profile 中额外抽 META_REVIEW spot-check 的比例;P-INT 由 profile 分档恒入闸(sampling 无关)。默认 P-EXT/QA/CASE=**0.0**(纯直落),避免默认把外规全挡回复核;机制由单测(rate=1.0/0.5/0)证明。**确定性抽检**(sha1(dvid) 落点 < rate,非随机)使重跑/测试可复现。
- 默认 `l2_enabled=false` → s4_meta 不触达本路径,既有 default-path 集成测(test_b_mode 等)不受扰。

**测试**:`test_l2_llm.py`(13:打标裁字典 + biz_l2_decision 穷举 + _sampled)+ `test_corpus_rows_biz.py`(3:下游取值/回落)+ `test_s4_meta.py`(3 真栈:P-INT 候选入闸 / P-EXT 直落 / manifest 冲突优先 manifest)。

> 时间轴:`docs/devlog.md` 阶段 C(C2/C3)、阶段 W(双模式)、阶段 P0 Phase 2。
