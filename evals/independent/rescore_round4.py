"""Re-score a run file with the round-4 candidate scorers into a NEW file (issue #95).

    uv run python evals/independent/rescore_round4.py runs/exp-v02/plain-131k.json \\
        --out runs/exp-v02/rescored-round4/plain-131k.json

The recorded run files are never written. ``run_eval.py`` is untouched: this wrapper builds
a manifest view whose ``active`` entry per lane is the ``round4`` entry (file + sha256) and
hands it to ``run_eval.rescore_rows``. Every row keeps ``old_score`` and gets ``new_score``;
the file's ``meta.rescored`` names the scorer set and its sha256s. Rows whose stored answer
hit the 2,000-character cap are left at their recorded score and flagged
``rescore_skipped`` (the scorer saw text that is gone); the summary counts them.

Until CJ approves TEST-PLAN section 1d this is a diagnostic, not a result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402

SET = "round4"


def round4_manifest(manifest: dict, root: Path = HERE) -> dict:
    """The manifest with each lane's ``active`` replaced by its ``round4`` entry."""
    view = json.loads(json.dumps(manifest))
    for lane in run_eval.LANES:
        entry = view["generators"][lane].get(SET)
        if entry is None:  # not yet listed: pin to the file on disk
            path = root / "fixed" / SET / f"{lane}.py"
            entry = {
                "file": str(path.relative_to(root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source": f"{SET} candidate (unlisted in manifest.json)",
            }
        view["generators"][lane]["active"] = entry
    return view


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_file")
    p.add_argument("--out", required=True, help="new file; must differ from the input")
    args = p.parse_args(argv)
    src, out = Path(args.run_file), Path(args.out)
    if out.resolve() == src.resolve():
        print("rescore_round4: --out must be a new file", file=sys.stderr)
        return 2
    manifest = round4_manifest(run_eval.load_manifest())
    data = json.loads(src.read_text(encoding="utf-8"))
    meta, rows = data.get("meta", {}), data.get("rows", [])
    changed = run_eval.rescore_rows(rows, run_eval.Generators(manifest))
    skipped = sum("rescore_skipped" in r for r in rows)
    meta = {
        **meta,
        "rescored": {
            "from": str(src),
            "at": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
            "scorer_set": SET,
            "status": "diagnostic until TEST-PLAN 1d is approved",
            "rows_changed": changed,
            "rows_skipped_truncated": skipped,
            f"{SET}_sha256": {
                lane: manifest["generators"][lane]["active"]["sha256"] for lane in run_eval.LANES
            },
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    run_eval.write_rows(out, meta, rows)
    summary = run_eval.format_summary(rows, manifest)
    out.with_suffix(".md").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    print(f"\n{changed} row(s) changed, {skipped} skipped (truncated answer)\nrows: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
