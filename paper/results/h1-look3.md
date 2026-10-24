# H1 analysis: harness v0.1 32K vs plain-128K (seeds 4+; runs/exp-v02/rescored-round4)

Look 3, boundary |z| > 2.004. Pairs on (task, seed); A = harness, B = plain; b = A right / B wrong, c = A wrong / B right.

## small

### Exclusion sets (decision 9)

| set | kind | n | A exact | B exact | b | c | z | exact p | crossed |
|---|---|---|---|---|---|---|---|---|---|
| primary: every pair counts | primary | 320 | 203 | 229 | 22 | 48 | -3.108 | 0.0025 | yes |
| secondary: plain does_not_fit pairs dropped | secondary | 320 | 203 | 229 | 22 | 48 | -3.108 | 0.0025 | yes |
| sensitivity: plain length rows dropped | sensitivity | 320 | 203 | 229 | 22 | 48 | -3.108 | 0.0025 | yes |
| sensitivity: harness turn-cap/timeout rows dropped | sensitivity | 228 | 178 | 174 | 15 | 11 | +0.784 | 0.5572 | no |
| sensitivity: both arms finished | sensitivity | 228 | 178 | 174 | 15 | 11 | +0.784 | 0.5572 | no |

### Task-clustered paired bootstrap (primary set)

- exact-rate difference A-B: -0.081, 95% CI [-0.294, 0.072] (8 task clusters, 10000 resamples)
- mean-score difference A-B: -0.100, 95% CI [-0.303, 0.031]

### GLMM: logit(exact) ~ arm + (1 | task)

- arm (harness vs plain): beta -0.771, SE 0.250, Wald z -3.09, p 0.0020, odds ratio 0.46; task SD 1.98; 640 answers in 8 tasks

### Leave-one-task-out (primary)

| dropped | n | A exact | B exact | b | c | z | exact p | diff |
|---|---|---|---|---|---|---|---|---|
| Cerebex | 280 | 166 | 191 | 20 | 45 | -3.101 | 0.0026 | -0.089 |
| GLaDOS | 280 | 184 | 218 | 10 | 44 | -4.627 | 0.0000 | -0.121 |
| MasterControl | 280 | 164 | 189 | 22 | 47 | -3.010 | 0.0035 | -0.089 |
| Multivac | 280 | 171 | 192 | 21 | 42 | -2.646 | 0.0111 | -0.075 |
| Neuromancer | 280 | 168 | 195 | 19 | 46 | -3.349 | 0.0011 | -0.096 |
| SELMA | 280 | 164 | 193 | 19 | 48 | -3.543 | 0.0005 | -0.104 |
| SHODAN | 280 | 201 | 197 | 21 | 17 | +0.649 | 0.6271 | +0.014 |
| TheDixieFlatline | 280 | 203 | 228 | 22 | 47 | -3.010 | 0.0035 | -0.089 |

### Minimum detectable effect (80% power, observed discordance 0.219)

- look 1 (112 pairs): 0.191 in exact-rate difference
- look 2 (216 pairs): 0.105 in exact-rate difference
- look 3 (320 pairs): 0.074 in exact-rate difference
- at the observed n with this look's boundary: 0.074

### Per task

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| Cerebex | 40 | 37 | 38 | 2 | 3 | -0.447 | 1.0000 |
| GLaDOS | 40 | 19 | 11 | 12 | 4 | +2.000 | 0.0768 |
| MasterControl | 40 | 39 | 40 | 0 | 1 | -1.000 | 1.0000 |
| Multivac | 40 | 32 | 37 | 1 | 6 | -1.890 | 0.1250 |
| Neuromancer | 40 | 35 | 34 | 3 | 2 | +0.447 | 1.0000 |
| SELMA | 40 | 39 | 36 | 3 | 0 | +1.732 | 0.2500 |
| SHODAN | 40 | 2 | 32 | 1 | 31 | -5.303 | 0.0000 |
| TheDixieFlatline | 40 | 0 | 1 | 0 | 1 | -1.000 | 1.0000 |

### Per generator author

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| deepseek / deepseek-v4-flash | 40 | 35 | 34 | 3 | 2 | +0.447 | 1.0000 |
| google / gemini-3.1-pro-high | 40 | 0 | 1 | 0 | 1 | -1.000 | 1.0000 |
| mistral / mistral-medium-3.1 | 40 | 39 | 40 | 0 | 1 | -1.000 | 1.0000 |
| nousresearch / hermes-4-405b | 40 | 32 | 37 | 1 | 6 | -1.890 | 0.1250 |
| nvidia / nemotron-3-super-120b-a12b:free | 40 | 39 | 36 | 3 | 0 | +1.732 | 0.2500 |
| openai / gpt-6-astra | 40 | 2 | 32 | 1 | 31 | -5.303 | 0.0000 |
| xai / grok-4.6 | 40 | 19 | 11 | 12 | 4 | +2.000 | 0.0768 |
| z-ai / glm-5.3-flash | 40 | 37 | 38 | 2 | 3 | -0.447 | 1.0000 |

### Per evidence position

Position = the third of the context holding the answer's last literal mention; 'computed' = the answer never appears verbatim (sums, tallies). Where a task's position never varies across seeds this regroups tasks, so read it beside the per-task table.

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| computed | 120 | 74 | 104 | 6 | 36 | -4.629 | 0.0000 |
| first third | 72 | 64 | 62 | 3 | 1 | +1.000 | 0.6250 |
| last third | 114 | 60 | 60 | 10 | 10 | +0.000 | 1.0000 |
| middle third | 14 | 5 | 3 | 3 | 1 | +1.000 | 0.6250 |

### Completion, cost and latency

| arm | n | finished | completion | s p50 | s p95 | prompt tok | completion tok | sub-calls | turns |
|---|---|---|---|---|---|---|---|---|---|
| harness | 320 | 228 | 0.71 | 398 | 1429 | 70116 | 5620 | 0.71 | 13.48 |
| plain | 320 | 320 | 1.00 | 204 | 562 | 18191 | 2866 | 0.00 | 1.00 |

### Failure taxonomy

| category | harness | plain |
|---|---|---|
| answered | 228 | 320 |
| forced finish: time limit | 5 | 0 |
| forced finish: turn cap | 87 | 0 |

## medium

### Exclusion sets (decision 9)

| set | kind | n | A exact | B exact | b | c | z | exact p | crossed |
|---|---|---|---|---|---|---|---|---|---|
| primary: every pair counts | primary | 216 | 121 | 109 | 22 | 10 | +2.121 | 0.0501 | yes |
| secondary: plain does_not_fit pairs dropped | secondary | 189 | 118 | 109 | 19 | 10 | +1.671 | 0.1360 | no |
| sensitivity: plain length rows dropped | sensitivity | 187 | 120 | 109 | 21 | 10 | +1.976 | 0.0708 | no |
| sensitivity: harness turn-cap/timeout rows dropped | sensitivity | 140 | 108 | 95 | 20 | 7 | +2.502 | 0.0192 | yes |
| sensitivity: both arms finished | sensitivity | 137 | 106 | 95 | 18 | 7 | +2.200 | 0.0433 | yes |

### Task-clustered paired bootstrap (primary set)

- exact-rate difference A-B: +0.056, 95% CI [-0.037, 0.162] (8 task clusters, 10000 resamples)
- mean-score difference A-B: +0.064, 95% CI [-0.035, 0.174]

### GLMM: logit(exact) ~ arm + (1 | task)

- arm (harness vs plain): beta +0.619, SE 0.326, Wald z +1.90, p 0.0575, odds ratio 1.86; task SD 5.51; 432 answers in 8 tasks

### Leave-one-task-out (primary)

| dropped | n | A exact | B exact | b | c | z | exact p | diff |
|---|---|---|---|---|---|---|---|---|
| Cerebex | 189 | 101 | 85 | 21 | 5 | +3.138 | 0.0025 | +0.085 |
| GLaDOS | 189 | 118 | 109 | 19 | 10 | +1.671 | 0.1360 | +0.048 |
| MasterControl | 189 | 94 | 82 | 22 | 10 | +2.121 | 0.0501 | +0.063 |
| Multivac | 189 | 100 | 90 | 17 | 7 | +2.041 | 0.0639 | +0.053 |
| Neuromancer | 189 | 99 | 96 | 11 | 8 | +0.688 | 0.6476 | +0.016 |
| SELMA | 189 | 94 | 84 | 20 | 10 | +1.826 | 0.0987 | +0.053 |
| SHODAN | 189 | 121 | 109 | 22 | 10 | +2.121 | 0.0501 | +0.063 |
| TheDixieFlatline | 189 | 120 | 108 | 22 | 10 | +2.121 | 0.0501 | +0.063 |

### Minimum detectable effect (80% power, observed discordance 0.148)

- look 1 (112 pairs): 0.157 in exact-rate difference
- look 2 (216 pairs): 0.086 in exact-rate difference
- look 3 (320 pairs): 0.061 in exact-rate difference
- at the observed n with this look's boundary: 0.075

### Per task

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| Cerebex | 27 | 20 | 24 | 1 | 5 | -1.633 | 0.2188 |
| GLaDOS | 27 | 3 | 0 | 3 | 0 | +1.732 | 0.2500 |
| MasterControl | 27 | 27 | 27 | 0 | 0 | +0.000 | 1.0000 |
| Multivac | 27 | 21 | 19 | 5 | 3 | +0.707 | 0.7266 |
| Neuromancer | 27 | 22 | 13 | 11 | 2 | +2.496 | 0.0225 |
| SELMA | 27 | 27 | 25 | 2 | 0 | +1.414 | 0.5000 |
| SHODAN | 27 | 0 | 0 | 0 | 0 | +0.000 | 1.0000 |
| TheDixieFlatline | 27 | 1 | 1 | 0 | 0 | +0.000 | 1.0000 |

### Per generator author

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| deepseek / deepseek-v4-flash | 27 | 22 | 13 | 11 | 2 | +2.496 | 0.0225 |
| google / gemini-3.1-pro-high | 27 | 1 | 1 | 0 | 0 | +0.000 | 1.0000 |
| mistral / mistral-medium-3.1 | 27 | 27 | 27 | 0 | 0 | +0.000 | 1.0000 |
| nousresearch / hermes-4-405b | 27 | 21 | 19 | 5 | 3 | +0.707 | 0.7266 |
| nvidia / nemotron-3-super-120b-a12b:free | 27 | 27 | 25 | 2 | 0 | +1.414 | 0.5000 |
| openai / gpt-6-astra | 27 | 0 | 0 | 0 | 0 | +0.000 | 1.0000 |
| xai / grok-4.6 | 27 | 3 | 0 | 3 | 0 | +1.732 | 0.2500 |
| z-ai / glm-5.3-flash | 27 | 20 | 24 | 1 | 5 | -1.633 | 0.2188 |

### Per evidence position

Position = the third of the context holding the answer's last literal mention; 'computed' = the answer never appears verbatim (sums, tallies). Where a task's position never varies across seeds this regroups tasks, so read it beside the per-task table.

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| computed | 81 | 42 | 37 | 12 | 7 | +1.147 | 0.3593 |
| first third | 52 | 49 | 46 | 3 | 0 | +1.732 | 0.2500 |
| last third | 72 | 29 | 26 | 6 | 3 | +1.000 | 0.5078 |
| middle third | 11 | 1 | 0 | 1 | 0 | +1.000 | 1.0000 |

### Completion, cost and latency

| arm | n | finished | completion | s p50 | s p95 | prompt tok | completion tok | sub-calls | turns |
|---|---|---|---|---|---|---|---|---|---|
| harness | 216 | 140 | 0.65 | 370 | 1528 | 79829 | 6296 | 0.46 | 14.62 |
| plain | 216 | 160 | 0.74 | 568 | 1362 | 79913 | 5581 | 0.00 | 1.00 |

### Failure taxonomy

| category | harness | plain |
|---|---|---|
| answered | 140 | 160 |
| forced finish: time limit | 1 | 0 |
| forced finish: turn cap | 75 | 0 |
| not_run: does_not_fit | 0 | 27 |
| output-length cap | 0 | 29 |

## A/A noise floor: plain-32K vs plain-128K at small

- 64 cells, 56 where both fit; exactness differs on 10 (0.179). Identical input, identical model: this is the per-row noise any paired delta must clear.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
