# 结构化层 devlog(pipeline/pipeline/chunking)

**职责**:S3 = 条款树构建 + 切块。`normalize.py`(中文数字/条款号归一)· `clause_tree.py`(七类节点建树)· `chunker.py`(六规则 + 确定性 chunk_id 调用)。s3_structure 是薄装配(`stages/s3_structure.py`)。

## normalize / clause_tree
- **L1 normalize**:中文数字→int;条款号→规范形(`之一`/bis/小数式统一 `N-K`);全半角 + 去空白。
- **L2 clause_tree**:七类节点正则、栈式建树、虚拟根、`clause_path(_norm)`、`internal_refs`。**bug**:`第X条之一` 的 `之一` 在「条」**之后**,初版 refs 正则写反。bis/.1b 经 `_ART_NUM` 接通(normalize 早支持、classify 入口够不着)。
- **做全小数规则(检查点 D 发现 2,根因在 IR 边界下游、与换 DeepDoc 无关)**:
  - **跨法引用过滤**:`第X条` 紧跟枚举标点 `、，,;；`(`_REF_PUNCT`)判引用列举、非条标题(否则 `…第一百九十六条、依照《证券法》…` 碎片落块首被当条标题撑假缺口)。
  - **小数编号**(交易所规则 `2.17`/`3.1.2`,章[.节].条):classify 加小数分支——号后**强制空白**避 `2.17%`/`1.5亿`,`(?!条)` 排 `10.1.3 条…` 引用碎片,号取**全小数**保排序;`_key` 改**变长元组**(`10.1.3`→(10,1,3))跨节排序正确。ext_sse 0→401 条。
  - **目录剥离(阶段 W 区域化)**:逐行正则不普适 → 改**区域级预扫 `_toc_block_indices`**(目录锚 / ≥4 连续点引导符 / 末尾连续 ≥3 行页码簇),统一覆盖 章/节/条/小数;`classify_heading` 回归纯单行。**scheme A**:命中块留 root body、不当标题(chunker 只切节/条,根 body 不入 chunk)。golden F1 不回归。

## chunker(六规则 + chunk_id)
- 原子=条;超长按款拆 + **条头续接**;超短独立;父块=节级仅 PG;表格独立块;**面包屑前缀**(合成 `章 > 条` 路径,T4 回放须剥它)。
- **`target_token_min`(决策 8)**:原是死参 → 实现**条内尾块合并**(尾组 <min 并回前组,仅同条内)。
- **单段超长(决策 10)**:语义边界(项（N）/句末；。)拆 + 字符硬切兜底(标 `oversize`);`token_count` 改**量内容**(不含面包屑/条头续接,使「≤target_max」为干净不变量)。
- **C1 s3**:载 IR → `build_chunks` → `pg_io.replace_chunks`(同事务删旧插新,确定性 id 重跑幂等)。chunk_status=staging;父/表格块仅 PG;`oversize` 落库(迁移 0004)。

> chunk_id 公式本体是契约,在 `libs/common`(见 `../../../libs/common/contracts_devlog.md`)。
> 时间轴:`docs/devlog.md` 并行流 L(L1/L2/L3)、阶段 C(C1)、检查点 D(发现 2)、阶段 W(目录区域化)。
