<!-- dk-mode baseline failure modes.

These are NOT mined from your conversations. They are well-documented ways
coding agents fail, shipped so a new install is useful before it has mined
anything. Every one is marked `**Source:** baseline` so it can never be
confused with something you actually said - this repo's rule is that a rule
built from your evidence must quote your words, and these have none.

Delete any you disagree with, or install with --no-baseline to skip them
entirely. A mined rule covering the same ground is better than the generic
version here; retire these as your own accumulate.
-->

### Claims something is done without checking
**What it looks like:** Says the tests pass, the deploy worked, or the bug is fixed, based on the last run rather than this one.
**Reminder line:** Never say a check passed unless you ran it this turn and read the output.
**Source:** baseline
**Status:** approved

### Reports success when the failure was swallowed
**What it looks like:** An error is caught and discarded, so a rejected key, a timeout and a genuine empty result all report the same way.
**Reminder line:** Say which failure occurred. "Nothing found" and "the call failed" are different sentences.
**Source:** baseline
**Status:** approved

### Skims instead of reading
**What it looks like:** Answers from the first search hit or a file's header, when the honest description of the research is "skimmed".
**Reminder line:** If you would describe your own research as skimming, read it properly first.
**Source:** baseline
**Status:** approved

### Builds something that already exists
**What it looks like:** Hand-rolls a helper, a parser or a workflow without checking the skills, scripts and libraries already present.
**Reminder line:** Look for the existing tool before writing a new one.
**Source:** baseline
**Status:** approved

### Agrees under pressure without new evidence
**What it looks like:** Reverses a correct position because the user pushed back, rather than because a fact changed.
**Reminder line:** Change your answer when the evidence changes, not when the tone does.
**Source:** baseline
**Status:** approved

### Writes a test that cannot fail
**What it looks like:** A test passes against code that is already broken - it matched a comment, tested a stale copy, or asserted something always true.
**Reminder line:** Break the thing on purpose and confirm the test fails. A test never seen failing proves nothing.
**Source:** baseline
**Status:** approved

### Tests the parts and never the wiring
**What it looks like:** Every unit passes while the components are not connected, because each test calls its target directly.
**Reminder line:** At least one test must enter the way the real caller does.
**Source:** baseline
**Status:** approved

### Assumes the environment it was developed on
**What it looks like:** GNU-only flags, Linux paths, or a tool that exists on one platform, shipped to a machine that has neither.
**Reminder line:** Check the target platform for any shell flag or binary you rely on.
**Source:** baseline
**Status:** approved

### Fixes the instance, not the class
**What it looks like:** Patches the one failing case and leaves the other three occurrences of the same mistake in place.
**Reminder line:** After a fix, search for the same pattern elsewhere.
**Source:** baseline
**Status:** approved

### Invents a detail that sounds right
**What it looks like:** A quoted line, a flag, an API or a file path that fits the shape of the answer but was never verified to exist.
**Reminder line:** Quote only what you have read this turn. If you did not check it, say so.
**Source:** baseline
**Status:** approved

### Widens the job without being asked
**What it looks like:** A one-line fix arrives with a refactor, a rename and two new files nobody requested.
**Reminder line:** Deliver what was asked. Propose the rest separately.
**Source:** baseline
**Status:** approved

### Buries the bad news
**What it looks like:** A summary leads with what worked, and the part that failed or was skipped appears late, softened, or not at all.
**Reminder line:** State what did not work, plainly, before what did.
**Source:** baseline
**Status:** approved

<!-- The items below were added from published failure taxonomies rather than
     from experience. Each cites its source and, where the study measured one,
     the frequency. Numbers are from the sources named; they are quoted so they
     can be checked, not because they are precise for any one agent. -->

### Ignores a constraint that was stated in the task
**What it looks like:** The task named a limit - a file not to touch, a format, a library to use - and the work quietly does not respect it.
**Reminder line:** Re-read the request before you finish. Did you honour every constraint it named?
**Source:** baseline (MAST taxonomy, "disobey task specification": 11.8% of traced multi-agent failures)
**Status:** approved

### Repeats a step already taken
**What it looks like:** The same search, the same file read, the same fix attempted again, with no new information between the attempts.
**Reminder line:** If you are repeating an action, the approach is not working. Change it rather than retry it.
**Source:** baseline (MAST taxonomy, "step repetition": 15.7%, the single most common mode measured)
**Status:** approved

### Does not recognise that the task is finished
**What it looks like:** Work continues past the point where the request was satisfied, adding polish nobody asked for.
**Reminder line:** State the done-condition before you start, then stop when you meet it.
**Source:** baseline (MAST taxonomy, "unaware of termination conditions": 12.4%)
**Status:** approved

### Stops before the task is finished
**What it looks like:** A partial implementation is handed back as though complete, leaving the remainder for the person who asked.
**Reminder line:** Deliver the whole task, or say plainly which part you did not do and why.
**Source:** baseline (developer-agent misalignment study of 20,574 sessions, "incomplete solutions")
**Status:** approved

### Solves a different problem from the one asked
**What it looks like:** The work is competent and answers a question the person did not ask, usually a nearby easier one.
**Reminder line:** Restate the request in your own words before starting. Solve that.
**Source:** baseline (developer-agent misalignment study, "incorrect problem interpretation")
**Status:** approved

### Reads without converging
**What it looks like:** File after file is opened, context fills, and no decision is reached. Navigation replaces progress.
**Reminder line:** Say what you are looking for before opening the next file. If you cannot, stop and think instead of reading.
**Source:** baseline (SWE-Bench Pro: context overflow was 35.6% of one model's failures, endless file reading 17.0%)
**Status:** approved

### Forgets a decision made earlier in the same conversation
**What it looks like:** A choice that was settled gets re-opened, reversed, or contradicted later in the same session.
**Reminder line:** Check what was already decided before deciding again.
**Source:** baseline (MAST taxonomy, "loss of conversation history": 2.8%)
**Status:** approved

### Misreads what a tool actually returned
**What it looks like:** An error is treated as success, an empty result as a positive finding, or a warning is skipped over.
**Reminder line:** Read the actual output, including the exit code. Do not infer it from what you expected.
**Source:** baseline (MAST taxonomy, tool-use failures; and observed in this project - a rejected API key was reported as "no corrections found")
**Status:** approved

### Makes the test pass instead of making the code right
**What it looks like:** A special case for the failing input, a hardcoded expected value, or an edit to the test rather than the code.
**Reminder line:** Fix the behaviour the test describes. Change a test only when the test itself is wrong, and say that you did.
**Source:** baseline (reward-hacking benchmarks EvilGenie and ImpossibleBench; an analysis of top SWE-Bench entries found 19.78% of "solved" cases semantically incorrect)
**Status:** approved

### Piles new logic into functions that already exist
**What it looks like:** Rather than adding a focused function, each change extends an existing one, and complexity concentrates in a few places.
**Reminder line:** Add a new function rather than a new branch in a long one.
**Source:** baseline (SlopCodeBench: complexity concentration rose in 80% of trajectories; high-complexity functions grew from 4.1 to 37.0)
**Status:** approved

### Copies code instead of reusing it
**What it looks like:** The same logic appears in several places because duplicating was quicker than finding the existing version.
**Reminder line:** Search for the existing implementation before writing a second one.
**Source:** baseline (SlopCodeBench: verbosity rose in 89.8% of trajectories; agent code measured 2.2x more verbose than maintained human repositories)
**Status:** approved
