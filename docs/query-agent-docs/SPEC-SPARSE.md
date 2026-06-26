# Spec: §5.4 sparse 精确通道(发文字号提权 + 词典扩展 dict_scenario_terms)

> 状态:**Phase 1 / SPECIFY —— 待人工复核批准**。属 GAP.md P1(§3 检索与重排,#5)。八路收官 + §5.5 重排后
> **第二个横切检索增强**(惠及 R1/R5)。延续 MVP 范式(接缝/默认零网络/**默认 byte 等价**/consumed-when-present)。
> 上游设计:`制度查询智能体_技术框架设计_v1_0.md` §5.4(L228/249)/ §5.1(L225)/ §3.2(L167–175)/ §2.1(L133)。
> 本文件只述 §5.4 增量。
>
> **已决(2026-06-26,AskUserQuestion):**
> 1. **范围** = 发文字号提权 **+** 词典扩展(新建 `seeds/dict_scenario_terms.csv` **v0-draft**,consumed-when-present)。
> 2. **提权机制** = **查询层 sparse token 提权**(检测 span → 重 embed → 按系数并入 query sparse;**保持 `RRFRanker`、零 pipeline 改动**)。
> 3. **应用范围** = **主 hybrid `retrieve`(R1/R5)**;R4 枚举 / R2/R3/R6 不接。

## 0. 切片边界

| | 范围 |
|---|---|
| **做** | **§5.4 查询层 sparse 增强**:主 hybrid `retrieve` 内,在 `embed(query)` 之后、`milvus.search` 之前,对 **query sparse 向量**做两路增强 ——(A)**发文字号提权**:regex 检测查询中的发文字号 / 制度全名 span → 对 span 重 embed 取其 `lexical_weights` → 按 `docnum_boost_factor` **加权并入** query sparse(放大精确 token);(B)**词典扩展**:`dict_scenario_terms`(口语→法言)子串匹配查询 → 对映射出的法言词 embed → 按 `scenario_expand_factor` **并入** query sparse(扩命中面)。新增 `query/query/retrieve/sparse_boost.py`(检测 regex + dict loader + `augment_sparse`)。新增 `seeds/dict_scenario_terms.csv`(**v0-draft 待 §15⑥ 评审**)。`config` +`docnum_boost`/`scenario_expand`(bool,**默认 False**)+ 两系数 + `scenario_terms_path`。**两开关默认关 → `augment_sparse` 不调用 → query sparse 原样 → byte 等价**(不回归 R1/R3/R4/R5/R6)。开关开但无命中(无发文字号 / dict 空或无匹配)→ 增强为空集 → **仍 byte 等价**。dict **consumed-when-present**(文件缺 / 空 → 扩展为空)。 |
| **不做** | **Milvus `WeightedRanker` 通道重权**(决策弃:RRF 基于秩、字面"通道提权"需切 WeightedRanker,但 Milvus 2.4 为原始加权和、COSINE/IP 量级失配易被 sparse 主导 —— 改走查询层 token 提权达成等效)。**检索后分数提权 / 给 Candidate·Milvus 加 `doc_number`**(决策弃,需扩 schema)。**dense 侧改写 / HyDE**(§3.1 / N1,另路,本切片只动 sparse)。**`dict_scenario_terms` 建 PG 表 + alembic + `demo up` 灌库**(GAP #11,另切片;本切片仅查询层读 CSV)。**提权应用于 R4 枚举 / R2/R3/R6**。**系数 V0 标定**(§15,默认占位,不对甲方承诺)。**`dict_intent_routes` / N2 桥接重构**(§4.1,另路)。**生产 embedding 网关双输出 endpoint**(§15②;本地 BGE-M3 已 dense+sparse 双输出,非本切片阻塞)。 |

## 1. Objective

把"裸 query 的 sparse 向量"升级为 **查询层 sparse 精确增强**(§5.4):**精确编号问句**(发文字号 / 制度全名)
经 token 提权使精确匹配 chunk 在 sparse 排名上升、经 RRF 浮顶;**口语问句**经 `dict_scenario_terms` 法言扩展
拓宽 sparse 命中面 —— 提升 R1 依据 / R5 判定对法规专有名词(发文字号、罚则编号、制度全名)的精确召回。

成功 = `docnum_boost=True` 时含发文字号的查询里,目标编号 chunk 的检索名次**较增强前上升**;`scenario_expand=True`
+ 非空 dict 时,口语查询能召回仅含法言词的 chunk(增强前漏);**两开关默认关(False)与本轮前 byte 等价**(不回归);
**保持 Milvus `RRFRanker`、零 pipeline 改动**;增强**零 LLM**(regex + dict 子串)、**只动 sparse 不动 dense**、
**仅施于主 `retrieve`(R1/R5)**。

## 2. Tech Stack(增量)

- 复用 `query/`:`config`(加字段)/ `retrieve.hybrid`(`Retriever.retrieve` / `Candidate`)/ `embedding`
  接缝(`self._embed.embed`,已可批量取 `Embedding.sparse = lexical_weights`)。
- 复用 `pipeline`:`milvus_io.search(dense, sparse, …)` **签名不变**(传入增强后的 sparse 即可,**零 pipeline 改动**)。
- 复用 `pipeline.chunking.normalize`(`to_halfwidth` / `strip_ws`)做发文字号 / 全名归一(全角〔〕()→半角)。
- 新增 `query/query/retrieve/sparse_boost.py`:`detect_doc_numbers(q)`(regex)+ `load_scenario_terms(path)`(CSV→dict,
  缺→{})+ `augment_sparse(query, base_sparse, *, embed, scenario_terms, docnum_factor, expand_factor, docnum_on, expand_on)`。
- 新增 `seeds/dict_scenario_terms.csv`(列 `oral_term,legal_terms`;`legal_terms` 以 `|` 分隔;**v0-draft 待 §15⑥**)。
- **零新依赖、默认零增强(双开关关)、零网络**(增强复用本地 BGE-M3,无外呼;dict 为本地 CSV)。

## 3. Commands

```bash
demo up                                                    # 集成需 PG+Milvus+BGE-M3
# 发文字号提权:
QUERY_DOCNUM_BOOST=1 demo search "银保监发〔2021〕5号 的处罚标准"
# 词典扩展:
QUERY_SCENARIO_EXPAND=1 demo search "代客理财违规吗"
.venv/bin/python -m pytest query/tests/test_sparse_boost.py \
  query/tests/test_sparse_boost_integration.py -q
.venv/bin/ruff check .
```

## 4. Project Structure(增量)

```
query/query/retrieve/
  sparse_boost.py   # detect_doc_numbers(regex) + load_scenario_terms(csv→dict,缺→{}) + augment_sparse(...)
  hybrid.py         # retrieve:docnum/expand 开 → augment_sparse(emb.sparse) → search;默认关 byte 等价
query/query/config.py
  # + docnum_boost: bool=False (env QUERY_DOCNUM_BOOST) + docnum_boost_factor: float=2.0 (⚠V0)
  # + scenario_expand: bool=False (env QUERY_SCENARIO_EXPAND) + scenario_expand_factor: float=1.0 (⚠V0)
  # + scenario_terms_path: str="seeds/dict_scenario_terms.csv" (env QUERY_SCENARIO_TERMS_PATH)
seeds/dict_scenario_terms.csv   # NEW v0-draft (oral_term,legal_terms),待 §15⑥ 评审;仅查询层读,不入 demo up 灌库
query/tests/
  test_sparse_boost.py              # 纯单元:detect regex、augment_sparse(fake embed)、load_scenario_terms、双关 byte 等价
  test_sparse_boost_integration.py  # 真栈:发文字号名次↑、口语扩展召回↑、双关 byte 等价
docs/query-agent-docs/SPEC-SPARSE.md / PLAN-SPARSE.md / TASKS-SPARSE.md
```

## 5. Code Style

沿用接缝 / 纯函数 idiom。增强为**纯函数**(无 IO,embed 注入),默认空集 = 原样返回(byte 等价根):

```python
def augment_sparse(
    query: str,
    base_sparse: dict[str, float],
    *,
    embed,                              # EmbeddingClient(注入;复用本地 BGE-M3,批量)
    scenario_terms: dict[str, list[str]] = {},
    docnum_factor: float = 2.0,
    expand_factor: float = 1.0,
    docnum_on: bool = False,
    expand_on: bool = False,
) -> dict[str, float]:
    spans: list[tuple[str, float]] = []
    if docnum_on:
        spans += [(s, docnum_factor) for s in detect_doc_numbers(query)]   # 发文字号 + 《全名》
    if expand_on:
        spans += [(t, expand_factor) for t in _matched_legal_terms(query, scenario_terms)]
    if not spans:
        return base_sparse              # 无命中 → 原样(byte 等价)
    out = dict(base_sparse)
    for vec, factor in zip(embed.embed([s for s, _ in spans]), (f for _, f in spans)):
        for tok, w in vec.sparse.items():        # token_id(str) → lexical 权重
            out[tok] = out.get(tok, 0.0) + factor * w     # 加权并入(放大/扩展 token)
    return out
```

> RRF 是基于秩的:对**特定 token** 加权 → 含该 token 的 chunk 的 sparse IP 升 → 其 sparse 名次升 → RRF 浮顶。
> (uniform 缩放全 sparse 对 RRF 无效,故必须**选择性** token 提权 —— 这是弃 WeightedRanker 仍达意的关键。)

`hybrid.retrieve` 接缝(改动最小):

```python
emb = self._embed.embed([query])[0]
sparse = emb.sparse
if self._qcfg.docnum_boost or self._qcfg.scenario_expand:
    sparse = augment_sparse(
        query, emb.sparse, embed=self._embed, scenario_terms=self._scenario_terms,
        docnum_factor=self._qcfg.docnum_boost_factor, expand_factor=self._qcfg.scenario_expand_factor,
        docnum_on=self._qcfg.docnum_boost, expand_on=self._qcfg.scenario_expand,
    )
for corpus in _PARTITIONS:
    res = self._milvus.search(emb.dense, sparse, topk=..., corpus=corpus, with_text=with_text, ...)
```

## 6. Testing Strategy

- **单元(零栈零模型)**:
  - `detect_doc_numbers`:命中 `银保监发〔2021〕5号` / `证监发〔2020〕第53号` / `财会〔2017〕22号` / 半角 `(2023)5号` / 裸 `〔2023〕5号` + 制度全名 `《XX管理办法》`;**不误命中**纯数字 / 普通句;全角↔半角归一(经 `to_halfwidth`)。
  - `augment_sparse`(**fake embed**:对 span / 法言词返预设 sparse)→ 断言命中 token 按 `factor` 加权并入、新 token 加入;**无命中 / 双关关 → 返回 `base_sparse` 同一性(byte 等价守护)**;`docnum_on` 单开只提权、`expand_on` 单开只扩展。
  - `load_scenario_terms`:解析 CSV(`legal_terms` 按 `|` 拆)→ dict;**文件缺 / 空 → `{}`**(consumed-when-present)。
- **集成(gate = PG+Milvus+BGE-M3)**:
  - **发文字号提权**:索引含特定发文字号的多 chunk;查询该编号,`docnum_boost=True` 下目标 chunk 名次 **高于** `docnum_boost=False`(构造可判别,断言 rank 提升 / 进 topk)。
  - **词典扩展**:seed 含 `代客理财|全权委托|受托理财`;索引仅含"受托理财"的 chunk;口语查询"代客理财",`scenario_expand=True` 召回该 chunk、`False` 漏(覆盖面拓宽)。
  - **byte 等价**:双关默认关 → `retrieve` 结果与本轮前一致(同 fixture 同序)。
- **守护断言**:**双开关默认关 byte 等价**(不回归八路);**只动 sparse**(dense 入参不变;断言 `search` 收到的 `dense` 恒等);增强**零网络**(复用本地 BGE-M3,未设模型 → 集成 skip)。

## 7. Boundaries

- **Always**:**`docnum_boost`/`scenario_expand` 默认 False → byte 等价**(不回归既有八路);增强**零 LLM**(regex + dict 子串);**只动 sparse、不动 dense**;**仅施于主 `retrieve`(R1/R5)**;dict **consumed-when-present**(缺/空 → 扩展为空);复用既有 `embed` 接缝(**零新模型 / 零新依赖**);**`milvus_io.search` 签名零改动**。
- **Ask first**:**新增 `seeds/dict_scenario_terms.csv`** —— 内容属 **业务域语义**(口语→法言映射),**v0-draft 待 §15⑥(张老师 + 张益)评审**,本切片只给草案 schema + 少量示例(代客理财 / 二维码介绍开户 / 见底到顶,源自 §3.2);**须确认加该 CSV 不扰动 `demo up` 灌库**(seed 步骤须按表显式加载、非 glob `seeds/*.csv`;查询层独立读该文件)。
- **Never**:发文字号 / 法言词进入**生成**(§7.1 clause_id 注入已防编造,§5.4 **只影响检索排序**);切 `WeightedRanker` / 改 RRF 融合语义;改 `status`/可见性过滤语义(增强不碰 `expr`);**联网下载**;改 `Candidate`/Milvus schema。

## 8. Success Criteria(可测)

1. `docnum_boost=True` + 查询含发文字号 → 目标编号 chunk 检索名次**较关闭时上升**(集成断言);**保持 `RRFRanker`、零 pipeline 改动**。
2. `scenario_expand=True` + 非空 dict + 口语查询 → 召回仅含法言词的 chunk(关闭时漏;集成断言覆盖面拓宽)。
3. **双开关默认关(False)byte 等价**:`retrieve` 行为与本轮前一致(单元 `augment_sparse` 同一性 + 集成同序);**只动 sparse**(`search` 收到的 `dense` 恒等)。
4. `detect_doc_numbers` 覆盖主流发文字号格式 + 制度全名,**不误命中**普通句 / 纯数字(单元参数化)。
5. `load_scenario_terms` **consumed-when-present**:文件缺/空 → `{}`;扩展无命中 → byte 等价。
6. `augment_sparse` 纯函数:fake embed 下命中 token 按系数加权并入;`docnum_on`/`expand_on` 各自独立生效。
7. 增强**零网络**:复用本地 BGE-M3,未设模型路径 → 集成 **skip**(绝不联网)。
8. `config` 新字段(`docnum_boost`/`scenario_expand`/两系数/`scenario_terms_path`)**add-only**、默认关;env 覆盖(`QUERY_DOCNUM_BOOST` 等)。
9. 全仓全量 + ruff 全绿;**DAG 无环**(`query → pipeline → common`,本切片不新增跨包依赖)。

## 9. Open Questions(已决 3 项 + 默认待 gate)

| # | 事项 | 处置(✅=AskUserQuestion 已定 / 默认) |
|---|---|---|
| **范围** | 提权 / 扩展 取舍 | ✅ **两者都做** + `dict_scenario_terms` **v0-draft seed**(consumed-when-present)。 |
| **机制** | 发文字号提权落法 | ✅ **查询层 sparse token 提权**(保持 RRFRanker、零 pipeline 改动);弃 WeightedRanker / 检索后提分。 |
| **应用范围** | 施于哪些 retrieve | ✅ **仅主 hybrid `retrieve`(R1/R5)**;R4 枚举 / R2/R3/R6 不接。 |
| Q1 | 提权 / 扩展系数 | 默认 `docnum_boost_factor=2.0` / `scenario_expand_factor=1.0`;⚠ **V0 标定**(占位,不承诺)。 |
| Q2 | 合并策略 | 默认 **加权相加**(`out[t] += factor*w`,保证命中 token ≥ 原值);`max` / 归一留增强。 |
| Q3 | 发文字号 regex 边界 | 默认机关代字`〔年〕第?序号号` + 全角/半角括号 + 制度全名`《…》`;细化留 impl(参数化测试钉)。 |
| Q4 | dict 加载源 | 默认**查询层读 `seeds/dict_scenario_terms.csv`**(v0 workaround);生产 = PG `dict_scenario_terms` 表(GAP #11 / §15⑥,另切片)。 |
| Q5 | 默认开/关 | 默认 **双关闭(byte 等价)**,opt-in 至 V0 标定;同 rerank 保守范式。 |

## 10. 与 §15 / §5.4 的关系

- **§15②(网关 embedding 双输出 endpoint)**:本地 BGE-M3 已 **dense+sparse 双输出**(§5.1 已落),**非本切片阻塞**;
  生产换网关 endpoint(版本钉死、变更=全量重灌)属 §9.1 / CP-005-②。
- **§15⑥(字典初版评审)**:`dict_scenario_terms` 内容受其阻塞 → 本切片仅 **v0-draft seed + 查询层机制**,
  **consumed-when-present 默认空 = byte 等价**,不对甲方承诺 dict 内容 / 覆盖率(同 R4 biz/entity dict 范式)。
- **§5.4 既定**:发文字号/制度全名 → sparse 提权、语义问句 dense 主导、`dict_scenario_terms` 扩 sparse 命中面 ——
  本轮落**查询层 token 提权 + dict 扩展**,**差异化系数属 §15 待 V0 标定**(默认占位)。
- **§7.1 防编造**:发文字号**永不进生成**(clause_id 注入兜底);§5.4 **只改检索排序**,不触红线。

## 11. 验证清单(进 Phase 2 前)

- [x] 六大块齐全 · [x] 成功标准可测 · [x] 边界三档 · [x] spec 落盘
- [ ] **人工复核批准**(尤其 §0 边界、§7 Ask-first 新增 `seeds/dict_scenario_terms.csv`【内容 v0-draft 待 §15⑥】+ 确认不扰 `demo up` 灌库、§8 SC3 双关 byte 等价 + 只动 sparse、§9 Q4 dict 读 CSV 的 v0 workaround)
