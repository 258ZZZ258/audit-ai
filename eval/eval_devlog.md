# 验证套件 devlog(eval/eval)

**职责**:demo 差异化卖点——`smoke`(T2)· `anchor_replay`(T4)· `reconcile` · `rebuild` · `idempotency` · `report`。**对终态无阻断权**(只写报告,生产 §21.2)。依赖 `pipeline`(用 StageContext/MilvusIO/corpus_rows)→ `eval → pipeline → common`。

## 组件 / 踩坑
- **T4 anchor_replay(V3)**:逐非 parent chunk 在原件页 `[page_start-W..page_end+W]`(复用 `rendition.page_texts`)精确子串 / rapidfuzz≥阈值定位;**is_table/degraded 豁免**;chunk 文本须**剥面包屑**再比(面包屑是合成路径、原页无)。
- **T2 smoke(V7)**:合成查询 = 标题 + 首条款前 N 字 → search(topk=hit_at);断言 hit@N + `SearchResult.expr` 含 `status=="effective"` 过滤位(E801/E802)。**须排除 superseded 件**(旧版默认检索不可见,测它必 E801 误报)→ `_indexed_dvids(effective_only=True)`;**replay 不排除**(旧版锚点不变仍可回放)。
- **reconcile**:逐 doc PG 块数 vs `MilvusIO.count(dvid)`(query-by-PK 准确,**非**虚高 `num_entities`);不平 E701 + 冷备重灌。**rebuild(V6)**:drop collection → 从冷备零编码全量回灌(纯 insert,count 干净)。两者复用 `corpus_rows.rows_from_cold`。
- **idempotency(V5,D3)**:幂等根 = s0 SHA 去重;二次 register 前后断言 chunk_id 集合 + Milvus `num_entities` 不变 + ≥1 dup 留痕。**免模型**(不重嵌入)。
- **report(D4)**:纯 PG 聚合(解析成功率 / QC 一次通过率 / 状态计数 / 锚点填充率 / retrieval_mode + M3 义务覆盖/队列/版本链/按语料);**不加载模型**;比率分母 0→None;e1 关→义务覆盖 None。

## 设计转折(M2 C1/C2)
report 初版**现场跑 smoke** → 无模型时触发模型加载/联网卡住。改为 **finalize 在 INDEXED 跑 T2/T4 并留痕 `pipeline_events.detail['verify']`(§9),report 只聚合读取**(绝不在 report 加载模型)。cli `_advance_one` 钩子改为**所有** INDEXED 件都调 finalize。

## 升格(Step 4)
`verify/` → `eval/eval/`;eval 模块内部只 import `pipeline.*`+`common.*`(无 verify 互引)→ 搬后零内部改动。**断 `pipeline⇄eval` 环用懒导入**:cli/web/finalize 对 eval 改**函数级懒导入**(`import pipeline.*` 零拉入 eval,实测);`test_finalize_verify` 的 monkeypatch 目标 `pipeline.verify.*` → `eval.*`(懒导入下 patch 源模块属性仍生效)。
另:`_advance_one` 静默 exit 0 修复(M2 审查)——回带 error、`_approve_doc` 返 bool、未达 INDEXED 非零退出。

> 时间轴:`docs/devlog.md` 阶段 M2(T2/T4/reconcile/rebuild/golden/finalize 转折)、阶段 D(D3/D4)、升格 Step 4。
