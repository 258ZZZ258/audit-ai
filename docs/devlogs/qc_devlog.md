# 质检层 devlog(pipeline/pipeline/qc)

**职责**:S2 七指标硬关卡(`indicators.py`)+ `gate.py`(阈值 + edge band 从 `config/qc_thresholds.yaml`)+ evidence。任一不达标 → QC_FAILED(E301),写失败指标 + 定位证据进补录队列。

## 关键决策 / 踩坑
- **边缘带退化(B5)**:edge band(阈值±ε 升级人工抽检)对两类指标会**误标完美文档**——阈值=可达极值的(页码锚点=100%)、阈值在 ε 内的(文本乱码 0.01<ε 0.02)。**这两个指标关掉边缘带**。
- **指标 3 `hierarchy_legality` 误报插入条(检查点 D 发现 1)**:原要求同级条号严格递增,`_base("第四条之一")`=4 与前面 `第四条`=4 相等 → 误判违规,把合法插入条(解析器明确支持)QC 误杀。**修**:改用 `_key(num)` **变长整数元组**键(`"4-1"`→(4,1) > `"4"`→(4,))做 `k <= last` 比较——插入条不误判、真重复/逆序仍被抓;`clause_continuity` 仍用 `_base`(首段)。回归测试 `test_inserted_clause_not_flagged_by_hierarchy` + `test_hierarchy_catches_duplicate_clause`。

- **指标 7 抽取充分性从 P-QA/P-CASE 移除(V16)**:它量的是**页间密度均匀度**、假定"制度满版页",对短/不均的非制度件(问答、案例)会误伤 → 按 `corpus_type` 选指标集(`indicators_for`),制度七项不变。非制度 profile 另有 **P-QA 问答对完整率 / P-CASE cases 字段完整率**,是**批次度量、非 s2 拦截**(故案例件易自动放行)。

> 注:指标 1/2(条款覆盖/连续性)的真实外规失败根因在**下游 clause_tree**(跨法引用碎片、小数编号),见 `../chunking/structuring_devlog.md`;与质检指标本身无关。
> 时间轴:`docs/devlog.md` 阶段 B(B5)、检查点 D 走查(发现 1)。
