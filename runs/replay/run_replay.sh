#!/bin/zsh
# Replay set (#97): temperature-0 capture on stack A, pass 1 then pass 2.
# Launch THROUGH ssh localhost: the uv-managed CPython has no macOS Local Network permission under Claude Code
# ("No route to host" to pluto), while sshd-spawned processes do:
#   ssh localhost "nohup zsh -l ~/source/repos/ReCLamO-Harness/runs/replay/run_replay.sh > ~/source/repos/ReCLamO-Harness/runs/replay/run_replay.log 2>&1 &"
set -u
export PATH=$HOME/.local/bin:/opt/homebrew/bin:$PATH
cd ~/source/repos/ReCLamO-Harness
export RECLAMO_BASE_URL=${RECLAMO_BASE_URL:-http://172.16.28.254:8083/v1}
echo "$(date '+%Y-%m-%d %H:%M') replay pass 1 started, code $(git rev-parse --short HEAD)"
uv run python evals/independent/replay_capture.py --pass 1 --concurrency 2
echo "$(date '+%Y-%m-%d %H:%M') replay pass 1 finished (exit $?)"
uv run python evals/independent/replay_capture.py --pass 2 --concurrency 2
echo "$(date '+%Y-%m-%d %H:%M') replay pass 2 finished (exit $?)"
uv run python evals/independent/replay_capture.py --compare runs/replay/stackA-pass1.jsonl runs/replay/stackA-pass2.jsonl > runs/replay/stackA-compare.md
echo "$(date '+%Y-%m-%d %H:%M') REPLAYDONE"
