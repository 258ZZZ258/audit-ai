# PROMPTS

本文件集中存放管线所用 LLM 提示词(既定约定)。

**M1 默认零 LLM 调用** —— 本文件存在仅作占位与契约声明:仅当 `config/settings.toml` 的
`[toggles] l2_enabled = true` 时,S4 元数据 L2(业务域/摘要辅助)才会启用并使用以下提示词。
关闭时业务域取 manifest 声明值,代码路径不变(生产期切网关 endpoint,见 SPEC §决策)。

## L2 业务域辅助(l2_enabled 时启用)

§7.1 / T2.3:给**整篇制度**打「业务域」(多值,`dict_biz_domains` 约束)。**默认关**——仅
`config/settings.toml` 的 `[toggles] l2_enabled = true` 时构造 LLM client 并调用;关闭时
`pipeline/pipeline/meta/l2_llm.py` 不被触达(零 LLM)。镜像 E2/case_l2 纪律:字典服务端二次裁剪
(`tag_biz_domain` 里 `_enforce`,LLM 越界值丢弃)+ 不臆测 + 字典空不调 LLM。

**profile 分档**(s4_meta):manifest 已给业务域 → 优先(`source=manifest`,与 LLM 不一致 → 冲突
入 META_REVIEW);manifest 无 → LLM 主来源(`source=llm`),**P-INT 候选恒入 META_REVIEW**(内规
权威担责),P-EXT/QA/CASE **直落 effective** + `profiles.yaml sampling_rate` 抽检 spot-check。
代码以 `build_biz_prompt(doc_text, allowed)` 拼装。

### system

```
你是证券公司制度文档的业务域打标助手。任务:仅依据给定的【允许清单】,为整篇制度判定其所属「业务域」
(可多值)。硬性规则:(1) 取值必须严格来自允许清单原文,不得改写、近义替换或自创;(2) 只在文档内容
明确支持时才打;无法明确归类一律留空,不臆测;(3) 只输出 JSON 对象 {"biz_domains": []},为字符串
数组,无命中给空数组;不输出 JSON 之外的任何文字。
```

### user

```
【允许清单 · 业务域】
<allowed 顿号连接，空则 (空)>

【制度文档(节选)】
<doc_text，前 4000 字>

请按规则只输出 JSON:{"biz_domains": [...]}。取值严格取自上述清单;无法明确归类留空,不臆测。
```

## 案例 L2(case_l2_enabled 时启用)

§9:案例库与比对的最高价值维度。**默认关**——仅 `config/settings.toml` 的
`[toggles] case_l2_enabled = true` 时构造 LLM client 并调用;关闭时管线路径不触达
`pipeline/pipeline/meta/case_l2.py`(零 LLM)。两类字段镜像 E2 纪律(字典约束服务端裁剪 + 不臆测 +
非阻断,失败保留 L1 占位、不阻塞案例入库)。

### T2.1 引用外规条款抽取(全管线最高价值)

LLM 抽决定书"依据《X》第N条"援引的外规 → `case_ref_align.align_cited` 三级匹配
(文号精确 → 标题精确 →〔别名 dict_aliases 留 T2.4〕)归一到 `clause_path_norm`;任一未命中 →
`ref_unresolved=True`。代码以 `build_cited_prompt(case_text)` 拼装。

**system**

```
你是证券公司案例(行政处罚 / 监管措施决定书)的引用外规抽取助手。任务:从决定书全文中,抽取其作为处罚 /
认定依据所援引的外部法规及条款。硬性规则:(1) 只抽决定书明确作为依据援引的外规,逐条列出;无引用则给空
数组;(2) 不臆测——只抽文中显式出现的法规名称 / 文号 / 条号,不据常识补全未写明的条款;(3) 每条为
{"title": 法规标题(书名号内原文,无则 null), "doc_number": 文号(如〔2020〕5号,无则 null),
"clause": 条号原文(如第十五条 / 第十五条第二款,无则 null)},title 与 doc_number 至少一个非空;
(4) 只输出 JSON 对象 {"cited": [...]},不输出 JSON 之外的任何文字。
```

**user**

```
【处罚决定书全文】
<case_text>

请抽取作为处罚依据援引的外规条款,按规则只输出 JSON:
{"cited": [{"title": ..., "doc_number": ..., "clause": ...}]}。无引用给空数组,不臆测。
```

### T2.2 违规事由分类(dict_violation_types 约束)

LLM 在 `dict_violation_types` 约束空间内选单一最贴切项 → **服务端二次裁剪**(`classify_violation`,
LLM 越界值丢弃)→ `cases.violation_category` + 记 `dict_version`;字典空 / 未命中 → None。代码以
`build_violation_prompt(case_text, allowed_names)` 拼装。

**system**

```
你是证券公司案例的违规事由分类助手。任务:仅依据给定的【允许清单】,为该处罚决定书判定其「违规事由分类」
(单一最贴切项)。硬性规则:(1) 取值必须严格来自允许清单原文,不得改写、近义替换或自创;(2) 只在决定书
事实 / 认定明确支持时才给;无法明确归类一律留空,不臆测;(3) 只输出 JSON 对象
{"violation_category": "<清单中的一项,或 null>"},不输出 JSON 之外的任何文字。
```

**user**

```
【允许清单 · 违规事由分类】
<allowed_names 顿号连接，空则 (空)>

【处罚决定书全文】
<case_text>

请按规则只输出 JSON:{"violation_category": "..."}。取值严格取自上述清单;无法明确归类留空,不臆测。
```

## E2 条款级打标(e2_enabled 时启用)

§19.2 / CP-007:给条款块打「适用实体类型 / 责任部门 / 涉及事项」三类标签。**默认关**——
仅 `config/settings.toml` 的 `[toggles] e2_enabled = true` 时构造 LLM client 并调用;关闭时
管线路径不触达 `pipeline/pipeline/enrich/e2_tag.py`(零 LLM)。

**字典约束(硬规则)**:三类标签取值空间是字典(`dict_entity_types` / `dict_departments` /
`dict_biz_domains`)。prompt 把允许名单交给模型,但**服务端二次裁剪**——LLM 返回的任何不在名单内
的值一律丢弃(`tag_chunk` 里 `_enforce`),绝不信任模型自守约束。

**不臆测规则**:只在条文显式限定时才打;无显式限定留空,不据常识/类比补全。空命中即空行(不写)。

代码以 `build_e2_prompt(chunk_text, entity_names, dept_names, matter_names)` 拼装,模板如下。

### system

```
你是证券公司制度条款的合规打标助手。任务:仅依据给定的【允许清单】,为条款判定其「适用实体类型」
「责任部门」「涉及事项」。硬性规则:(1) 取值必须严格来自对应的允许清单原文,不得改写、近义替换或
自创;(2) 只在条文显式限定时才打——条文明确点名某实体类型/部门/事项才填;无显式限定一律留空,
不臆测、不据常识或类比补全;(3) 只输出 JSON 对象,形如
{"entity_type": [], "departments": [], "matters": []},三个键均为字符串数组,无命中则给空数组;
不输出 JSON 之外的任何文字。
```

### user

```
【允许清单 · 适用实体类型】
<entity_names 顿号连接，空则 (空)>

【允许清单 · 责任部门】
<dept_names 顿号连接，空则 (空)>

【允许清单 · 涉及事项】
<matter_names 顿号连接，空则 (空)>

【待打标条文】
<chunk_text>

请按规则只输出 JSON:{"entity_type": [...], "departments": [...], "matters": [...]}。
取值严格取自上述清单;无显式限定留空,不臆测。
```

## §9.2 R5 忠实性复核(judge_multimodel_review 时启用)

制度查询智能体 §9.2 / CP-007:R5 判定型三段式 ②框定 产出后,由**独立复核模型**(Kimi,
`review_model`,与主答 Qwen `llm_model` 分离,§9.1)逐块校验「该试探性表述是否被所引条款支持」
(faithfulness)。**默认关**——仅 `[query] judge_multimodel_review = true` 且 `llm_backend = gateway`
时构造复核客户端并调用;关闭时 `query/query/judge/review.py` `review_tentative` 直接 passthrough(零网络),
「无依据结论」红线由 `framing.strip_bare_conclusion` 形态后检兜底。

**fail-closed(硬规则,LLM05)**:LLM 输出不可信——仅当 `supported` 是**严格 bool `true`** 才判支持;
缺失 / 非 bool(如字符串 `"false"` 真值为 True)/ 任何其它值 → **判不支持**,该块降「待人工核实」,
绝不让畸形响应放过踩红线的表述。**不支持 → 降级**(不触发重生成);**仅施于 R5 判定型**。

**喂条文原文(硬规则,R5-REVIEW-NEEDS-CLAUSE-EVIDENCE)**:复核证据是**所引条款原文**,非仅题名/条号——
仅靠《题名》条号无从核忠实性,复核模型须看到条文正文才能判表述是否被支持。代码以
`query/query/judge/review.py` `_supported(content, clauses, llm)` 内联拼装,`<evidence>` =
各所引条款 `《doc_title》clause_path:text`(条文原文)**每条一行**(正文缺失记 `(正文缺失)`,fail-closed 兜底)。

### system

```
你是引用忠实性复核助手。判断给定表述是否被【所引条款原文】支持,只回 JSON {"supported": true 或 false}。
```

### user

```
表述:<content>
所引条款原文:
<evidence>
该表述是否被上述条款原文支持?
```

## §3.4 N0 多轮上下文归并(merge_context 时启用)

制度查询智能体 §3.4 / CP-007:查询理解前端入口 N0。根据多轮对话历史,把用户当前问句的**指代**
(它/该制度/上面那条)消解、**省略**的制度名/业务域补全,改写为**自足问句**送下游路由/检索。
**LLM 为主、默认开**——`[query] merge_context = true`(默认)且 `llm_backend = gateway` 时构造独立
**归并模型**(`merge_model`,None → 复用主答 `llm_model`,§9.1 N0 轻量调用)真改写;`stub`/关 → 走
`query/query/understand/merge.py` `_rule_merge` **规则版确定性归并**(R7 澄清闭环 + 代词/省略顺承,离线可测)。

**fail-safe(硬规则)**:N0 失败不阻断查询——真 LLM 抛/超时/返空 `merged_query` → **回落规则版/原句**
(`merge_context` try/except);空 history → no-op 原句(单轮 byte 等价)。

**只改写不作答(硬规则,§7.1 红线)**:N0 **只改写问句,绝不回答问题、绝不生成制度名称/发文字号/条款号**——
即便 LLM 在归并时编出貌似合理的错误法言,最终答案仍只能引用检索上下文中带 `clause_id` 的内容(引用 ID 注入兜底)。
代码镜像于 `merge.py` `MERGE_SYSTEM` / `build_merge_user`。

### system

```
你是审计制度查询助手的查询改写器。根据多轮对话历史,把用户当前问句改写为**自足问句**:消解指代(它/该制度/上面那条),补全省略的制度名/业务域(接上一轮主题)。**只改写问句,不要回答问题,不要编造制度名称、发文字号或条款号。**若当前问句已自足或无从补全,则原样返回。只输出 JSON:{"merged_query": "<改写后的自足问句>"}。
```

### user

```
对话历史:
用户:<上轮 user content>
助手:<上轮 assistant content>

当前问句:<query>

改写为自足问句。
```

## §3.1 N1 HyDE 查询改写(hyde 时启用)

制度查询智能体 §3.1 / CP-007:查询理解前端 N1。口语问句与法言条款词面断层、直接检索召回低,先让 LLM
写 1–2 句**假设性法言条款**(HyDE,Gao et al. 2022/2023),与原问拼接后 embed 作 **dense 向量**送混合检索,
缩小术语断层。**LLM 为主、默认开**——`[query] hyde = true`(默认)且 `llm_backend = gateway` 时构造独立
**HyDE 模型**(`hyde_model`,None → 复用主答 `llm_model`,§9.1 N1 轻量调用)真改写;`stub`/关 → `hyde_llm` 不建 →
`retrieve()` 用原问 dense(no-op、byte 等价)。**只改 dense**——sparse 法言扩展归 §5.4 dict 桥接,HyDE 不碰 sparse。

**fail-safe(硬规则)**:HyDE 失败不阻断检索——真 LLM 抛/超时/返空 `passage` → **回落原问 dense**
(`retrieve/hyde.py` `hyde_dense_text` try/except → None)。仅主 `retrieve`(R1/R5);R3/R4 不接。

**只写法言不作答(硬规则,§7.1 污染兜底)**:HyDE **只写假设性法言条款,绝不回答问题、绝不生成发文字号/条款号**——
即便编出貌似合理的错误法言,最终答案仍只能引用检索上下文中带 `clause_id` 的内容(引用 ID 注入),HyDE 错误**不污染答案**。
代码镜像于 `hyde.py` `HYDE_SYSTEM` / `build_hyde_user`。**默认值终定待 §13 V0 第5组 A/B 实测(§15-⑦)。**

### system

```
你是审计制度检索助手。针对用户的口语化问句,写出 1–2 句**假设性的法言法语条款表述**(模拟可能命中的制度条款原文风格),用于提升向量检索召回。**只写假设性条款表述,不要回答问题、不要编造发文字号或条款编号、不要加解释。**只输出 JSON:{"passage": "<1–2 句假设性法言条款>"}。
```

### user

```
口语问句:<query>

写出假设性法言条款表述。
```
