#!/bin/bash
# 单批入库:stage(格式归一)→ manifest(L1+L2 登记)→ ingest(扫描走 OCR)→ meta confirm → 报状态。
# 用法:bash tools/doc_test/run_batch.sh <NN>   (NN=01..10)
# 条款树体例修复在批后人工做(诊断 QC_FAILED → 改 clause_tree → reprocess)。
N="$1"
WT=/Users/apple/Projects/audit-ai-demo
cd "$WT" || exit 1
set -a; . ./.env.local; set +a
export PYTHONPATH="$WT/libs/common:$WT/pipeline:$WT/eval:$WT/query"
PY=/Users/apple/Projects/audit-ai/.venv/bin/python
O=tools/doc_test/out
NOISE='Loading weights|Inference Embeddings|pre tokenize|fork_posix|absl::|pkg_resources|DistributionNotFound|UserWarning|from pkg_resources|WARNING|loguru|it/s\]|download|Fetching|%\|'

echo "### batch_$N · stage ###"
$PY tools/doc_test/stage_corpus.py --in "$O/batches/batch_$N.jsonl" --batch-dir "$O/b$N" --out "$O/staged_$N.jsonl" 2>&1 | tail -3
echo "### batch_$N · manifest ###"
$PY tools/doc_test/gen_manifest.py --in "$O/staged_$N.jsonl" --batch-dir "$O/b$N" --seeds seeds --out "$O/manifest_$N.xlsx" 2>&1 | grep -vE "$NOISE" | tail -2
echo "### batch_$N · ingest(扫描走 OCR,可能很慢)###"
$PY -m pipeline.cli ingest "$O/b$N" -m "$O/manifest_$N.xlsx" 2>&1 | grep -vE "$NOISE" | tail -3
bid=$($PY -c "
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO
from sqlalchemy import text
pg=PgIO.from_config(load_config())
with pg.session() as s:
    print(s.execute(text('select batch_id from import_batches order by created_at desc limit 1')).scalar())
" 2>/dev/null | tail -1)
echo "### batch_$N · meta confirm (bid=$bid) ###"
$PY -m pipeline.cli meta confirm --batch "$bid" >/dev/null 2>&1
echo "### batch_$N · 状态 ###"
BID="$bid" $PY -c "
import os
from pipeline.config import load_config
from pipeline.index.pg_io import PgIO
from sqlalchemy import text
pg=PgIO.from_config(load_config())
with pg.session() as s:
    for st,n in s.execute(text('select pipeline_status,count(*) from doc_versions where batch_id=:b group by 1 order by 2 desc'),{'b':os.environ['BID']}): print(f'  {st}: {n}')
"
echo "BATCH_DONE bid=$bid"
