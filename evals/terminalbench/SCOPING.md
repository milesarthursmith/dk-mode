# Terminal-Bench as a watcher A/B instrument — scoping (2026-09-01)

Source: research pass over harbor 0.22.0 source, Hub leaderboard data,
Claude Code docs, HF datasets. Full citations in docs/log.md entry.

## Feasibility: YES, no fork

- TB 2.0+ runs on Harbor (`uv tool install harbor`). The leaderboard's
  "Claude Code harness" is `--agent claude-code`, which installs `claude`
  in the task container and runs it in /app with --print and
  --permission-mode=bypassPermissions.
- Hook injection, zero code: `--ak "config=<settings.json>"` uploads a
  Claude settings object (hooks included) and passes it via --settings;
  `--skill ./dkmode` uploads the hook scripts to
  $CLAUDE_CONFIG_DIR/skills/dkmode/. Hooks run in -p mode (folder
  trusted). Control arm = same command without config/skill. Pin
  `--ak version=` in both arms. Never use --bare (skips hooks).
- Hook state written under $CLAUDE_CONFIG_DIR lands in the trial's
  agent/sessions/ and is collected automatically - the probe problem
  solved for free.

## Cost: far above earlier estimates

Leaderboard totals / trials, all at effort=max:

    Opus 5 / CC     TB4 $18.1/trial   TB-Sci $33.3
    Fable 5 / CC    TB4 $22.0/trial   TB-Sci $67.5
    Sonnet 5 / CC   TB4 $29.1 (pathological at max; ~$5-10 at high)

Trial durations 40-110 min. A 30-task x 2-arm x 3-trial A/B is ~$3.6k
Opus-class, ~$1-1.5k Sonnet-class at high effort. Not a $10-25 stage.

## Task selection

- TB 4.0: 66 tasks, aggregate already in the 30-50% band (Opus 5 51.8%,
  Fable 5 44.5%; ~30% of tasks never solved in 5 tries).
- TB-Science 0.1: 70 tasks, too hard for an A/B (Opus 5 30%, Fable 21%);
  floor effect.
- No per-task pass rates published for 3.0+/Science. Free prior: drop
  the 18 tasks with expert time >= 8h and the 6 <= 1.5h; the 2-6h middle
  (~40 tasks) is the candidate pool. 29 tasks fit this box (mem <= 4GB,
  cpus <= 2, no GPU). Local per-task image builds: 4-5GB free disk is
  the binding constraint; run -n 1 and prune between tasks.

## The free win: public trajectories

HF `harborframework/terminal-bench-2-leaderboard` (Apache-2.0, 40GB, 76
submissions) has per-trial NATIVE Claude Code session JSONLs
(agent/sessions/projects/-app/<id>.jsonl), verifier results and
trajectories, from frontier agents. Fetchable selectively via the HF
tree API. This is the semantic-wedge corpus the replay bench needs -
competent agents, real Claude Code transcripts, known outcomes - at zero
model cost.

## Recommendation

Do not run Terminal-Bench end-to-end until a watcher build has cleared
bench + branched forks. Mine the public trajectories now for the corpus.
When a build earns a Tier-3 run, use TB 4.0 middle-band tasks with a
Sonnet-class agent at high effort, paired trials, sequential stopping.
