#!/usr/bin/env bash
# A/B: run the 27-task subset twice — v1 (baseline prompt) then v2 (new prompt) —
# into separate result dirs, so we can attribute any delta to the prompt change.
set -u
cd /mnt/zhaorunsong/repo/CUA/Env/OSWorld

PYO=/mnt/zhaorunsong/anaconda3/envs/osworld/bin/python
URLS="http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1"
COMMON_ENV=(
  DOCKER_HOST=unix:///var/run/docker.sock
  OSWORLD_FORCE_KVM=1
  http_proxy=http://127.0.0.1:7897
  https_proxy=http://127.0.0.1:7897
  no_proxy=localhost,127.0.0.1
  NO_PROXY=localhost,127.0.0.1
)

for variant in v1 v2; do
  echo "===== $(date '+%H:%M:%S') starting prompt=$variant ====="
  env "${COMMON_ENV[@]}" "$PYO" holo_repro/run_holo.py \
    --test_meta evaluation_examples/ab_subset.json \
    --prompt "$variant" \
    --result_dir "results_ab_$variant" \
    --workers 4 \
    --base_urls "$URLS" \
    > "/mnt/zhaorunsong/repo/CUA/ab_$variant.log" 2>&1
  echo "===== $(date '+%H:%M:%S') done prompt=$variant ====="
done
echo "ALL DONE"
