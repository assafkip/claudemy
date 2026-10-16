#!/usr/bin/env python3
"""SessionStart hook: pass the plugin's ElevenLabs key to this session's shell.

Claude Code asks for the key once through the plugin's `userConfig` prompt
(masked, kept in the OS credential store) and hands it to hooks as
CLAUDE_PLUGIN_OPTION_ELEVENLABS_API_KEY. The audio renderer reads
ELEVENLABS_API_KEY, so this hook writes one export line to CLAUDE_ENV_FILE,
which Claude Code sources before each Bash command in the session.

It does nothing when the option is unset, when ELEVENLABS_API_KEY is already
set in the environment, or when CLAUDE_ENV_FILE is not provided. It never
prints the key.
"""
import os
import sys


def main() -> int:
    key = os.environ.get("CLAUDE_PLUGIN_OPTION_ELEVENLABS_API_KEY", "").strip()
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not key or not env_file or os.environ.get("ELEVENLABS_API_KEY"):
        return 0
    # Single-quote for the shell; the only character that needs escaping inside
    # single quotes is the single quote itself.
    quoted = "'" + key.replace("'", "'\\''") + "'"
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(f"export ELEVENLABS_API_KEY={quoted}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
