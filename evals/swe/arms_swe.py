"""Three arms on SWE-bench Verified's "<15 min fix" slice, real Claude Code.

The n=20 pilot (docs/log.md 2026-08-30) showed the baseline failure here
is stochastic disengagement: 7/20 samples ended after ONE turn with zero
tool calls, and the same instance flips between turn-1 surrender and a
19-turn pass across runs. That is the most steerable failure that exists,
so this is the first instrument where dk-mode's mechanism and the
dominant failure mode actually meet.

  bare       no hooks. The control.
  dk         dk-mode's three hooks, files written into the swebench
             container at setup (no custom image - each sample runs its
             instance's Epoch image).
  challenge  no hooks; fixed text every 3rd bridged generation. The
             no-model, no-selection control.

attempts=3 in EVERY arm, for two reasons: dk_watch writes its verdict for
the NEXT user prompt, and attempts are what provide next prompts (see
evals/lcb/arms_lcb.py); and retry-on-fail alone plausibly rescues turn-1
surrenders, so the bare arm must have it too or dk gets credit for mere
re-prompting. Mid-attempt scoring is safe: the official eval script
resets test files to the base commit before AND after each run. Known
arm-equal leak: it leaves /tmp/test_patch.diff in the container.

Before believing a dk number, count live monitor injections:

    python3 evals/lcb/check_live.py evals/swe/logs/arms
"""
import os

from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset
from inspect_ai.model import ChatMessageUser, GenerateInput
from inspect_ai.solver import chain, solver
from inspect_ai.util import sandbox
from inspect_evals.swe_bench import swe_bench
from inspect_swe import claude_code

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PLUGIN = os.path.join(REPO, "evals", "hooked", "plugin")
CA_LOCAL = os.environ.get("DK_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
IDS = set(open(os.environ.get(
    "SWE_IDS", os.path.join(HERE, "instances.txt"))).read().split())

# Hook processes get their whole environment inline: the swebench sandbox
# is the per-instance Epoch image, so there is no compose file to carry
# DK_* variables and no baked-in /opt/dk-mode. The three CA variables are
# what lets dk_watch verify TLS through the egress proxy (compose.yaml's
# lesson 2: a trust failure here is silent and just looks like a quiet
# monitor).
DK_ENV = (
    "DK_MEM=/opt/dk-mem"
    " DK_BACKEND=openai"
    " DK_API_URL=https://openrouter.ai/api/v1/chat/completions"
    " DK_API_KEY={key}"
    " DK_WATCH_MODELS=google/gemini-2.5-flash"
    " SSL_CERT_FILE=/opt/dk-ca.crt"
    " CURL_CA_BUNDLE=/opt/dk-ca.crt"
    " REQUESTS_CA_BUNDLE=/opt/dk-ca.crt"
    " DK_LOG_DIR=/opt/dk-mem"
)

HOOKS_JSON = """{{
  "hooks": {{
    "UserPromptSubmit": [{{"hooks": [{{"type": "command",
      "command": "{env} bash /opt/dk-mode/scripts/dk_recall.sh 2>>/opt/dk-mem/hook_err.log"}}]}}],
    "PostToolUse": [{{"hooks": [{{"type": "command",
      "command": "{env} python3 /opt/dk-mode/scripts/dk_tripwire.py 2>>/opt/dk-mem/hook_err.log"}}]}}],
    "Stop": [{{"hooks": [{{"type": "command",
      "command": "{env} bash /opt/dk-mode/scripts/dk_capture.sh 2>>/opt/dk-mem/hook_err.log"}}]}}]
  }}
}}"""


@solver
def setup(hooks: bool):
    """Write this arm's hook registration (and for dk, the plugin itself)
    into the per-instance container. Settings are project-level under
    /testbed because inspect_swe seeds the home directory itself."""
    plugin_files = {}
    if hooks:
        for root, _, files in os.walk(PLUGIN):
            for f in files:
                p = os.path.join(root, f)
                plugin_files[os.path.relpath(p, PLUGIN)] = open(p).read()
        ca = open(CA_LOCAL).read()
        env = DK_ENV.format(key=os.environ["OPENROUTER_API_KEY"])

    async def solve(state, generate):
        if hooks:
            for rel, content in plugin_files.items():
                await sandbox().write_file(f"/opt/dk-mode/{rel}", content)
            await sandbox().write_file("/opt/dk-ca.crt", ca)
            r = await sandbox().exec(["bash", "-c",
                "chmod +x /opt/dk-mode/scripts/* && mkdir -p /opt/dk-mem "
                "&& bash /opt/dk-mode/scripts/dk_bootstrap.sh /opt/dk-mem "
                "&& test -f /opt/dk-mem/dk_rules.md"])
            if r.returncode != 0:
                raise RuntimeError(f"dk setup failed: {r.stderr}")
            settings = HOOKS_JSON.format(env=env)
        else:
            settings = '{"hooks": {}}'
        await sandbox().write_file("/testbed/.claude/settings.json", settings)
        return state
    return solve


@solver
def probe():
    """Post-agent: pull the dk memory dir's state into the transcript so a
    silent monitor is diagnosable after the container is gone."""
    async def solve(state, generate):
        r = await sandbox().exec(["bash", "-c",
            "ls -la /opt/dk-mem 2>&1; echo ==; "
            "tail -c 3000 /opt/dk-mem/dk_watch*.log /opt/dk-mem/hook_err.log 2>/dev/null; "
            "echo ==; head -c 2000 /opt/dk-mem/.dk_active.* 2>/dev/null"])
        state.messages.append(ChatMessageUser(
            content=f"<dk-probe>\n{r.stdout[-6000:]}\n</dk-probe>"))
        return state
    return solve


def _challenge_filter(every: int):
    with open(os.path.join(REPO, "evals", "impossiblebench",
                           "challenge.md"), encoding="utf-8") as f:
        text = f.read().strip()
    state = {"n": 0}

    async def filter(model, input, tools, tool_choice, config):
        state["n"] += 1
        if (state["n"] - 1) % every:
            return None
        return GenerateInput(
            input=list(input) + [ChatMessageUser(content=text)],
            tools=tools, tool_choice=tool_choice, config=config)
    return filter


def make_task(name, hooks, challenge_every=0):
    t = swe_bench()               # default template = Epoch ghcr images
    t._name = f"swe_{name}"       # Task.name property reads self._name
    t.dataset = MemoryDataset([s for s in t.dataset if str(s.id) in IDS])
    assert len(t.dataset) == len(IDS)
    agent = claude_code(
        cwd="/testbed",
        attempts=3,
        model_config="claude-haiku-4-5-20251001",  # identity pinned; bridge serves --model
        disallowed_tools=["WebSearch", "WebFetch"],
        filter=_challenge_filter(challenge_every) if challenge_every else None,
    )
    t.solver = chain(setup(hooks), agent, probe()) if hooks \
        else chain(setup(hooks), agent)
    return t


if __name__ == "__main__":
    import sys
    arms = sys.argv[1:] or ["bare", "dk", "challenge"]
    spec = {"bare": (False, 0), "dk": (True, 0), "challenge": (False, 3)}
    for arm in arms:
        hooks, every = spec[arm]
        inspect_eval(
            make_task(arm, hooks, every),
            model="openrouter/google/gemini-2.5-flash-lite",
            epochs=int(os.environ.get("SWE_EPOCHS", "2")),
            message_limit=100,
            max_samples=4,
            log_dir=os.path.join(HERE, "logs", "arms"),
            display="plain",
        )
