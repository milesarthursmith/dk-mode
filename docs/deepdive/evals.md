# Deep dive: the evaluation programme (reader report, 2026-09-06)

I have everything needed. Summary of what I verified independently before writing: I re-ran `evals/bench/score_judgment.py` and reproduced the 09-05 numbers (48/78 vs 31/78, p=0.005; per-corpus 25/38 vs 15/38 p=0.006 on own moments, 23/40 vs 16/40 p=0.19 on Terminal-Bench moments); I confirmed `evals/hooked/plugin/` is gitignored (`.gitignore:27`), so no hooked run has a versioned build; and I counted that 7 of the own-corpus "wedge" moments are growing prefixes of one session.

---

# Deep dive: the dk-mode evaluation programme, 2026-08-27 to 09-06

Vocabulary used below (from docs/SHAPE.md): a **watcher** is the LLM overseer; a **wedge** is a stretch where the agent is stuck; a **moment** is a frozen transcript prefix ending at a decision point; a **sense** is a deterministic signal shown to the watcher; an **arm** is one policy for what to inject; a **live block** is text the model-based monitor injected (as opposed to the static note or the tripwire, which need no model).

## 1. Every instrument run

Cost is as stated in the log; "?" means the log gives no figure. "Build" says which monitor code ran: `scripts/` (imported directly, `evals/impossiblebench/arms.py:67-72`) or `plugin` (the gitignored snapshot, `.gitignore:27`, found stale on 09-01).

| # | Date / dir | Task family | Arms | n | Endpoint | Result | Cost | Build | What the log concluded |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 08-27_1042/1048 | ImpossibleBench (IB) conflicting, `claude -p` wrapper | baseline, dk | 1 | cheat rate | 0.0 both; dk fired 2/3 gens | $0 | scripts | "n=1 through a wrapper is not a measurement" (log 08-27) |
| 2 | 08-28_0444 | IB conflicting, minimal/3, Haiku agent | 4 arms | 20 | cheat rate | all 0.0; dk fired 51/60 gens | ? | scripts | reproduces published 0%; "no headroom above a zero floor" (results.md) |
| 3 | 08-28_0459 | IB original, minimal/3, Haiku | 4 arms | 20 | pass rate | base .45, dk .35, chal .40, both .40; dk paired 0 won/2 lost | ? | scripts | inside noise; 17/20 tasks identical in every arm (log 08-28, fault 3) |
| 4 | 08-28_0523 | IB original, tools/10, Haiku | 4 | 20 | - | ABORTED, HTTP 402 | ? | scripts | "do not read as a result" |
| 5 | 08-28_0625 | IB original, tools/6/bare, Haiku | 3 | 20 | - | ABORTED 402; 9.99M tokens on 13 samples | ? | scripts | cost uncalibrated |
| 6 | 08-28_0652 | IB original, tools/6/bare, flash-lite agent, Haiku monitor | baseline, dk, (challenge aborted) | 20 | pass + trace counters | .15 vs .15, paired 2-2; dk fired 639/693 gens (92%); steps 21→34, repeats 13→24.5 | ? | scripts | "selectivity, asserted since the first README, is false as shipped" (log 08-28) |
| 7 | 08-28 offline | replay of #6 baseline traces through prompt variants (`tune_selectivity.py`) | 5 prompt variants | 6 samples, 44-51 points | fire rate | shipped 95%, suppress 85%, strict-now 38%, both 36%, ported 46-53% | $0 (CLI login) | scripts | strict-now ported into the product (commit bc26cf1) |
| 8 | 08-28_1355 | MATH-500 band(23), 3 ep, flash-lite agent, Haiku monitor | baseline, dk, challenge | 23 | mean, pass^3, pass@3 | .59/.67/.70; dk vs base 7/4/12 p=.55 | ~$0.10 | scripts | "first positive signal, not yet a conclusion" |
| 9 | 08-28_1502 | MATH band(46), 5 ep | same 3 | 46 | mean, pass^5 | .70/.70/.75; dk vs base 12/14 p=.85; chal vs base 18/11 p=.27 | ~$1 | scripts | "dk's edge was noise; the schedule's survives, weakly" |
| 10 | 08-29_0111 | MATH band(46), 3 ep | 7 arms (payload ablation) | 46 | mean, pass^3 | nothing significant; "Try harder." 16/14 p=.86 | ~$1.5 | scripts | content of injection does not matter |
| 11 | 08-29_0231 | MATH band(46), dk only, Haiku monitor | dk | 46 (111 trials, not 138: `math_arms.json` trials=111) | mean | .73, pass^3 28/46 | ? | scripts | no in-session baseline; "a lead, not a result" |
| 12 | 08-29_0438 | MATH band(46), gpt-oss-120b monitor | dk, challenger | 46 | mean | .70 / .72; vs Haiku counterparts 9-15 p=.31, 11-7 p=.48; cross-session vs #10 baseline | ? | scripts | "monitor model is not the bottleneck" |
| 13 | 08-29_0822 | MATH band(46), directive format | baseline, dk | 46 | mean | .70 / .75; paired 12-10 p=.83; session drift .67→.70 | ? | scripts | "the instrument is exhausted" |
| 14 | 08-29 (aborted) | LCB easy+medium, real Claude Code (hooked) | 3 | 20×3 | - | OOM; arms at 57/16/58 samples | $2.15 | plugin | recorded, not reported |
| 15 | 08-29_lcb | LCB easy+medium, hooked, flash-lite agent, Haiku monitor | bare, dk, challenge | 20×3 | mean, pass^3, pass@3 | .75/.72/.73; dk vs bare 5-7 p=.77; dk carried 50 live blocks | ~$3.50 (+$3.83 aborts) | plugin (stale, per log 09-01) | "this null counts"; only 8 flaky tasks; power wants 113-161 pairs |
| 16 | 08-30 pilot | SWE-bench Verified easy, hooked | bare | 6 then 20 | resolved | 1/6; 3/20; 7/20 one-turn surrenders | $0.07 + $0.22 | plugin | failures are procedural, "finally match the mechanism" |
| 17 | 08-30 run 1 | SWE easy, hooked, attempts=3, gemini-2.5-flash monitor (`arms_swe.py:58`) | bare, chal, dk | 20×2 | mean, pass^2, pass@2 | .15/.20/.30; dk vs bare 5-1 p=.22; dk 5 live blocks in 40 samples | ~$8 | plugin (stale) | "first directional separation, not yet a result" |
| 18 | 08-30 run 2 | SWE easy-2, 29 fresh instances | same 3 | 29×2 | mean | .29/.36/.35; pooled dk vs chal 8-7 p=1.0; any-injection vs bare 15-8 p=.21 | ~$4 | plugin (stale) | "dk's edge over the scheduled control was noise" |
| 19 | 08-31 | goal-mode jinja marathon (20 seeded bugs), gemini-2.5-flash agent | bare, dk, (challenge lost) | 1 task × 2 ep | fraction fixed | bare {1.00,.41}; dk {0.00,.62}; 0 live blocks in 244 turns | ~$12 | plugin (stale) | instrument "validated"; n=2 is noise; live layer silent |
| 20 | 09-01 offline | marathon wedge replayed through dk_watch | old vs current prompt | 1 moment | fires? | old: silent; current: fires | ~$0.01 | both | "evals ran a stale build" |
| 21 | 09-01 bench | replay, 18 moments from #19 (10 wedge/8 healthy) | arc-patch, stale, current | 18 | recall / false fire | 5/10 0/8; 4/10 2/8; 2/10 3/8 | ~$0.30 | both | morning's story "WRONG at n=10"; wedge-blindness build-independent |
| 22 | 09-02 | Terminal-Bench 2 corpus mined (`extract_tb.py`) | - | 104 moments (49 wedge / 55 healthy by rule) | - | - | $0 | - | the semantic corpus the watcher exists for |
| 23 | 09-02 | counter-gated baseline over 163 moments | counter | 163 | recall / FP | 40/92, 17/71; beats every model prompt on the 10 shared wedges | $0 | - | "the free baseline sets the bar"; admits circularity |
| 24 | 09-02 stage 1 | stateful watcher, gemini-2.5-flash, run-seq | watcher | 163 | recall / FP, McNemar vs counter | 50/92, 21/71; 22/12 p=.12; semantic subset 27/49 tie | ~$4.4 | watcher_session | "kill criterion NOT cleared" |
| 25 | 09-02 | watcher-dense (look every 5) | dense | 104 | same | 22/49, 20/55; dense vs baseline healthy 16-6 p=.05 | ~$5 | watcher_session | "cadence is not the lever" |
| 26 | 09-02 | watcher-v2 first run | v2 | 104 | - | 0/49: 66 rows HTTP 403 (key cap) | ? | watcher_v2 | artefact, discarded |
| 27 | 09-03 | watcher-v2 rerun | v2 | 104 | same | 13/44, 11/54; v2 vs watcher on wedges 1-12 p<.01 | ~$5 | watcher_v2 | "selectivity costs recall, buys nothing" |
| 28 | 09-05 | judgment relabel, 4 LLM readers | - | 160 | speak / silent | 78/82; 48/160 disagree with prefixes | ? | - | rule labels were "wrong in kind" |
| 29 | 09-05 rescore | all variants vs judgment labels (`score_judgment.py`) | watcher, counter, dense, v2, think | 160 | recall / FP, McNemar | watcher 48/78 vs counter 31/78, 25/8 p=.005; FP 22/82 vs 24/82 | $0 | - | stage-1 criterion "met on the full corpus, at the margin on the semantic subset" |
| 30 | 09-05 | watcher with DK_REASONING=high | think | 157 paired | recall | 34 vs 46 speak-fires, p=.029; FP equal | ~$2.5 | watcher_session | reasoning-on is worse; "not the default" |
| 31 | 09-06 | alert quality, second reader | - | 70 fires | same / partial / wrong | 24/20/4 on speak; 14 false alarm / 2 watcher right / 6 unclear on silent | ? | - | "honest tier-1 number is 24/78"; watcher never widens the frame (TIERS.md:152-201) |

## 2. Reading each null result

**#2-3, ImpossibleBench minimal scaffold.** Not capable of detecting anything. On `conflicting`, every arm scored 0.0, so there was no cheating to prevent (results.md). On `original`, 17 of 20 tasks gave the same answer in every arm, an effective n of 3 (log 08-28, fault 3). The dk arm also fired on 51/60 and 41/50 generations (`2026-08-28_0444` and `_0459` JSON), so it was not a selective policy in any case. Void as a test of selection; valid only as a reproduction of the published 0%.

**#6, IB tools/bare.** The one comparison that finished was dk vs baseline at n=20, one epoch, paired 2-2. The scheduled control aborted, so the head-to-head the whole harness was built for never ran. The dk arm fired on 92% of generations, which the log correctly reads as "the scheduled challenge plus a model call". Two of the three instrument faults the log found here (the `tools` scaffold bypassing the injection wrapper; the pre-steered system prompt) were fixed *in this run's own design*, so this is a smoke test, not a null.

**#8-13, the maths band.** The instrument had no arc: 2-12 turns on a single problem (log 08-29, "the maths band was retired on a fair objection"). The rules are coding-flavoured and the monitor fired on 3-15% of generations (log 08-28). What the band could detect was a large effect of *any* injection on short-task completion; it saw at most +5 points with p around 0.3-0.8. Two of the comparisons are unpaired across sessions (#11 has no baseline at all; #12 pairs against #10's baseline), and the log itself measured session drift at 0.67→0.70, equal to the largest "effect" seen (log 08-29 "session drift is real"). #11 also has 111 trials where 138 were planned (`2026-08-29_0231/math_arms.json`), so some tasks have two epochs, not three, and pass^3 there is not the same statistic as elsewhere. Conclusion: capable of excluding effects above roughly 15 points on short tasks for the old monitor; nothing else.

**#15, LCB hooked.** This is the run the log called "the first valid comparison" (08-29) and said used "the rebuilt one that can see an arc". The 09-01 entry contradicts that: "EVERY dk arm ever run - LCB, both SWE runs, the marathon - evaluated the old build." The evidence for the 09-01 finding is a working-tree diff on that day, not a run record: the plugin snapshot is gitignored (`.gitignore:27`), the Dockerfile copies it at build time (`evals/hooked/Dockerfile:11`), and `git log -- evals/hooked/plugin` is empty. So no hooked run has a verifiable build hash. Hooks did fire (50 live blocks, verified by `check_live.py`, which classifies by string match at lines 15-20). Power: only 8 of 20 tasks were flaky in the control; the log's own estimate wants 113-161 paired observations. Verdict: void as a test of the current build; underpowered as a test of the old one. Note also that the 09-01 bench (#21) found the *current* build worse on wedges (2/10 vs 4/10), so voiding these runs does not rescue the design.

**#17-18, SWE-bench.** Same stale build, same provenance gap. The live layer was thin: 5 live blocks in 40 samples, 10 in 58 (log 08-30). The control is not a clean placebo (see section 3). The dominant failure was mechanical (edit precision, ~25-30% of samples in every arm, log 08-30 trace analysis), which no injection touches. The "dk 0.30 vs bare 0.15" headline rests on 6 discordant tasks (5-1, p=0.22) and did not replicate (8-7 vs challenge pooled). Verdict: void for the current build; for the old build, consistent with "any injection gives a small, non-significant lift on a weak agent", which is what the log concluded.

**#19, goal marathon.** n=2 per arm with within-arm spread of 0.6 (bare 1.00 vs 0.41). The challenge arm never ran, so the three-arm design became two arms. Zero live blocks in 244 turns is reported as "the live layer was silent", but the log also says both epochs hit the message cap "so the post-agent probe never ran and the watch log is unrecoverable" (log 08-31). Whether `dk_watch` executed, reached the relay, or errored is therefore unknown; the smoke run had produced live blocks, so the plumbing probably worked, but "silent by judgment" and "silent by failure" are indistinguishable here. The muting bug (an empty selection suppressing the static note, log 08-30) is described as fixed on 08-31 (`arms_goal.py:10-11`), the same day as the run, with no record of which copy was in the container. Verdict: not a measurement of anything but the instrument's variance, which is itself the useful number: it says three epochs cannot separate arms here (TIERS.md:100-106 reaches the same conclusion).

**#24, bench stage 1 under automatic labels.** The labels were produced by rules (`replay_bench.py:78-86`: wedge = score flat across 3 driver checks; healthy = new high-water mark; `replay_bench.py:97-101` for SWE; `extract_tb.py:50-77, 688-720` for Terminal-Bench). The counter baseline's triggers are the same shapes with the same threshold of 3 (`baseline_counter.py:13-14, 21-48`), which the log admits ("its triggers partly mirror the corpus labeling rules", 09-02). So the "tie" between watcher and counter was a comparison against a labeler that shares the counter's definition of a wedge. The 09-05 relabel showed the rule labels disagreed with a reader on 48/160 moments. Every bench number before 09-05 (#21, #23-27 as originally reported) is void as a measure of overseer judgment. The rescoring (#29) is the only bench result that should be cited.

**#30, reasoning on.** Nine rows were excluded as errors and three moments never completed. The result (recall drops, p=0.029, one model, one prompt) is a single unreplicated run. It also conflicts with CLAUDE.md §3 ("Judge/watcher runs must use reasoning on ... A judge without reasoning is not a judge"), while the log of the same day says reasoning "is not the default". The repo currently holds both positions.

## 3. Methodology faults

1. **Rule-derived labels, then a rule-derived baseline.** Covered above. CLAUDE.md §1 forbids this and TIERS.md:15-25 concedes it. Additionally, `extract_tb.py:749-751` prioritises *passing* trials when picking healthy moments (`prio = (0 if e["reward"] == 1 else 1, ...)`), while the docstring (line 11-12) says the verifier reward "never decides a label". It does not decide the label; it decides which candidates become the healthy set, which is outcome contamination of the negatives.

2. **Label rule edited after seeing the watcher's fires, in the watcher's favour.** Commit a0c62ef (09-05 08:13): "Review of watcher fires showed the score-uptick rule counted recovery from self-inflicted damage as progress. Watcher calls on those moments were correct." Three healthy moments the watcher had fired on were moved to `moments_dropped/`. Whatever the merit, this is post-hoc removal of false positives.

3. **Label leakage into the judgment relabel.** The reader shard lists (`evals/bench/labels/shard0.txt`) give file paths like `moments/healthy_challenge_ep1_1.jsonl` and `moments/wedge_dk_ep1_10.jsonl`. The readers saw the old rule label in every filename. The 70% agreement with prefixes is therefore an upper bound on independence, not a measurement of it.

4. **One LLM reader per moment; second reads only on disagreements.** Log 09-05 caveat: "the readers were LLM subagents, not Miles." TIERS.md:202-206 measures agreement only on the 22 watcher-vs-reader disagreements, a biased subset. EVALS.md §0 rejected hand labels because they would "grade the system with its own food"; the programme then adopted LLM labels without revisiting that argument.

5. **Pseudo-replication.** In the own corpus, `wedge_dk_ep1_10..16` are seven growing prefixes of one session (and 17 more prefixes of the same session sit in `held/`); `wedge_bare_ep2_7..9` are three of another. McNemar (`score_judgment.py:32-39`) treats them as independent pairs. The own-corpus p=0.006 (TIERS.md:37-39) is computed over 38 "speak" moments of which 10 are two sessions. Eight Terminal-Bench trials also contribute two moments each.

6. **Prompt tuned on replayed traces by fire rate, not outcome, then shipped.** `tune_selectivity.py` replayed 6 samples at stride 2 (44-51 points) of the #6 baseline traces and picked the variant that fired least (log 08-28). That variant, "strict-now" (`tune_selectivity.py:89-96`), became the product prompt (commit bc26cf1) and was later identified as *the* reason the monitor could not see multi-turn wedges (log 09-01, "CONFIRMED AS THE FLAW"). The objective was "speak on a minority of turns", a design assertion, never validated against any outcome.

7. **Endpoints chosen after the data.** IB moved from pass rate to trace counters after 17/20 identical answers (log 08-28, fault 3; `trace_metrics.py:11-16` calls the counters "diagnostics, not the primary signal" anyway). Maths reported mean, pass^k and pass@k and the log picks whichever moved. SWE reported mean, pass^2, pass@2. redesign.md then declares pass^k/flake-rate the right endpoint for the *next* run. No endpoint was fixed before any run.

8. **Multiple comparisons without correction.** Seven payload arms against one shared baseline (#10; the log notes "a single unlucky baseline explains" the pass^3 pattern). Three pairwise tests per three-arm run. The two sub-0.05 results in the bench (dense false fires p=0.05; reasoning p=0.029) are the smallest of roughly a dozen tests.

9. **The scheduled control is not a placebo, and its dose differs.** `challenge.md` carries specific advice ("Repeating an attempt unchanged does not work", "follow the specification"). The true placebo is "Try harder." (`arms.py:135`), which matched it, so "presence, not content" was established, but only on maths. Dose: the challenge arm fired on 45-46% of generations and injected 174k characters against dk's 13-28% and 44k (#9). In the hooked harnesses the schedule counter is a closure created once per task (`arms_lcb.py:110-118`, `arms_swe.py:136-145`, `arms_goal.py:145-153`, `arms_hooked.py:127-137`) and shared across concurrent samples (`max_samples=4`), so "every 3rd generation" is every 3rd request across the pool, not per sample. `arms.py:420-441` records that injecting arms consume the message limit faster; the limit was raised, not equalised.

10. **Only the dk arm runs a `probe()` step** (`arms_swe.py:205-206`, `arms_goal.py:176-177`). It runs after the agent and should be inert, but the arms are not byte-identical.

11. **Hook verification arrived late.** Before 08-29, seven hooked logs held 212 static notes, 13 tripwire warnings and zero live blocks (log, "Not yet proven" §3; three independent causes). The 08-28 entry "the shipped plugin verified end to end" was therefore wrong when written, and the log corrected it (commit f04a45b).

12. **Spend decisions made on non-results.** The $12 marathon was launched on the strength of a 5-1 pairing at p=0.22 and a "horizon hypothesis" (log 08-30/31); SHAPE.md's spend section was written "after burning ~$40". Two IB runs (#4, #5) died to uncalibrated cost. The challenge marathon arm was lost to budget, leaving an unbalanced design. The stage gates in SHAPE.md are threshold rules for spending, which TIERS.md:116-119 itself calls a rule-one violation applied to the programme.

13. **The bench scores "fired at the final look", not "was the alert right".** `replay_bench.py:192-200` records the verdict after the last chunk; a watcher that spoke correctly at chunk 2 and fell silent counts as a miss, and a watcher that spoke wrongly counts as a hit. Alert content was only assessed on 09-06 (TIERS.md:152-201). The error filter is `< 3` seconds (`replay_bench.py:203`), while CLAUDE.md §3 says "sub-5s".

14. **The stage-1 bar drifted.** SHAPE.md names the arc-patch prompt as the bar; arc-patch ran on 18 moments only, and the counter became the bar by default (TIERS.md:47-50).

15. **Plan deviations without re-stating the claim.** EVALS.md §2.1 chose Haiku as the agent; nearly every run used gemini-2.5-flash-lite for cost. The Sonnet milestone check never ran (log, "Not yet proven" §4). The scaffold, agent and monitor model all changed between instruments, so "three instruments, same null" is three different systems.

## 4. What the programme has established, as a referee would state it

Established, with the evidence:

- **E1.** The regex phrase list found 0 of 46 real corrections in the project's own history (log 08-25). Solid.
- **E2.** The monitor as shipped on 08-28 fired on 92% of generations (639/693) in one 20-task run (log 08-28). Solid; single run.
- **E3.** Three plumbing faults meant no hooked run before 08-29 ever carried a live monitor block (log, "Not yet proven" §3). Solid, and it voids the 08-28 "verified end to end" claim.
- **E4.** With the *old, stateless* monitor and a Flash-Lite agent, on short tasks (maths band n=46×3-5; LCB n=20×3), no injection policy moved completion by more than about 10-15 points. Effects smaller than that are not excluded. The stale-build finding means this says nothing about the post-08-29 prompt.
- **E5.** On maths, an 11-character payload was within noise of every richer payload (#10). This is "no detectable effect of anything", not "interruption helps".
- **E6.** On frozen transcripts, against labels from single LLM readers who could see the old label in the filename, a gemini-2.5-flash stateful watcher fires on more reader-marked speak-moments than a 3-repeat counter on the own small-agent corpus (25/38 vs 15/38, p=0.006 before correcting for 10 near-duplicate prefixes) and does not separate on the 104 frontier-agent Terminal-Bench moments (23/40 vs 16/40, p=0.19). False-fire rates are similar (about 27-30% of silent moments). I reproduced these numbers.
- **E7.** Of 48 watcher alerts on speak-moments, a second reader judged 24 to name the same problem, 20 partial, 4 wrong; of 22 alerts on silent-moments, 14 were false alarms (TIERS.md:158-169). All 24 "same" verdicts were single-recurring-error wedges; no alert questioned task compliance or abandoned correct work (TIERS.md:181-193).
- **E8.** One run, one model: turning reasoning on lowered recall (p=0.029). Unreplicated.

Not established:

- Whether any watcher output changes what the agent does next, or the session outcome. No fork, reaction or end-to-end run of the watcher shape exists (TIERS.md:66-70 confirms nothing for it is in the repo).
- Whether the current `scripts/dk_watch.py` (post 09-01) does anything end-to-end. It has never been run in a hooked arm.
- Whether the watcher beats the best stateless prompt on the full corpus (arc-patch ran on 18 moments).
- Whether selection beats presence on long-horizon tasks. All long-horizon runs used the stale build and were underpowered.
- Whether the labels are right. No human has read a moment; one LLM reader per moment; leakage via filenames; 21 low-confidence labels.
- Whether a 27-30% false-fire rate is tolerable in a real session. The cost side of interrupting has never been measured anywhere in the programme.
- Anything about the watcher model. Every watcher row is gemini-2.5-flash (log 09-03, 09-05).
- Anything about sessions of hours. Median session across instruments was 12 turns (log 08-30, "the horizon hypothesis stands untested"); only the marathon reached 100+ turns, and it is n=2.

## 5. With about $28 and 160 labelled moments

**The measurement that would most change the product decision** is a reaction check, not another detection sweep. The product question (SHAPE.md) has two halves: does the watcher say what the absent human would say, and does the session end better. The bench has spent all its effort on the first half and now says "half the time, on one wedge shape". Nothing has ever touched the second half, and it decides everything: if the agent ignores a correct alert, detection rate is irrelevant; if it changes course, the 24/78 becomes worth improving.

Concretely: take about 10 own-corpus speak-moments where the alert-quality reader marked the alert "same" (the 24 in `labels/alert_quality.jsonl`), and where the environment can be rebuilt (the jinja goal-mode container is seeded deterministically by `bugs.patch`, and the `.eval` logs hold every Bash and Edit call, so state can be replayed tool call by tool call, the Replay Gap protocol redesign.md cites). At each moment, continue the session three ways for about 15-20 turns: with the watcher's alert injected, with the counter's templated alert for the same moment, and with nothing. Judge by reading, as TIERS.md:143-148 proposes: changed approach / ignored / made it worse. At roughly $0.30-0.50 per continuation (redesign.md tier-2 estimate; the marathon cost ~$2 for 100+ turns) this is 30 continuations, about $10-15, leaving margin for retries. The third arm matters: it asks whether the LLM's wording buys anything over a $0 fact-carrying template, which is the actual product question dk-mode has never asked end-to-end.

What this cannot tell you, and should be said up front: it runs on small-agent (gemini-2.5-flash) wedges, the corpus where detection already works, and says nothing about frontier agents. It measures whether the mechanism exists, not an effect size. Ten moments cannot see a small positive or negative effect (TIERS.md:84-91 is right about that). It is the cheapest experiment that can kill the product; it cannot confirm it.

**Free, and it should come first:** Miles reads a sample of the 22 disputed fires and the 30 missed speak-moments himself (`evals/bench/review_stage1.md` is already formatted for this). Every bench number rests on LLM-reader labels with filename leakage. This costs time, not money, and it is the only thing that turns E6 and E7 from "an LLM agreed with an LLM" into evidence.

**What cannot be learned at this budget:**

- Whether the watcher improves outcomes for frontier agents on real long tasks. Terminal-Bench 4.0 is $1-1.5k with a Sonnet-class agent and $3.6k Opus-class (`evals/terminalbench/SCOPING.md:22-31`), 40-130x the balance (TIERS.md:114).
- Any end-to-end effect smaller than about 15-20 points on any instrument. The goal marathon needs many more than three epochs (its two epochs spanned 0.41-1.00), and the SWE slice needs 60+ instances and multiple epochs (log 08-30) at $4-8 per run of a single arm pair.
- The cost of false fires in real sessions with a human present, which needs real usage, not a benchmark.
- The model knob with any power: a stronger watcher over the 104 frontier moments is single-digit dollars (TIERS.md:139-142) and could move the p=0.19, but it would still be a detection number against the same unverified labels, so it changes the picture less than the reaction check does.

Files cited: `/home/user/dk-mode/docs/log.md`, `docs/SHAPE.md`, `docs/EVALS.md`, `docs/redesign.md`, `docs/TIERS.md`, `docs/HANDOVER.md`, `CLAUDE.md`, `evals/results.md`, `evals/results/*/*.json`, `evals/results/selectivity_tune*.json`, `evals/impossiblebench/{README.md,arms.py,trace_metrics.py,tune_selectivity.py,challenge.md}`, `evals/hooked/{arms_hooked.py,compose.yaml,Dockerfile}`, `evals/swe/{arms_swe.py,pilot.py,relay.py,instances*.txt}`, `evals/goal/arms_goal.py`, `evals/lcb/{arms_lcb.py,check_live.py}`, `evals/math/{arms_math.py,run_math.py}`, `evals/terminalbench/SCOPING.md`, `evals/bench/{replay_bench.py,extract_tb.py,baseline_counter.py,score_judgment.py,watcher_session.py,results.jsonl,review_stage1.md,labels/*}`, `.gitignore`.