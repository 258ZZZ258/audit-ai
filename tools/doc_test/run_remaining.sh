#!/bin/bash
# 主循环:顺序跑 batch_18..25(各 run_batch.sh 阻塞,完成才下一个,绝不并发争 Milvus)。
# 先等 batch_17(disown 启的)结束。一个后台任务驱动剩余全部批,看门狗全程盯栈。
WT=/Users/apple/Projects/audit-ai-demo
cd "$WT" || exit 1
echo "=== MASTER 等 batch_17 结束 ==="
while pgrep -f "run_batch.sh 17|pipeline.cli ingest" >/dev/null; do sleep 30; done
for n in 18 19 20 21 22 23 24 25; do
  echo "=== MASTER 启 batch_$n $(date +%H:%M) ==="
  bash "$WT/tools/doc_test/run_batch.sh" "$n"
done
echo "=== MASTER 全部完成 batch_18-25 $(date +%H:%M) ==="
