# Independent eval tasks (Flatline Roundtable, non-Anthropic lanes)

These task generators were written by models that had nothing to do with building
ReCLamO-Harness. The harness, its prompt and its own tests were written by Claude models
(Opus orchestrating, Fable implementing). Those tests were also designed by the same
authors as the prompt, so they likely overstate what the harness can do (see
[#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22)).

To get tests we did not write, the brief in [`BRIEF.md`](BRIEF.md) went on 2026-10-07 to
the eight non-Anthropic lanes of CJ's Flatline Roundtable. They ran one lane at a time.
Each lane saw only the brief: no repo, no harness prompt, no other lane's answer. The CLI
lanes ran from an empty directory, which was still empty afterwards. One lane was
excluded. **Proteus** runs Qwen 3.7 Flash, the same model family as the system under
test, so its task could favour Qwen.

## What is here

| Path | Contents |
|---|---|
| `BRIEF.md` | The exact brief every lane received |
| `answers/<lane>.md` | Each lane's full response, verbatim (task description and code) |
| `generators/<lane>.py` | The Python block extracted from that response, **byte-for-byte unmodified** |
| `manifest.json` | Provenance (vendor, model, harness), sha256 of each generator, sizes, status |
| `validate.py` | The validator used: runs each generator's self-test and checks it in a no-network container |
| `validation-report.json` | Raw validator output |

The generators are kept exactly as delivered, defects included. That is what makes them
independent. If we repair one, the repaired copy goes in a separate file with a diff and
a note, and the original stays here unchanged.

## Status

The validator checks these things for every generator:

- its own `__main__` self-test passes;
- sizes are about 60K, 300K and 1.2M characters;
- output is the same for the same seed and changes with the seed, both within one process
  and across separate processes;
- `score(truth) == 1` and `score("") == 0`.

It runs everything in `python:3.12-slim` with `--network none`, as a non-root user, on a
read-only filesystem.

| Lane | Model | Task | Status |
|---|---|---|---|
| GLaDOS | xAI grok-4.6 | Transit co-op records: net authorized amount and certifying member for the current legal successor of a renamed project, under bylaws and SOP | **pass** |
| SHODAN | OpenAI gpt-6-astra | Month-end packet: per-office freight credits after signed corrections, custody findings and agreement terms | **pass** |
| TheDixieFlatline | Google gemini-3.1-pro-high | Chain of custody: final room of an asset through renames and transfers (medium size ≈260K) | **pass** |
| Cerebex | Z-AI glm-5.3-flash | Expense emails: travel total after amendments and reversals | defect: `score()` accepts a deliberately wrong answer |
| Neuromancer | DeepSeek v4-flash | March travel reimbursed after adjustments and denials | defect: small size degenerates to $0; lenient scorer |
| SELMA | NVIDIA Nemotron 3 Super | Final owner of a review after reassignments in an email thread | defect: output depends on `PYTHONHASHSEED` |
| MasterControl | Mistral Medium 3.1 | Only employee flagged for two audit issues, plus their total | defect: scorer gives its own truth 0.5 |
| Multivac | Nous Hermes 4 405B | Requirement status after merges and splits | defect: contexts 2.7K / 6K / 16K chars |

Only the **pass** generators feed headline results. The others are recorded because a
lane's failure to follow the brief is itself data about that lane.

## Running

```sh
# Validate (needs Docker; the directory must be one Docker Desktop can mount)
python3 evals/independent/validate.py evals/independent/answers ~/.cache/reclamo/rtgen

# Use a generator directly
python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('g', 'evals/independent/generators/SHODAN.py')
g = importlib.util.module_from_spec(spec); sys.modules['g'] = g; spec.loader.exec_module(g)
d = g.generate(0, 'medium'); print(len(d['context']), d['question']); print(d['answer'])
"
```

Running these against the harness and the plain model is tracked in
[#22](https://github.com/CryptoJones/ReCLamO-Harness/issues/22). The prompt and defaults
are frozen before that run, with no tuning on these tasks.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
