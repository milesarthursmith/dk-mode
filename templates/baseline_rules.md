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
