#!/bin/bash
# H1 on a second model: Laguna S 2.1 (issue #116, TEST-PLAN 1i).
# Harness v0.1 32K vs plain v0.2 128K, small+medium, all 8 tasks, seeds 4-43.
# 4 seed lanes per arm in parallel (run_eval runs rows one at a time), each lane its own file.
# Error rows are moved to a side file and re-run (up to 3 passes); then lanes merge into
# runs/exp-laguna/{h-v01-32k,plain-131k}.json for paper/analysis/h1_analysis.py.
set -u
cd ~/source/repos/ReCLamO-Harness-laguna
D=runs/exp-laguna; L=$D/lanes; mkdir -p $L $D/traj $D/quarantine
P="--profiles $D/profiles.toml"
LANES=("4,5,6,7,8,9,10,11,12,13" "14,15,16,17,18,19,20,21,22,23" "24,25,26,27,28,29,30,31,32,33" "34,35,36,37,38,39,40,41,42,43")
echo "$(date '+%Y-%m-%d %H:%M %Z') launch, code $(git rev-parse --short HEAD), host $(hostname)" >> $D/commit.txt

lane() {  # arm-name profile prompt mode seeds idx
  local f=$L/$1-L$6.json
  local res=""; [ -f $f ] && res="--resume $f" || res="--out $f"
  uv run python evals/independent/run_eval.py $P --profile $2 --prompt-version $3 --modes $4 \
    --sizes small,medium --seed-list $5 $res --log-dir $D/traj 2>&1 \
    | grep --line-buffered -E -- "->|\] |rror" | sed -u "s/^/[$1 L$6] /" \
    | awk -v pat="$1-L$6" -v f="$f" '{print; fflush()} /-> .*(error|Error)/{e++} /-> score/ && !/error/{e=0}
        e>=3{print "WATCHDOG: 3 consecutive errors in " pat "; lane stopped"; fflush(); system("pkill -f \"" f "\""); exit 1}'
}

quarantine() {  # move error rows out of every lane file; print how many were moved
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

for pass in 1 2 3 4; do
  echo "=== pass $pass $(date '+%m-%d %H:%M')"
  for i in 0 1 2 3; do
    lane h-v01-32k  laguna-32k  v0.1 rlm   ${LANES[$i]} $i &
    lane plain-131k laguna-128k v0.2 plain ${LANES[$i]} $i &
  done
  wait
  n=$(quarantine); echo "=== pass $pass done $(date '+%m-%d %H:%M'): $n error rows quarantined"
  [ "$n" = "0" ] && break
  sleep 300
done

python3 - "$L" "$D" <<'PY'
import json,sys,glob
L,D=sys.argv[1],sys.argv[2]
for arm in ("h-v01-32k","plain-131k"):
    rows=[];meta=None
    for f in sorted(glob.glob(f"{L}/{arm}-L*.json")):
        d=json.load(open(f)); meta=meta or d.get("meta"); rows+=d["rows"]
    json.dump({"meta":meta,"rows":rows},open(f"{D}/{arm}.json","w"),indent=1)
    print(arm,len(rows),"rows (want 640)")
PY
echo LAGUNADONE $(date '+%m-%d %H:%M')
