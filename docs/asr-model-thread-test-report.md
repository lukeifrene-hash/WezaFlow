# ASR Model and Thread Test Report

Report date: 2026-05-11

This report summarizes the LocalFlow ASR benchmark artifacts in `artifacts/benchmarks/`
and the relevant live runtime timing logs in `artifacts/logs/runtime.jsonl`.

## Executive Summary

- Best current default: `small.en`, `int8`, CPU, 2 threads.
- Best raw speed from the tested small model configs: `small.en`, 6 threads.
- Best smoothness tradeoff: `small.en`, 2 threads. It is slower than 4 or 6 threads, but it uses far less CPU and preserves the same measured word accuracy on the benchmark pack.
- Higher quality models did not win on the current benchmark pack. `medium.en`, `distil-large-v3`, and `large-v3-turbo` were much slower, used more memory, and did not improve the measured word error rate in these samples.
- GPU metrics were collected by the benchmark schema, but the recorded runs have no GPU readings. All meaningful numbers here are CPU runs.
- CPU percent can exceed 100%. The benchmark records process CPU across logical cores, so around 600% means roughly six logical cores busy during transcription.

## Source Artifacts

| File | Purpose | Rows |
|---|---|---:|
| `artifacts/benchmarks/asr_current.jsonl` | Older current-config baseline on `artifacts/test.wav` | 2 |
| `artifacts/benchmarks/asr_resource_check.jsonl` | Older current-config baseline with CPU and memory tracking | 1 |
| `artifacts/benchmarks/asr_thread_sweep.jsonl` | First large-v3-turbo thread sweep, 8/12/16 threads | 3 |
| `artifacts/benchmarks/asr_smoothness_cpu.jsonl` | large-v3-turbo CPU smoothness sweep, 4/6/8/12 threads | 8 |
| `artifacts/benchmarks/asr_model_first_pass.jsonl` | First turbo vs distil comparison on `artifacts/test.wav` | 4 |
| `artifacts/benchmarks/asr_voice_model_compare.jsonl` | Repeated turbo vs distil comparison on the user voice pack | 16 |
| `artifacts/benchmarks/asr_voice_model_size_first_pass.jsonl` | First voice-pack model-size comparison | 16 |
| `artifacts/benchmarks/asr_small_thread_sweep.jsonl` | `small.en` thread sweep, 2/4/6 threads | 12 |
| `artifacts/benchmarks/asr_manifest_smoke.jsonl` | Manifest benchmark smoke test | 1 |

## Metrics

- `Avg ms`: average ASR transcription wall-clock time.
- `Best ms` and `Worst ms`: fastest and slowest run in that group.
- `Avg RTF`: real-time factor. Lower is faster. `0.5` means the model processed twice as fast as audio duration.
- `Avg WER`: word error rate against the benchmark expected transcript. Lower is better.
- `Avg acc`: word accuracy, calculated as `1 - WER`. Higher is better.
- `Avg CPU %`: average process CPU utilization during transcription.
- `Avg CPU ms`: CPU time consumed by the process.
- `Peak MB`: peak process memory observed during the run.

## Model Size Comparison

Source: `artifacts/benchmarks/asr_voice_model_size_first_pass.jsonl`

Voice-pack samples: `short`, `long`, `coding`, `correction`. One run per sample.

| Config | Model | Threads | Runs | Avg ms | Best ms | Worst ms | Avg RTF | Avg WER | Avg acc | Avg CPU % | Avg CPU ms | Peak MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `small_en6` | `small.en` | 6 | 4 | 1303 | 1149 | 1428 | 0.210 | 0.099 | 0.901 | 619.1 | 8914 | 805.5 |
| `medium_en6` | `medium.en` | 6 | 4 | 3758 | 3337 | 4139 | 0.607 | 0.117 | 0.883 | 606.1 | 23527 | 1393.9 |
| `distil6` | `distil-large-v3` | 6 | 4 | 5025 | 4931 | 5219 | 0.839 | 0.117 | 0.883 | 603.7 | 30625 | 1468.5 |
| `turbo6` | `large-v3-turbo` | 6 | 4 | 5100 | 5024 | 5246 | 0.850 | 0.135 | 0.865 | 602.3 | 31703 | 1520.0 |

Result: `small.en` was fastest, smallest in memory, and had the best measured WER on this benchmark pack.

## Turbo vs Distil Repeated Voice Comparison

Source: `artifacts/benchmarks/asr_voice_model_compare.jsonl`

Voice-pack samples: `short`, `long`, `coding`, `correction`. Two runs per sample.

| Config | Model | Threads | Runs | Avg ms | Best ms | Worst ms | Avg RTF | Avg WER | Avg acc | Avg CPU % | Avg CPU ms | Peak MB |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `distil6` | `distil-large-v3` | 6 | 8 | 5288 | 5168 | 5399 | 0.874 | 0.117 | 0.883 | 596.8 | 32515 | 1435.1 |
| `turbo6` | `large-v3-turbo` | 6 | 8 | 5406 | 5312 | 5522 | 0.894 | 0.135 | 0.865 | 596.2 | 33052 | 1487.0 |

Result: `distil-large-v3` was slightly faster and slightly more accurate than `large-v3-turbo` in this specific repeated test, but both were far slower than `small.en`.

## First Turbo vs Distil Smoke

Source: `artifacts/benchmarks/asr_model_first_pass.jsonl`

Sample: `artifacts/test.wav`. Two runs per model. No WER was available because this file did not include expected-text scoring.

| Config | Model | Threads | Runs | Avg ms | Best ms | Worst ms | Avg RTF | Avg CPU % | Avg CPU ms | Peak MB | Text |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `distil6` | `distil-large-v3` | 6 | 2 | 3812 | 3810 | 3813 | 1.294 | 598.3 | 23984 | 1448.1 | `I went in eating` |
| `turbo6` | `large-v3-turbo` | 6 | 2 | 4016 | 3938 | 4093 | 1.364 | 601.5 | 24882 | 1479.3 | `I went in eating` |

Result: on this early smoke sample, distil was slightly faster than turbo. The sample is too small to use for a product decision.

## small.en Thread Sweep

Source: `artifacts/benchmarks/asr_small_thread_sweep.jsonl`

Voice-pack samples: `short`, `long`, `coding`, `correction`. One run per sample.

| Config | Model | Threads | Runs | Avg ms | Best ms | Worst ms | Avg RTF | Avg WER | Avg acc | Avg CPU % | Avg CPU ms | Peak MB | Impact |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `small2` | `small.en` | 2 | 4 | 2461 | 2294 | 2656 | 0.401 | 0.099 | 0.901 | 195.9 | 5164 | 778.3 | low |
| `small4` | `small.en` | 4 | 4 | 1622 | 1487 | 1769 | 0.264 | 0.099 | 0.901 | 408.4 | 7148 | 671.8 | medium |
| `small6` | `small.en` | 6 | 4 | 1313 | 1191 | 1441 | 0.213 | 0.099 | 0.901 | 622.4 | 8960 | 779.1 | medium |

Result: all three thread counts had the same measured WER. The choice is therefore a product-feel decision:

- `small2`: lowest CPU pressure and best for "runs smoothly while I keep working".
- `small4`: good optional "snappier" mode.
- `small6`: fastest, but uses much more CPU for only about 309 ms over `small4` and about 1148 ms over `small2`.

## large-v3-turbo Thread Sweep

Source: `artifacts/benchmarks/asr_smoothness_cpu.jsonl`

Sample: `artifacts/test.wav`. Two runs per thread count.

| Config | Model | Threads | Runs | Avg ms | Best ms | Worst ms | Avg RTF | Avg CPU % | Avg CPU ms | Peak MB | Impact |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `threads4` | `large-v3-turbo` | 4 | 2 | 4478 | 4472 | 4484 | 1.521 | 398.9 | 18054 | 1478.1 | medium |
| `threads6` | `large-v3-turbo` | 6 | 2 | 3966 | 3920 | 4011 | 1.347 | 597.4 | 24695 | 1484.0 | medium |
| `threads8` | `large-v3-turbo` | 8 | 2 | 3733 | 3707 | 3759 | 1.268 | 793.8 | 30828 | 1493.8 | high |
| `threads12` | `large-v3-turbo` | 12 | 2 | 3632 | 3599 | 3666 | 1.234 | 1187.5 | 44624 | 1497.1 | high |

Result: more threads improved latency, but with steep CPU cost. For the larger model, 6 threads looked like the best engineering compromise. However, this is no longer the preferred default because `small.en` won the model comparison.

## Older large-v3-turbo Thread Smoke

Source: `artifacts/benchmarks/asr_thread_sweep.jsonl`

Sample: `artifacts/test.wav`. One run per thread count.

| Config | Model | Threads | Runs | Avg ms | Avg RTF | Text |
|---|---|---:|---:|---:|---:|---|
| `t12` | `large-v3-turbo` | 12 | 1 | 4107 | 1.395 | `I went in eating` |
| `t8` | `large-v3-turbo` | 8 | 1 | 4533 | 1.540 | `I went in eating` |
| `t16` | `large-v3-turbo` | 16 | 1 | 4646 | 1.578 | `I went in eating` |

Result: this first smoke run was noisy and less useful than the later smoothness sweep. It still showed that "more threads" is not automatically better.

## Current Baseline and Resource Checks

Sources: `artifacts/benchmarks/asr_current.jsonl`, `artifacts/benchmarks/asr_resource_check.jsonl`, and `artifacts/benchmarks/asr_manifest_smoke.jsonl`

| Test | Model | Threads | Runs | Avg ms | Avg RTF | Avg CPU % | Peak MB | Text |
|---|---|---:|---:|---:|---:|---:|---:|---|
| current baseline | `large-v3-turbo` | 12 | 2 | 4226 | 1.435 | - | - | `I went in eating` |
| resource check | `large-v3-turbo` | 12 | 1 | 4252 | 1.444 | 1109.6 | 1472.0 | `I went in eating` |
| manifest smoke | `large-v3-turbo` | 6 | 1 | 5237 | 1.779 | 600.7 | 1468.6 | `I went in eating` |

Result: these were useful instrumentation checks, but they are weaker decision inputs than the voice-pack tests.

## Model Cache Footprint

Measured from the local Hugging Face cache.

| Model cache | Size MB |
|---|---:|
| `Systran/faster-whisper-small.en` | 463.6 |
| `Systran/faster-whisper-medium.en` | 1459.6 |
| `Systran/faster-distil-whisper-large-v3` | 1446.2 |
| `mobiuslabsgmbh/faster-whisper-large-v3-turbo` | 1546.5 |

Result: `small.en` is roughly one third the disk footprint of the larger models.

## Live Runtime Timing Snapshot

Source: `artifacts/logs/runtime.jsonl`

These are not controlled benchmark runs. They are useful because they measure the real runner path: hotkey, mic recording, VAD, ASR, formatting, and paste injection.

Recent low-impact live successes used:

- profile: `low-impact`
- model: `small.en`
- compute: `int8`
- CPU threads: 2
- speculative ASR: disabled

Latest visible low-impact successes:

| Timestamp UTC | Recording ms | Total ms | ASR ms | Raw chars |
|---|---:|---:|---:|---:|
| 2026-05-11T07:10:29Z | 1535 | 2917 | 2778 | 14 |
| 2026-05-11T07:13:50Z | 6035 | 3017 | 2862 | 40 |
| 2026-05-11T07:16:02Z | 2762 | 3152 | 3005 | 14 |
| 2026-05-11T07:18:42Z | 8405 | 3348 | 3168 | 50 |
| 2026-05-11T07:20:13Z | 20114 | 4622 | 4403 | 183 |
| 2026-05-11T07:38:33Z | 5249 | 3292 | 3145 | 67 |

Observed feel: live end-to-end latency is still commonly around 3 seconds on this machine, even though the isolated `small.en` benchmark is much faster. That suggests the next performance work should focus on runner-path latency, model warm state, audio chunk handling, and possibly faster incremental/streaming architecture rather than simply picking a larger model.

## Decision Record

1. Keep `low-impact` as the default profile for now:
   - `small.en`
   - `int8`
   - CPU
   - 2 threads
   - no speculation by default

2. Keep `small.en`, 4 threads as the likely next optional "snappy" profile:
   - Same measured WER as 2 threads.
   - About 839 ms faster than 2 threads on the benchmark pack.
   - About double the CPU pressure.

3. Do not make `medium.en`, `distil-large-v3`, or `large-v3-turbo` the default yet:
   - They are slower on our benchmark pack.
   - They use much more memory and disk.
   - They did not improve the current measured WER.

4. Treat quality work as infrastructure work next:
   - Better formatting/backtrack behavior.
   - Developer vocabulary and casing.
   - Context-aware replacements.
   - More representative benchmark samples.
   - Optional quality fallback only when confidence is low or the user explicitly asks for quality.

## Recommended Next Tests

1. Add a live runner timing report command that summarizes the last N dictations by profile, model, and thread count.
2. Add benchmark rows for the active runner profiles directly: `low-impact`, `balanced`, and `quality`.
3. Add a `small.en` 4-thread live profile and compare live end-to-end feel against 2 threads.
4. Add process priority and background-load tests to measure whether LocalFlow stays pleasant while the user is using other apps.
5. Add a quality-focused benchmark pack with developer phrases, corrections, casing, punctuation, browser text fields, and editor commands.

## Caveats

- The benchmark pack is still small. It is good enough for direction, not final product proof.
- WER is word-based and does not fully capture developer quality. Casing, symbol names, function names, punctuation, and smart formatting need separate scoring.
- The isolated ASR benchmark is faster than the live runner path. That gap is now one of the most important engineering targets.
- GPU numbers are not available in these artifacts, so no GPU conclusion should be drawn from this report.
