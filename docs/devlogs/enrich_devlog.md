# 富集层 devlog(pipeline/pipeline/enrich)

**职责**:E1 义务条款预打标(零 LLM 正则 + `config/obligation.yaml` 词表),接 `_structuring` 装配,写 `clause_tags`。富集链起点(为比对智能体预热)——证明加富集步不动状态机/解析器、默认零 LLM。

## 关键决策 / 踩坑
- **Plan 探针定方向(非拍脑袋)**:batch01 真文本统计「应」分布——690 个「应」中 应当 637(92%),前缀陷阱仅 相应(15),后缀(应用/应急)近乎不现。据此词表初值固化进 `config/obligation.yaml`,**后缀排除不加**(避免造假阴)。
- **matcher(A1)**:`match_obligation` = 整词 markers **或** bare 单字(应/须)且前缀不落 `exclusions`。前缀排除**统一作用于 `应当`/`须经` 这类 marker**(修 `对应当`/`无须经` 子串误命中)。X应=相应/对应(应在监管语料 98% 表义务,故不排);**X须=无须/毋须 必排**(否定义务)。
- **装配(A2)**:`_structuring` 改 **clear→s3→tag→s4**(clear 先于 s3 `replace_chunks` 删 chunk,避 `clause_tags.chunk_id` FK 子悬空)。E1 异常 `_safe_e1` 吞掉**不阻断终态**。**连带**:管线给每件写 clause_tags → 凡删 chunk 的测试 teardown 须**先删 clause_tags**(FK 子先删)。
- **golden / V8**:人工据语义**独立标注**(22 正 + 12 负,batch01 真条款,**非 matcher 输出**否则自证),`test_obligation_golden` 断言 precision=1.0 / recall。唯一 FN 曾是「用印须填写」(bare 须)——续 #2 加 `bare_chars`(应/须)+ `无须/毋须` 排除后 **recall 0.955→1.0**(`无须` 负例锁 X须 排除)。

## E2 条款级打标(LLM,默认关 `e2_enabled`;V16 落地)

- **纪律(被 `case_l2`/`l2_llm` 反复"镜像 E2 纪律")**:字典约束(取值空间 = `dict_entity_types`/`dict_departments`/`dict_biz_domains`)+ **服务端二次裁剪**(`_enforce`,never trust LLM,越界值一律丢弃)+ **不臆测**(条文显式限定才打,无则留空)→ 写 `clause_tags` 的 entity_type/部门/事项 + `dict_version`。
- **client 注入 + 非阻断 + 默认关**:`llm_client`(httpx OpenAI 兼容,JSON 模式,`gpt-5.4-nano`)经形参注入(测试用 fake,免真调用);`LLMError` 经 `_safe_*` 吞掉不改 `pipeline_status`;`e2_enabled` 默认关 → 默认路径零 LLM、不触达本模块。**key 仅走 env `OPENAI_API_KEY`、绝不入库**;prompt 在根 `PROMPTS.md`。

> 时间轴:`docs/devlog.md` 阶段 M3(探针 / A1 / A2 / B1)、M3 续 #1(search 出义务标)/#2(bare 须泛化)、V16(E2)。
