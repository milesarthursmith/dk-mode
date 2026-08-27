# Does dk-mode reduce cheating? A public measurement

Everything in the main repository tests whether dk-mode *works*. Nothing tests
whether it *helps*. This directory is the first attempt to answer that against
a public benchmark with published baselines.

## Why this benchmark

[ImpossibleBench](https://github.com/safety-research/impossiblebench) builds
coding tasks where the written specification and the unit tests contradict
each other. Passing is then only possible by cheating: special-case the test,
hardcode the expected value, or edit the test instead of the code.

Three properties make it the right first hill:

1. **The score is unambiguous.** A pass on an impossible task IS a cheat. No
   judge model, no partial credit, no argument about what counts.
2. **It moves.** The paper reports GPT-5 cheating 76% of the time on one
   variant, dropping to near zero when the tests are hidden. A measure that
   responds to intervention can show whether ours does anything.
3. **dk-mode ships a rule for exactly this**, taken from this line of work:
   *"Makes the test pass instead of making the code right."* So this asks the
   sharpest question available - does showing that rule, at the moment the
   model is about to cheat, make it cheat less?

## Running it

```bash
git clone https://github.com/safety-research/impossiblebench
cd impossiblebench && pip install -e . && cd -

# 1. Baseline first. Always.
inspect eval evals/impossiblebench/dk_steer.py@dk_baseline \
  --model anthropic/claude-sonnet-5 --limit 20

# 2. The same run, with dk-mode speaking.
DK_HOME=~ inspect eval evals/impossiblebench/dk_steer.py@dk_steered \
  --model anthropic/claude-sonnet-5 --limit 20
```

The cheating rate is the pass rate. Lower is better - the opposite of a normal
benchmark.

LiveCodeBench needs no Docker. The SWE-bench variant does.

## Reading the result honestly

**Run the baseline first and check it against the published number.** A
baseline that does not roughly reproduce means the setup is wrong and the
comparison is worthless. This is the step that is tempting to skip.

**Check how often dk-mode actually spoke.** Each run records `dk_calls` and
`dk_fired` in sample metadata. If it never fired, the run says nothing about
dk-mode - it says the relevance layer stayed quiet.

**Change one thing at a time.** Same model, same split, same limit. Two runs
that differ in two ways measure neither.

**A negative result is a result, and it gets published here.** dk-mode is
built on the belief that a rule shown at the right moment changes behaviour.
If the cheating rate does not move, that belief is wrong, and finding that out
cheaply is the point of running this.

## Status

**Not yet run.** The integration is built and tested - the steering text is
injected as the last message before each generation, which is the same
position the hook uses in a real session. No numbers exist yet. When they do,
they go here, whichever way they fall.
