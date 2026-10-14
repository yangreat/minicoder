# MiniCoder v2 eval (PR #2 branch `cursor/eval-fixes-and-multi-agent-f2e6` @ cc3079d + local_fix.patch)

Generated: 2026-10-14 18:36 Asia/Shanghai (UTC+8); runs executed 2026-10-14 17:03–~18:45.  
Endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1. Models: `qwen3.6-plus`, `qwen-plus`. 10 toy tasks, --max-steps 15, --protect-tests block, compression presets per row.  
Pass = repo pytest passes after the run (test files restored before grading). Pass rate mean ± stdev is across repeats (each repeat = 10 tasks); steps/tokens/wall are mean ± stdev per run.  
Multi rows were run AFTER applying local_fix.patch (scheduler hang fix); single rows ran on unpatched code (the patch only touches the multi-agent scheduler path).

| model | mode | compression | runs | tests pass | pass rate (per repeat) | agent called finish | steps | total tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.6-plus | single | default | 30 | 30/30 | 100.0 ± 0.0% | 30/30 | 8.2 ± 1.9 | 16367.6 ± 6001.3 | 72.5 ± 144.7 |
| qwen3.6-plus | single | off | 30 | 30/30 | 100.0 ± 0.0% | 30/30 | 8.7 ± 2.3 | 17875.6 ± 6706.2 | 75.4 ± 143.7 |
| qwen3.6-plus | single | aggressive | 30 | 30/30 | 100.0 ± 0.0% | 26/30 | 9.4 ± 3.5 | 16989.1 ± 7344.6 | 81.3 ± 144.8 |
| qwen3.6-plus | multi | default | 30 | 22/30 | 73.3 ± 20.8% | 0/30 | 15.0 ± 0.0 | 27043.5 ± 2501.5 | 64.7 ± 70.0 |
| qwen-plus | single | default | 20 | 20/20 | 100.0 ± 0.0% | 19/20 | 10.1 ± 1.9 | 21708.7 ± 9045.6 | 103.0 ± 177.8 |
| qwen-plus | multi | default | 20 | 3/20 | 15.0 ± 7.1% | 0/20 | 15.0 ± 0.0 | 21447.8 ± 1402.5 | 28.3 ± 6.4 |

## Per-task tests pass (passes/runs)

| task | qwen3.6-plus/single/default | qwen3.6-plus/single/off | qwen3.6-plus/single/aggressive | qwen3.6-plus/multi/default | qwen-plus/single/default | qwen-plus/multi/default |
|---|---|---|---|---|---|---|
| calculator | 3/3 | 3/3 | 3/3 | 3/3 | 2/2 | 2/2 |
| csv_stats | 3/3 | 3/3 | 3/3 | 0/3 | 2/2 | 0/2 |
| fizzbuzz | 3/3 | 3/3 | 3/3 | 3/3 | 2/2 | 0/2 |
| inventory | 3/3 | 3/3 | 3/3 | 3/3 | 2/2 | 0/2 |
| lru_cache | 3/3 | 3/3 | 3/3 | 2/3 | 2/2 | 0/2 |
| palindrome | 3/3 | 3/3 | 3/3 | 2/3 | 2/2 | 0/2 |
| roman | 3/3 | 3/3 | 3/3 | 3/3 | 2/2 | 1/2 |
| text_stats | 3/3 | 3/3 | 3/3 | 3/3 | 2/2 | 0/2 |
| todo_store | 3/3 | 3/3 | 3/3 | 1/3 | 2/2 | 0/2 |
| url_join | 3/3 | 3/3 | 3/3 | 2/3 | 2/2 | 0/2 |

## Sources

- qwen3.6-plus/single/default: /workspace/minicoder-eval-v2/qwen3.6-plus_single_default/results.json
- qwen3.6-plus/single/off: /workspace/minicoder-eval-v2/qwen3.6-plus_single_off/results.json
- qwen3.6-plus/single/aggressive: /workspace/minicoder-eval-v2/qwen3.6-plus_single_aggressive/results.json
- qwen3.6-plus/multi/default: /workspace/minicoder-eval-v2/qwen3.6-plus_multi_default/log.txt (per-run lines; process died before results.json); /workspace/minicoder-eval-v2/qwen3.6-plus_multi_default_part2/results.json
- qwen-plus/single/default: /workspace/minicoder-eval-v2/qwen-plus_single_default/results.json
- qwen-plus/multi/default: /workspace/minicoder-eval-v2/qwen-plus_multi_default/results.json

## Exact commands (run from /workspace/mc2 with its venv)

```
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode single --compression default --repeats 3 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen3.6-plus_single_default
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode single --compression off --repeats 3 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen3.6-plus_single_off
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode single --compression aggressive --repeats 3 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen3.6-plus_single_aggressive
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 3 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen3.6-plus_multi_default
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode single --compression default --repeats 2 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen-plus_single_default
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 2 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen-plus_multi_default
# rerun after local_fix.patch: OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 3 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen3.6-plus_multi_default
# rerun after local_fix.patch: OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 2 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v2/qwen-plus_multi_default
# completion of interrupted qwen3.6 multi run (first process died at 24/30): OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 3 --max-steps 15 --protect-tests block --tasks todo_store,url_join --output-dir /workspace/minicoder-eval-v2/qwen3.6-plus_multi_default_part2
```

## Notes
- Local fix (local_fix.patch, src/minicoder/scheduler.py): `TaskScheduler.run_all` marked a pending subtask BLOCKED only if a dependency was FAILED. In a chain A→B→C, when A failed, B became BLOCKED but C (depending on BLOCKED B) was never marked, so `pending` never emptied and the loop spun forever on `asyncio.sleep(0.05)` with no LLM calls. Both multi runs hung this way at ~17:04 (after 1 and 2 runs; partial logs in *_multi_default_hung_before_fix/). The fix treats BLOCKED dependencies like FAILED ones. The unit tests still pass (76 passed, 2 skipped). Multi rows were re-run from scratch with the fix.
- The qwen3.6-plus multi run's process died at 24/30 when the shell that had launched it was killed (an infrastructure problem, not a MiniCoder bug). The remaining 2 tasks × 3 repeats (todo_store, url_join) were run separately into *_part2/. The first 24 records come from the per-run log lines, which don't include prompt/completion splits.
- Multi mode never called finish (0/50 runs): every run used up the shared 15-step budget across the planner subtasks (read README → read tests → locate → apply fix → verify). In the two hung runs I inspected, an early subtask ("Locate the buggy code") failed on step exhaustion and "Apply the fix" was blocked; I did not inspect the rest individually. With the same steps, single mode is clearly better here.
- Wall-time outliers (~430–700 s) all occurred during the same time windows across the parallel processes, which points to DashScope request stalls/timeouts with retries, not agent behaviour. They inflate wall-time stdev; median-like runs are 25–60 s.
- apply_patch: no corrupted-file failures were seen in single mode (100% pass). No test files were flagged/blocked in any recorded run.


---

## v3 measured regression (`425af4a`)

The following write-up is appended **verbatim** from the DashScope v3 eval of commit `425af4a`. It is a measured regression against v2: deadlock is gone, but multi-agent pass rate collapsed because read-only subtasks exhausted a 3-step budget, failed, and blocked the fix worker. Later commits on this branch address that; **do not treat these multi numbers as results for later code**. Single mode on `425af4a` still passed 10/10.

# MiniCoder v3 eval (branch `cursor/eval-fixes-and-multi-agent-f2e6` @ 425af4a, no local patches)

Generated: 2026-10-14 19:06 Asia/Shanghai (UTC+8); runs executed 2026-10-14 ~18:43–19:06.  
Endpoint: https://dashscope.aliyuncs.com/compatible-mode/v1. Models: `qwen3.6-plus`, `qwen-plus`. 10 toy tasks, --max-steps 15, --protect-tests block, compression presets per row.  
Pass = repo pytest passes after the run (test files restored before grading). Pass rate mean ± stdev is across repeats (each repeat = 10 tasks); steps/tokens/wall are mean ± stdev per run.  
| model | mode | compression | runs | tests pass | pass rate (per repeat) | agent called finish | steps | total tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.6-plus | multi | default | 30 | 2/30 | 6.7 ± 5.8% | 1/30 | 12.0 ± 1.2 | 17029.7 ± 2861.0 | 30.3 ± 24.3 |
| qwen-plus | multi | default | 20 | 0/20 | 0.0 ± 0.0% | 0/20 | 11.9 ± 0.4 | 12963.3 ± 539.7 | 14.8 ± 2.2 |
| qwen3.6-plus | single | default | 10 | 10/10 | 100.0% | 10/10 | 8.4 ± 2.2 | 16549.0 ± 5853.6 | 35.8 ± 13.0 |

## Per-task tests pass (passes/runs)

| task | qwen3.6-plus/multi/default | qwen-plus/multi/default | qwen3.6-plus/single/default |
|---|---|---|---|
| calculator | 0/3 | 0/2 | 1/1 |
| csv_stats | 0/3 | 0/2 | 1/1 |
| fizzbuzz | 1/3 | 0/2 | 1/1 |
| inventory | 0/3 | 0/2 | 1/1 |
| lru_cache | 0/3 | 0/2 | 1/1 |
| palindrome | 0/3 | 0/2 | 1/1 |
| roman | 1/3 | 0/2 | 1/1 |
| text_stats | 0/3 | 0/2 | 1/1 |
| todo_store | 0/3 | 0/2 | 1/1 |
| url_join | 0/3 | 0/2 | 1/1 |

## Sources

- qwen3.6-plus/multi/default: /workspace/minicoder-eval-v3/qwen3.6-plus_multi_default/results.json
- qwen-plus/multi/default: /workspace/minicoder-eval-v3/qwen-plus_multi_default/results.json
- qwen3.6-plus/single/default: /workspace/minicoder-eval-v3/qwen3.6-plus_single_default/results.json

## Exact commands (run from /workspace/mc2 with its venv)

```
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 3 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v3/qwen3.6-plus_multi_default
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode multi --compression default --repeats 2 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v3/qwen-plus_multi_default
OPENAI_API_KEY="$DASHSCOPE_API_KEY" python benchmarks/evaluate.py --model qwen3.6-plus --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --agent-mode single --compression default --repeats 1 --max-steps 15 --protect-tests block --output-dir /workspace/minicoder-eval-v3/qwen3.6-plus_single_default
```

## Comparison with v2 (same flags; v2 = cc3079d + local scheduler fix)

| row | v2 tests pass | v3 tests pass | v2 finish | v3 finish | v2 steps | v3 steps | v2 tokens | v3 tokens |
|---|---|---|---|---|---|---|---|---|
| qwen3.6-plus multi/default | 22/30 (73.3 ± 20.8%) | 2/30 (6.7 ± 5.8%) | 0/30 | 1/30 | 15.0 ± 0.0 | 12.0 ± 1.2 | 27,044 ± 2,502 | 17,030 ± 2,861 |
| qwen-plus multi/default | 3/20 (15.0 ± 7.1%) | 0/20 (0.0%) | 0/20 | 0/20 | 15.0 ± 0.0 | 11.9 ± 0.4 | 21,448 ± 1,403 | 12,963 ± 540 |
| qwen3.6-plus single/default | 30/30 (3 repeats) | 10/10 (1 repeat) | 30/30 | 10/10 | 8.2 ± 1.9 | 8.4 ± 2.2 | 16,368 ± 6,001 | 16,549 ± 5,854 |

## Notes
- No hangs: all three processes finished (last at ~19:06). The watchdog script quit early at 18:58 because of a bug in its loop condition, so it wasn't watching for the last ~8 min. Logs were still growing throughout, so no stall happened.
- Pure-chain fallback: 0 detections. The eval prompt always produces the plan [read README, read tests] → locate+apply → verify, and `Planner.is_pure_chain` returns False for that plan (checked offline). The fallback message never appears in any log or agent message.
- Main v3 regression: the two parallel "read" subtasks get a 3-step budget ("Max steps (3) reached"). They usually run out of steps before calling finish, so they are marked failed (even after the one retry), and the dependent "Locate the buggy code and apply the fix" subtask is BLOCKED. That means no fix is attempted. "[blocked] Locate…" appears in 24/30 qwen3.6-plus and 20/20 qwen-plus multi results, and both read subtasks failed in 22/30 and 19/20. These counts come from the merged agent messages, which may be truncated, so treat them as lower bounds. Runs end at ~12 steps (2 reads × 3 steps × 2 attempts).
- The new transitive-BLOCKED handling works: the blocked chain now terminates instead of deadlocking.
- Single mode on the new code matches v2 (10/10).
