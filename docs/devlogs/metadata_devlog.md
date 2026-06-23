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

> 时间轴:`docs/devlog.md` 阶段 C(C2/C3)、阶段 W(双模式)。
