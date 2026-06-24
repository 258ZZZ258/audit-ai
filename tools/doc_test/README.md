# 第一期文档处理管线测试(tools/doc_test)

> 📖 **团队成员请看 [`使用指南.md`](使用指南.md)** —— 详细的"怎么用 / 怎么看报告 / 三大目标怎么下结论"。
> 本 README 是快速参考。

对一批**已分类好、无 manifest** 的 PDF,**跳过 S0 登记**,逐件直调管线纯函数
(`解析(light)→IR → 条款树切块 → QC 指标 → L1/案例 正则抽取`),用指标 + 可选 LLM 无标注裁判
评估三件事,产出**易懂中文报告**(标失效 PDF + 异常指标分析)。

## 三大测试目标 → 指标

| 目标 | 确定性指标 | LLM 裁判(无标注真值) |
|---|---|---|
| **① 正则覆盖度/结构化** | 要素抽取命中率(文号/日期/机构;案例:机构/当事人/金额…)· clause_coverage · 表头识别率 · #chunks/有效 clause_path | 核对正则抽得**对不对、全不全** → 标抽错/漏识别 + 覆盖评分 |
| **② 是否需 DeepDoc** | 每页字符数(≈0→扫描件)· 乱码率 · QC 文本质量 | 判**版面破碎/表格丢失/OCR 乱码/阅读序错乱** → "light 够用 / 建议 DeepDoc" + 原因 |
| **③ QC 阈值** | 7 指标**数值**对当前阈值 · 失败分布 | 判文档真实好坏 × QC 通过/失败 → 假阳(太严)/假阴(太松)→ 调整方向 |

## 跑法

```bash
cp tools/doc_test/config.example.yaml tools/doc_test/config.yaml
# 编辑 config.yaml:填 pdf_root、corpus_map(目录名→类型)、llm.enabled/model
# LLM 走 env(绝不入库):
export OPENAI_API_KEY=sk-...           # 必填(开 LLM 时)
export OPENAI_BASE_URL=https://你的网关/v1   # 可选
.venv/bin/python tools/doc_test/run_phase1.py --config tools/doc_test/config.yaml
```

产物落 `output.dir`(默认 `tools/doc_test/out/`):`phase1_report.md`(易懂报告)+ `phase1_metrics.json`(逐 PDF 原始指标,可复跑对比阈值实验)。

## 关键设计 / 注意

- **无 manifest**:分类由你按**父目录名 → corpus_type** 给(`corpus_map`),或 `file_overrides` 逐文件指定;未匹配的件默认 skip 并在报告标注。corpus_type ∈ `P-INT/P-EXT/P-CASE/P-QA`,决定用哪套正则与 QC profile。
- **绕过 S0/PG**:只调纯函数(parser/chunker/qc/l1_rules),零 PG / 零 ObjectStore / 零 Milvus;PDF 直读字节,不需 soffice(仅 docx 才需)。
- **解析失败(扫描件)**:light 解析对字符密度 `< scanned_char_per_page_max`(默认 50/页)的件直接判扫描件(错误码 E202),记为**管线失效**并强提示 OCR/DeepDoc。
- **LLM 可关**:`llm.enabled: false` 时只出确定性报告(零成本);`max_pdfs>0` 可只对前 N 件跑 LLM(冒烟/控成本)。LLM 失败不阻断,报告照常出确定性部分。
- **clause_coverage 读法**:= 结构化条数 ÷ 宽松「第X条」命中数;**>1 正常**(小数/交易所编号体例),**<1 才是漏结构化**(报告只列 <0.95 的件)。

## 阈值实验

`config.yaml` 的 `qc_thresholds:` 留空=用仓库 `config/qc_thresholds.yaml` 现值;在此覆盖(如
`{clause_coverage_min: 0.90}`)即可不改仓库配置、跑对比看失败分布变化,辅助决定目标③。
