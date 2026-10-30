#!/bin/bash
# Frontier replication (issue #120, TEST-PLAN 1j): GPT-5 + GPT-5-mini with the paper's
# settings vs plain GPT-5, on the 8 independent tasks at small, medium and large.
#
#   OPENAI_API_KEY=... CAP_USD=600 evals/gpt5-replication/run.sh pilot
#   OPENAI_API_KEY=... CAP_USD=600 evals/gpt5-replication/run.sh full
#
# pilot: seeds 4-11, all three sizes (64 pairs per size). Checks the pipeline.
# full:  seeds 4-43 at small and medium (320 pairs), 4-23 at large (160). Resumes the
#        pilot's files, so pilot rows are part of the full sample (fixed in advance).
#
# Arms: rlm (gpt5-rlm), plain (gpt5-plain); at large also mapreduce (gpt5-plain profile:
# GPT-5-mini readers, GPT-5 aggregator), because plain GPT-5 cannot fit any large document.
# 4 seed lanes per arm run in parallel (run_eval runs rows one at a time). A lane with 3
# errors in a row is stopped. A cost guard stops everything when the upper-bound spend
# (cost.py) reaches CAP_USD. Error rows are moved aside and re-run (up to 4 passes);
# then lanes merge into runs/exp-gpt5/{rlm,plain,mapreduce}.json. Run from the repo root.
set -u
export PYTHONUNBUFFERED=1
STAGE=${1:?usage: run.sh pilot|full}
CAP_USD=${CAP_USD:?set CAP_USD, the most you are willing to spend in dollars}
: "${OPENAI_API_KEY:?set OPENAI_API_KEY}"
K=evals/gpt5-replication
D=runs/exp-gpt5; L=$D/lanes; mkdir -p $L $D/traj $D/quarantine
P="--profiles $K/profiles.toml"

seeds() {  # first last -> 4 comma lists, round-robin
  python3 -c "import sys;a,b=int(sys.argv[1]),int(sys.argv[2]);print(' '.join(','.join(str(s) for s in range(a+i,b+1,4)) for i in range(4)))" "$1" "$2"
}
case $STAGE in
  pilot) SM=($(seeds 4 11)); LG=($(seeds 4 11)) ;;
  full)  SM=($(seeds 4 43)); LG=($(seeds 4 23)) ;;
  *) echo "stage must be pilot or full"; exit 2 ;;
esac
echo "$(date '+%Y-%m-%d %H:%M %Z') $STAGE launch, code $(git rev-parse --short HEAD), host $(hostname), cap \$$CAP_USD" >> $D/commit.txt

lane() {  # arm profile mode sizes seeds tag
  local f=$L/$1-$6.json
  local res; [ -f "$f" ] && res="--resume $f" || res="--out $f"
  uv run python evals/independent/run_eval.py $P --profile $2 --modes $3 --sizes $4 \
    --seed-list $5 $res --log-dir $D/traj --plain-max-tokens 128000 2>&1 \
    | grep --line-buffered -E -- "->|\] |rror|Traceback|unknown|usage:" | sed -u "s/^/[$1 $6] /" \
    | awk -v pat="$1-$6" -v f="$f" '{print; fflush()} /-> .*(error|Error)/{e++} /-> score/ && !/error/{e=0}
        e>=3{print "WATCHDOG: 3 consecutive errors in " pat "; lane stopped"; fflush(); system("pkill -f \"" f "\""); exit 1}'
}

guard() {  # stop every lane once the upper-bound spend reaches the cap
  while sleep 60; do
    if ! python3 $K/cost.py $L "$CAP_USD" > $D/spend.txt; then
      echo "COST GUARD: $(cat $D/spend.txt); stopping all lanes"
      pkill -f "[r]un_eval.py $P"; touch $D/STOPPED_BY_COST_GUARD; return
    fi
  done
}

quarantine() {
  python3 - "$L" "$D/quarantine" <<'PY'
import json,sys,glob,os,time
L,Q=sys.argv[1],sys.argv[2]; moved=0
for f in sorted(glob.glob(f"{L}/*.json")):
    d=json.load(open(f)); bad=[r for r in d["rows"] if r.get("error") or r.get("stop_reason")=="error"]
    if not bad: continue
    d["rows"]=[r for r in d["rows"] if r not in bad]
    q=f"{Q}/{os.path.basename(f)[:-5]}.errors-{time.strftime('%Y%m%dT%H%M%S')}.json"
    json.dump({"meta":d.get("meta"),"rows":bad},open(q,"w"),indent=1)
    json.dump(d,open(f,"w"),indent=1); moved+=len(bad)
print(moved)
PY
}

guard & GUARD=$!
trap 'kill $GUARD 2>/dev/null' EXIT
for pass in 1 2 3 4; do
  [ -f $D/STOPPED_BY_COST_GUARD ] && break
  echo "=== pass $pass $(date '+%m-%d %H:%M')"
  PIDS=()
  for i in 0 1 2 3; do
    lane rlm       gpt5-rlm   rlm       small,medium ${SM[$i]} sm$i & PIDS+=($!)
    lane plain     gpt5-plain plain     small,medium ${SM[$i]} sm$i & PIDS+=($!)
    lane rlm       gpt5-rlm   rlm       large        ${LG[$i]} lg$i & PIDS+=($!)
    lane plain     gpt5-plain plain     large        ${LG[$i]} lg$i & PIDS+=($!)
    lane mapreduce gpt5-plain mapreduce large        ${LG[$i]} lg$i & PIDS+=($!)
  done
  wait "${PIDS[@]}"
  n=$(quarantine); echo "=== pass $pass done $(date '+%m-%d %H:%M'): $n error rows quarantined"
  python3 $K/cost.py $L
  [ "$n" = "0" ] && break
  sleep 300
done

python3 - "$L" "$D" <<'PY'
import json,sys,glob
L,D=sys.argv[1],sys.argv[2]
for arm in ("rlm","plain","mapreduce"):
    rows=[];meta=None
    for f in sorted(glob.glob(f"{L}/{arm}-*.json")):
        d=json.load(open(f)); meta=meta or d.get("meta"); rows+=d["rows"]
    json.dump({"meta":meta,"rows":rows},open(f"{D}/{arm}.json","w"),indent=1)
    print(arm,len(rows),"rows")
PY
[ -f $D/STOPPED_BY_COST_GUARD ] && echo "GPT5 STOPPED BY COST GUARD $(date '+%m-%d %H:%M')" || echo "GPT5DONE $STAGE $(date '+%m-%d %H:%M')"
