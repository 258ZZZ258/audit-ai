#!/bin/bash
# 10 分钟轮询看门狗:监控入库处理进程(ingest/meta confirm/reprocess)+ Milvus。
# 每轮 stdout 一行 → Monitor 事件:POLL(推进中)/ STALL(无进展或 Milvus 异常)/ DONE(处理进程已退出)。
WT=/Users/apple/Projects/audit-ai-demo
cd "$WT" || exit 1
set -a; . ./.env.local; set +a
export PYTHONPATH="$WT/libs/common:$WT/pipeline:$WT/eval:$WT/query"
PY=/Users/apple/Projects/audit-ai/.venv/bin/python
prev=-1
while true; do
  busy=$(pgrep -f "run_batch.sh|stage_corpus|gen_manifest|pipeline.cli ingest|pipeline.cli meta|pipeline.cli reprocess" | head -1)
  st=$($PY -c "
try:
    from pipeline.config import load_config
    from pipeline.index.pg_io import PgIO
    from sqlalchemy import text
    from pymilvus import connections, utility
    pg=PgIO.from_config(load_config())
    with pg.session() as s:
        done=s.execute(text(\"select count(*) from doc_versions where pipeline_status in ('INDEXED','DEGRADED_INDEXED','QUARANTINED','QC_FAILED','REJECTED')\")).scalar()
        pend=s.execute(text(\"select count(*) from doc_versions where pipeline_status in ('META_REVIEW','INDEXING','EMBEDDING','REGISTERED','PARSING','QC_PENDING','STRUCTURING')\")).scalar()
    connections.connect(host='localhost',port='19531',timeout=15); utility.list_collections(); mil='ok'
    print(f'{done} {pend} {mil}')
except Exception as e:
    print(f'-1 -1 ERR:{type(e).__name__}')
" 2>/dev/null | tail -1)
  d=$(echo "$st" | awk '{print $1}'); p=$(echo "$st" | awk '{print $2}'); m=$(echo "$st" | awk '{print $3}')
  if [ -z "$busy" ]; then echo "DONE 处理进程已退出 · 终态 $d · 待处理 $p · milvus=$m"; break; fi
  if [ "$d" = "$prev" ] || [ "$m" != "ok" ]; then
    echo "STALL 无进展/Milvus异常 · 终态 $d(上轮 $prev)· 待处理 $p · milvus=$m"
  else
    echo "POLL 推进中 · 终态 $d · 待处理 $p · milvus=$m"
  fi
  prev="$d"
  sleep 600
done
