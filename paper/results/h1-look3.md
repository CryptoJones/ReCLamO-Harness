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
| primary: every pair counts | primary | 320 | 177 | 162 | 31 | 16 | +2.188 | 0.0400 | yes |
| secondary: plain does_not_fit pairs dropped | secondary | 280 | 173 | 162 | 27 | 16 | +1.677 | 0.1263 | no |
| sensitivity: plain length rows dropped | sensitivity | 276 | 174 | 162 | 28 | 16 | +1.809 | 0.0961 | no |
| sensitivity: harness turn-cap/timeout rows dropped | sensitivity | 202 | 156 | 138 | 28 | 10 | +2.920 | 0.0051 | yes |
| sensitivity: both arms finished | sensitivity | 197 | 152 | 138 | 24 | 10 | +2.401 | 0.0243 | yes |

### Task-clustered paired bootstrap (primary set)

- exact-rate difference A-B: +0.047, 95% CI [-0.047, 0.163] (8 task clusters, 10000 resamples)
- mean-score difference A-B: +0.057, 95% CI [-0.042, 0.177]

### GLMM: logit(exact) ~ arm + (1 | task)

- arm (harness vs plain): beta +0.543, SE 0.272, Wald z +1.99, p 0.0462, odds ratio 1.72; task SD 3.17; 640 answers in 8 tasks

### Leave-one-task-out (primary)

| dropped | n | A exact | B exact | b | c | z | exact p | diff |
|---|---|---|---|---|---|---|---|---|
| Cerebex | 280 | 148 | 127 | 30 | 9 | +3.363 | 0.0011 | +0.075 |
| GLaDOS | 280 | 173 | 162 | 27 | 16 | +1.677 | 0.1263 | +0.039 |
| MasterControl | 280 | 137 | 122 | 31 | 16 | +2.188 | 0.0400 | +0.054 |
| Multivac | 280 | 145 | 130 | 26 | 11 | +2.466 | 0.0201 | +0.054 |
| Neuromancer | 280 | 145 | 145 | 13 | 13 | +0.000 | 1.0000 | +0.000 |
| SELMA | 280 | 138 | 125 | 28 | 15 | +1.982 | 0.0660 | +0.046 |
| SHODAN | 280 | 177 | 162 | 31 | 16 | +2.188 | 0.0400 | +0.054 |
| TheDixieFlatline | 280 | 176 | 161 | 31 | 16 | +2.188 | 0.0400 | +0.054 |

### Minimum detectable effect (80% power, observed discordance 0.147)

- look 1 (112 pairs): 0.156 in exact-rate difference
- look 2 (216 pairs): 0.086 in exact-rate difference
- look 3 (320 pairs): 0.061 in exact-rate difference
- at the observed n with this look's boundary: 0.061

### Per task

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| Cerebex | 40 | 29 | 35 | 1 | 7 | -2.121 | 0.0703 |
| GLaDOS | 40 | 4 | 0 | 4 | 0 | +2.000 | 0.1250 |
| MasterControl | 40 | 40 | 40 | 0 | 0 | +0.000 | 1.0000 |
| Multivac | 40 | 32 | 32 | 5 | 5 | +0.000 | 1.0000 |
| Neuromancer | 40 | 32 | 17 | 18 | 3 | +3.273 | 0.0015 |
| SELMA | 40 | 39 | 37 | 3 | 1 | +1.000 | 0.6250 |
| SHODAN | 40 | 0 | 0 | 0 | 0 | +0.000 | 1.0000 |
| TheDixieFlatline | 40 | 1 | 1 | 0 | 0 | +0.000 | 1.0000 |

### Per generator author

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| deepseek / deepseek-v4-flash | 40 | 32 | 17 | 18 | 3 | +3.273 | 0.0015 |
| google / gemini-3.1-pro-high | 40 | 1 | 1 | 0 | 0 | +0.000 | 1.0000 |
| mistral / mistral-medium-3.1 | 40 | 40 | 40 | 0 | 0 | +0.000 | 1.0000 |
| nousresearch / hermes-4-405b | 40 | 32 | 32 | 5 | 5 | +0.000 | 1.0000 |
| nvidia / nemotron-3-super-120b-a12b:free | 40 | 39 | 37 | 3 | 1 | +1.000 | 0.6250 |
| openai / gpt-6-astra | 40 | 0 | 0 | 0 | 0 | +0.000 | 1.0000 |
| xai / grok-4.6 | 40 | 4 | 0 | 4 | 0 | +2.000 | 0.1250 |
| z-ai / glm-5.3-flash | 40 | 29 | 35 | 1 | 7 | -2.121 | 0.0703 |

### Per evidence position

Position = the third of the context holding the answer's last literal mention; 'computed' = the answer never appears verbatim (sums, tallies). Where a task's position never varies across seeds this regroups tasks, so read it beside the per-task table.

| group | n | A exact | B exact | b | c | z | exact p |
|---|---|---|---|---|---|---|---|
| computed | 120 | 61 | 52 | 19 | 10 | +1.671 | 0.1360 |
| first third | 76 | 71 | 68 | 4 | 1 | +1.342 | 0.3750 |
| last third | 109 | 44 | 42 | 7 | 5 | +0.577 | 0.7744 |
| middle third | 15 | 1 | 0 | 1 | 0 | +1.000 | 1.0000 |

### Completion, cost and latency

| arm | n | finished | completion | s p50 | s p95 | prompt tok | completion tok | sub-calls | turns |
|---|---|---|---|---|---|---|---|---|---|
| harness | 320 | 202 | 0.63 | 421 | 1532 | 79788 | 6201 | 0.55 | 14.62 |
| plain | 320 | 236 | 0.74 | 580 | 1385 | 79905 | 5617 | 0.00 | 1.00 |

### Failure taxonomy

| category | harness | plain |
|---|---|---|
| answered | 202 | 236 |
| forced finish: time limit | 7 | 0 |
| forced finish: turn cap | 111 | 0 |
| not_run: does_not_fit | 0 | 40 |
| output-length cap | 0 | 44 |

## A/A noise floor: plain-32K vs plain-128K at small

- 64 cells, 56 where both fit; exactness differs on 10 (0.179). Identical input, identical model: this is the per-row noise any paired delta must clear.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
