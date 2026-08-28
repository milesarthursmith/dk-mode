# Sandbox for the hooked arms: a real Claude Code run with dk-mode installed
# as a real plugin, so its hooks fire as processes rather than being
# reimplemented by the harness.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash curl ca-certificates jq git \
    && rm -rf /var/lib/apt/lists/*

# dk-mode itself. Copied, not cloned, so the image tests the working tree.
COPY plugin/ /opt/dk-mode/

# The hooks are registered at PROJECT level, not in ~/.claude: inspect_swe
# seeds the home-directory settings itself and would clobber a home-level
# file. DK_MEM is set explicitly because ${CLAUDE_PLUGIN_DATA} is only
# populated by a real `claude plugin install`.
RUN mkdir -p /work/.claude /opt/dk-mem \
 && printf '%s\n' '{' \
  '  "hooks": {' \
  '    "UserPromptSubmit": [{"hooks": [{"type": "command",' \
  '      "command": "DK_MEM=/opt/dk-mem bash /opt/dk-mode/scripts/dk_recall.sh"}]}],' \
  '    "PostToolUse": [{"hooks": [{"type": "command",' \
  '      "command": "DK_MEM=/opt/dk-mem python3 /opt/dk-mode/scripts/dk_tripwire.py"}]}],' \
  '    "Stop": [{"hooks": [{"type": "command",' \
  '      "command": "DK_MEM=/opt/dk-mem bash /opt/dk-mode/scripts/dk_capture.sh"}]}]' \
  '  }' \
  '}' > /work/.claude/settings.json \
 && bash /opt/dk-mode/scripts/dk_bootstrap.sh /opt/dk-mem

WORKDIR /work
