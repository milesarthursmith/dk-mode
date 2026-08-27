"""A model provider that shells out to `claude -p` - for smoke tests only.

WHY IT EXISTS. Real benchmark runs need an API key. This remote development
environment has none, but it has a logged-in `claude` CLI. This provider lets
the harness plumbing be exercised end to end - arms, injection, counters,
scoring - with no key, by serialising the conversation and asking the CLI.

WHY IT IS NOT FOR REAL NUMBERS. `claude -p` wraps the model in the Claude
Code harness: its own system prompt, its own defaults. A cheating rate
measured through it is a number about that wrapper, not about the bare model,
and it does not reproduce anyone's published baseline. Use it to check the
harness runs; use an API key (run_arms.py --model anthropic/...) for numbers.

Selected via run_arms.py --model claude-cli/<model>, e.g. claude-cli/haiku.
The provider registers when this module is imported, which run_arms.py does.
"""
import asyncio

from inspect_ai.model import GenerateConfig, ModelAPI, ModelOutput, modelapi


@modelapi(name="claude-cli")
def claude_cli():
    return ClaudeCLI


class ClaudeCLI(ModelAPI):
    def __init__(self, model_name, base_url=None, api_key=None,
                 config=GenerateConfig(), **model_args):
        super().__init__(model_name, base_url, api_key, [], config)

    async def generate(self, input, tools, tool_choice, config):
        parts = []
        for m in input:
            text = (getattr(m, "text", "") or "").strip()
            if text:
                parts.append(f"[{m.role.upper()}]\n{text}")
        prompt = ("Continue this conversation as the ASSISTANT. Reply with "
                  "the assistant's next message only.\n\n"
                  + "\n\n".join(parts))
        cmd = ["claude", "-p"]
        if self.model_name and self.model_name != "default":
            cmd += ["--model", self.model_name]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")), timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude -p exit {proc.returncode}: "
                f"{err.decode('utf-8', 'replace')[:300]}")
        return ModelOutput.from_content(
            model=self.model_name, content=out.decode("utf-8", "replace"))
