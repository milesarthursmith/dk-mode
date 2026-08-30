"""Pilot: SWE-bench Verified easy-slice under our exact agent stack.

PURPOSE. No lab has published a Flash-Lite-class model driving a
Claude-Code-style scaffold on SWE-bench, and no one has published scores
for the "<15 min fix" difficulty slice at all. This pilot buys the two
numbers everything else depends on, for ~$2-3: our stack's pass rate on
the easy slice (target band 0.4-0.8), and the real per-instance cost.

Uses inspect_evals' swe_bench task (dataset + official scorer) with the
solver swapped for the same claude_code agent as evals/lcb, and the
Epoch ghcr images (authenticated pull; ~12GB for all 20 vs ~50GB from
Docker Hub thanks to shared layers). message_limit raised to 100 - the
task default of 30 was binding in the 6-instance pilot.
"""
import os

from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset
from inspect_evals.swe_bench import swe_bench
from inspect_swe import claude_code

HERE = os.path.dirname(os.path.abspath(__file__))
IDS = set(open(os.path.join(
    os.environ.get("PILOT_IDS",
                   "/tmp/claude-0/-home-user-dk-mode/2829e350-d9d0-5ad5-9a33-913bc07e4140/scratchpad/pilot_ids.txt"))).read().split())

task = swe_bench()  # default template = Epoch ghcr registry
task.dataset = MemoryDataset([s for s in task.dataset if str(s.id) in IDS])
assert len(task.dataset) == len(IDS), f"got {len(task.dataset)} of {len(IDS)}"

agent = claude_code(
    cwd="/testbed",              # where swebench images put the repo
    attempts=1,
    model_config="claude-haiku-4-5-20251001",   # identity pinned; bridge serves --model
    disallowed_tools=["WebSearch", "WebFetch"],
)

if __name__ == "__main__":
    inspect_eval(
        task,
        solver=agent,
        model="openrouter/google/gemini-2.5-flash-lite",
        epochs=1,
        message_limit=100,
        max_samples=4,           # 15GB host; each sample runs its own container + proxy
        log_dir=os.path.join(HERE, "logs", "pilot"),
        display="plain",
    )
