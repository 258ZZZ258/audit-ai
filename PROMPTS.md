# PROMPTS

本文件集中存放管线所用 LLM 提示词(既定约定)。

**M1 默认零 LLM 调用** —— 本文件存在仅作占位与契约声明:仅当 `config/settings.toml` 的
`[toggles] l2_enabled = true` 时,S4 元数据 L2(业务域/摘要辅助)才会启用并使用以下提示词。
关闭时业务域取 manifest 声明值,代码路径不变(生产期切网关 endpoint,见 SPEC §决策)。

## L2 业务域辅助(l2_enabled 时启用)

> 待 L2 回迁时填充。

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

代码以 `query/query/judge/review.py` `_supported(content, citations, llm)` 内联拼装,模板如下
(`<refs>` = 各 citation `《doc_title》clause_path` 以 `;` 连接)。

### system

```
你是引用忠实性复核助手。判断给定表述是否被所引条款支持,只回 JSON {"supported": true 或 false}。
```

### user

```
表述:<content>
所引条款:<refs>
该表述是否被所引条款支持?
```
