# Plan: §5.4 sparse 精确通道(发文字号提权 + 词典扩展)—— 技术实现计划

> 状态:**Phase 2 / PLAN —— 待人工复核批准**。依据 `SPEC-SPARSE.md`(已批准 2026-06-26:范围=提权+扩展 v0-draft seed、
> 机制=查询层 sparse token 提权保持 RRFRanker、应用=主 retrieve R1/R5)。延续纯函数 + consumed-when-present idiom。
> **零承重(pipeline)改动 = `milvus_io.search` 签名不变(传增强后 sparse 即可);零新依赖;双开关默认关 byte 等价。**
> **§7 风险已核实**:`PgIO.seed_dicts`(pg_io.py:233)**显式读命名文件**(`dict_issuers/biz_domains/entity_types/departments.csv`),
> **非 glob `seeds/*.csv`** → 新增 `seeds/dict_scenario_terms.csv` 对 `demo up` 灌库 **inert**(仅查询层读)。

## 1. 组件与依赖

```
retrieve/sparse_boost.py        [新增,纯函数,零栈零模型]
   detect_doc_numbers(query) -> list[str]                # regex:发文字号 + 《制度全名》(先 to_halfwidth 归一)
   load_scenario_terms(path) -> dict[str, list[str]]     # CSV(oral_term,legal_terms|分隔)→dict;缺/空/坏行→{} (consumed-when-present)
   _matched_legal_terms(query, terms) -> list[str]       # 口语词子串命中 → 映射法言词(去重保序)
   augment_sparse(query, base_sparse, *, embed, scenario_terms={}, docnum_factor=2.0,
                  expand_factor=1.0, docnum_on=False, expand_on=False) -> dict[str, float]
        spans = [(发文字号/全名, docnum_factor)…] + [(法言词, expand_factor)…]
        if not spans: return base_sparse                 # 无命中 → 原样(byte 等价根,同一性)
        out = dict(base_sparse); for vec,f in zip(embed.embed(spans_text), factors):
            for tok,w in vec.sparse.items(): out[tok] = out.get(tok,0)+f*w   # 选择性 token 加权并入
   ▲
retrieve/hybrid.py              [改:retrieve 1 处注入;enumerate/cases 不动]
   Retriever.__init__ +self._scenario_terms = load_scenario_terms(qcfg.scenario_terms_path) if qcfg.scenario_expand else {}
   retrieve(query):
       emb = embed([query])[0]; sparse = emb.sparse
       if qcfg.docnum_boost or qcfg.scenario_expand:
           sparse = augment_sparse(query, emb.sparse, embed=self._embed, scenario_terms=self._scenario_terms,
                                   docnum_factor=…, expand_factor=…, docnum_on=…, expand_on=…)
       for corpus in _PARTITIONS: search(emb.dense, sparse, …)     # dense 恒等、search 签名不变
   ▲
config.py                       [改:add-only 字段 + env]
   QueryConfig +docnum_boost:bool=False +docnum_boost_factor:float=2.0(⚠V0)
              +scenario_expand:bool=False +scenario_expand_factor:float=1.0(⚠V0)
              +scenario_terms_path:str=<repo>/seeds/dict_scenario_terms.csv(锚 repo 根,同 DEFAULT_CONFIG_DIR)
   _apply_env +QUERY_DOCNUM_BOOST / QUERY_SCENARIO_EXPAND / QUERY_SCENARIO_TERMS_PATH(bool 由 pydantic 强转)
   ▲
seeds/dict_scenario_terms.csv   [新增 v0-draft]  oral_term,legal_terms  (§3.2 示例,待 §15⑥ 评审;seed_dicts 不读)
```

**复用**:`pipeline.index.embedding_client`(`EmbeddingClient.embed([..]) -> [Embedding(.dense,.sparse=lexical_weights)]`,
embed 注入故 `sparse_boost.py` **不 import** 它,duck-typed)、`pipeline.chunking.normalize.to_halfwidth`(全角→半角归一)、
`MilvusIO.search`(**签名不变**)、`Candidate`/`_to_candidate`。**零新依赖、默认零增强、零网络**(增强复用本地 BGE-M3)。

> **`sparse_boost.py` 零承重导入**:纯函数 + 注入 embed,可零栈零模型单测(fake embed)。唯一外部依赖 = `to_halfwidth`
> (query→pipeline,DAG 允许;若忌可本地实现,默认复用)。

## 2. 实现顺序 + 检查点(TDD)

### Phase A — `sparse_boost.py` 纯函数(核心,零栈零模型)
- `detect_doc_numbers`:`to_halfwidth` 后 regex 命中机关代字`〔年〕第?序号号` + 制度全名`《…》`;去重保序。
- `load_scenario_terms`:`csv` 读(`legal_terms` 按 `|` 拆)→ dict;**文件缺/空/坏行 → `{}` / 跳过**(consumed-when-present)。
- `_matched_legal_terms`:口语词子串命中 → 法言词扁平去重。
- `augment_sparse`:装配 spans → **无命中返 `base_sparse` 同一对象**;有命中 → copy + `embed(spans)` 加权并入。
- **检查点 A**:`query/tests/test_sparse_boost.py`(**fake embed**)——detect 覆盖 `银保监发〔2021〕5号`/`证监发〔2020〕第53号`/`财会〔2017〕22号`/半角`(2023)5号`/`《XX管理办法》` + **不误命中**普通句/纯数字;`load_scenario_terms` 解析 + 缺/空→`{}`;`augment_sparse` 命中 token 按 `factor` 并入、**双关关/无命中 → 返回 `base_sparse` 同一性(byte 等价守护)**、`docnum_on`/`expand_on` 独立。**零栈零模型**。

### Phase B — `config` 加字段 + env(独立,可与 A 并行)
- `QueryConfig` +4 字段(默认关/系数/路径,锚 repo 根)+ `_apply_env` 3 env;bool 由 pydantic 强转(`"1"/"true"`)。
- **检查点 B**:`query/tests/test_config*.py`(或新增)——默认值;env 覆盖(`QUERY_DOCNUM_BOOST=1`→True);路径默认锚 `<repo>/seeds`。**零栈**。

### Phase C — `Retriever` 接线 + seed CSV(依赖 A+B)
- `Retriever.__init__` 载 `_scenario_terms`(`scenario_expand` 开才读文件,关→`{}` 免 IO);`retrieve` 注入 `augment_sparse`(仅 `retrieve`,**`retrieve_enumerate`/`retrieve_cases` 不动**)。
- 新增 `seeds/dict_scenario_terms.csv`:header + §3.2 示例(`代客理财`→`全权委托|受托理财`、`二维码介绍开户`→`违规招揽客户|居间介绍`、`见底到顶`→`对买卖时机的具体建议`)。
- **检查点 C**:`test_sparse_boost.py` 加 retriever 级(**fake embed + fake milvus 捕获入参**)——双关关 → `search` 收到 `emb.sparse` **同一性** + `dense` **恒等**(byte 等价 + **只动 sparse** 守护);开 + fake → `search` 收到增强 sparse。**零栈**。

### Phase D — 集成(gate = PG+Milvus+BGE-M3)
- `query/tests/test_sparse_boost_integration.py`:
  - **提权**:索引含特定发文字号的多 chunk;查询该编号 → `docnum_boost=True` 目标 chunk 名次 **高于** `False`(断言 rank↑/进 topk)。
  - **扩展**:seed `代客理财|受托理财`;索引仅含"受托理财"chunk;口语查"代客理财" → `scenario_expand=True` 召回、`False` 漏。
  - **byte 等价**:双关关 → `retrieve` 与本轮前同序;未设 BGE-M3 模型 → skip;autouse 幂等 `mio.connect()`。
- **检查点 D**:集成绿(gate;缺模型 skip)。

### Phase E — 收尾(devlog/GAP/RTM/时间轴)+ 全仓门
- `query_devlog.md` 记决策/踩坑(查询层 token 提权弃 WeightedRanker、seed_dicts inert 核实);`GAP.md`(§5.4 ❌→✅;§8 资产 `dict_*` 加 scenario_terms 行 partial);`RTM.md`(§5.4 → ✅ 挂 test_id);`docs/devlog.md` 加阶段。
- **检查点 E**:全仓非模型门 + sparse 模型门集成绿;ruff 全绿;DAG 无环(`query→pipeline→common`)。

## 3. 并行 vs 串行
A(`sparse_boost` 纯函数)∥ B(`config`)→ C(`Retriever` 接线 + seed,依赖 A+B)→ D(集成,依赖 C,真栈)→ E(收尾+全仓门)。A/B 可并行(纯函数 + config 独立)。

## 4. 风险与缓解
| # | 风险 | 缓解 |
|---|---|---|
| R1 | **双关默认关回归** R1/R3/R4/R5/R6 | `augment` 仅 `docnum_boost`/`scenario_expand` 开时调;无命中 **返 `base_sparse` 同一性**;`test_sparse_boost` + 集成守 byte 等价 |
| R2 | **误改 dense**(违"只动 sparse")| `augment_sparse` 只返 sparse、不碰 dense;**检查点 C 断言 `search` 收到 `dense` 恒等** |
| R3 | 增强**联网下载** | 复用本地 BGE-M3(`self._embed`);未设模型 → 集成 skip;**零新模型/零外呼** |
| R4 | 加 `dict_scenario_terms.csv` **扰 `demo up` 灌库** | **已核实** `seed_dicts` 显式读命名文件(非 glob)→ 新 CSV inert;`test_pg_io` 守 seed 计数不变 |
| R5 | dict **缺/坏** | `load_scenario_terms` 缺/空/坏行 → `{}`/跳过(consumed-when-present);扩展无命中 → byte 等价 |
| R6 | `scenario_terms_path` **相对路径随 cwd 漂移** | 默认锚 `<repo>`(`Path(__file__).parents[2]/seeds/…`,同 `DEFAULT_CONFIG_DIR`);env 绝对路径覆盖 |
| R7 | RRF 基于秩,**uniform 缩放无效** | `augment` **选择性** token 提权(只动命中 span/法言词 token,改 sparse 内部秩)→ 集成断言名次变化证有效 |
| R8 | 提权/扩展**污染 dense 语义** | 只注入 sparse;dense 改写归 HyDE/N1(out of scope) |
| R9 | 发文字号 regex **误/漏命中** | 参数化钉主流格式 + 反例;全角半角 `to_halfwidth` 归一;边界细化随测演进 |
| R10 | span/法言词 **额外 embed 成本** | spans 短少,单独一次 batch embed;query+spans 合批优化留后续 |

## 5. 可追溯(§5.4 → 组件 / 守护)
| §5.4 能力 | 组件 | 守护 |
|---|---|---|
| 发文字号/全名 → sparse 提权 | `detect_doc_numbers` + `augment_sparse`(docnum)| `docnum_boost` 默认关 byte 等价 |
| 语义问句 dense 主导 | 无 docnum 命中 → sparse 原样(不增强)| 无命中 byte 等价 |
| `dict_scenario_terms` 扩 sparse 命中面 | `load_scenario_terms` + `_matched_legal_terms` + `augment_sparse`(expand)| consumed-when-present 默认空 byte 等价 |
| 只动 sparse 不动 dense | `augment_sparse` 只返 sparse | 检查点 C `dense` 恒等 |
| 仅主 retrieve(R1/R5)| `Retriever.retrieve` | `retrieve_enumerate`/`retrieve_cases` 不接 |
| 差异化系数 | `docnum_boost_factor`/`scenario_expand_factor` | §15 V0 标定 |

## 6. 验证清单(进 Phase 3 前)
- [x] 组件/依赖 · [x] 顺序+检查点(A–E)· [x] 并行 · [x] 风险(含双关等价 + 只动 sparse + seed inert 核实)· [x] 可追溯
- [ ] **人工复核批准**
