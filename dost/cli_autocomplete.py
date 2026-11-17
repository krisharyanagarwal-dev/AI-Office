"""CLI autocomplete support for THE CLAUDE COMPANY — Dost.

Generates bash/zsh completion scripts and provides completion logic for
dost CLI flags, subcommands, and workspace actions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

# Directory containing this module (the dost package dir).
DOST_DIR = str(Path(__file__).resolve().parent)

# Top-level dost flags (long options).
DOST_FLAGS: List[str] = [
    "--department",
    "--briefing",
    "--push-telegram",
    "--status",
    "--results",
    "--history",
    "--dispatch",
    "--debate",
    "--template",
    "--memory",
    "--context",
    "--health",
    "--doctor",
    "--workspace",
    "--create-workspace",
    "--list-workspaces",
    "--add-user",
    "--export",
    "--synthesis",
    "--review",
    "--auto-archive",
    "--weekly-digest",
    "--results-status",
    "--results-agent",
    "--history-regex",
    "--briefing-now",
]

# Flags that take a value argument (not boolean flags).
DOST_FLAGS_WITH_VALUE: List[str] = [
    "--department",
    "--history",
    "--dispatch",
    "--debate",
    "--template",
    "--workspace",
    "--create-workspace",
    "--export",
    "--review",
    "--results-status",
    "--results-agent",
    "--history-regex",
    "--add-user",
]

# Flags that accept a fixed set of values.
DOST_FLAG_VALUES: dict[str, List[str]] = {
    "--department": ["research", "trading", "fleet", "ops", "upgrade", "assistant"],
    "--export": ["md", "json"],
    "--results-status": ["pending", "running", "completed", "failed"],
}

# Top-level subcommands.
DOST_COMMANDS: List[str] = ["workspace"]

# Workspace subcommand actions and their argument specs.
WORKSPACE_ACTIONS: dict[str, dict] = {
    "list": {"args": 0, "completions": []},
    "create": {"args": 1, "completions": []},
    "add-user": {"args": 3, "completions": ["admin", "editor", "viewer"]},
}


def get_completions(prefix: str, context: List[str]) -> List[str]:
    """Return matching completions for a prefix given the current context.

    context is a list of tokens already typed on the command line (the
    program name excluded). Returns a list of matching completion strings.
    """
    if not context:
        return [f for f in DOST_FLAGS + DOST_COMMANDS if f.startswith(prefix)]

    first = context[0]

    # --- `dost workspace <action> ...` completion -------------------------
    if first == "workspace":
        if len(context) == 1:
            return [
                a for a in WORKSPACE_ACTIONS if a.startswith(prefix)
            ]
        action = context[1]
        spec = WORKSPACE_ACTIONS.get(action, {})
        if len(context) == 2:
            return [a for a in WORKSPACE_ACTIONS if a.startswith(prefix)]
        # Inside action arguments
        if action == "create":
            if len(context) == 3:
                return []
            return []
        if action == "add-user":
            # add-user <workspace_id> <email> [role]
            pos = len(context) - 2  # subtract 'workspace' and 'add-user'
            if pos == 2:
                return []  # workspace_id — no static completions
            if pos == 3:
                return []  # email — no static completions
            if pos == 4:
                return [
                    r for r in spec["completions"] if r.startswith(prefix)
                ]
            return []

    # --- Flag completion ---------------------------------------------------
    if prefix.startswith("--"):
        return [f for f in DOST_FLAGS if f.startswith(prefix)]

    # --- Value completion for a flag --------------------------------------
    # Find the flag that this value belongs to.
    flag = None
    for tok in reversed(context):
        if tok in DOST_FLAGS_WITH_VALUE:
            flag = tok
            break
    if flag:
        values = DOST_FLAG_VALUES.get(flag)
        if values:
            return [v for v in values if v.startswith(prefix)]
        # Special case: --department handled above via DOST_FLAG_VALUES
        if flag == "--add-user":
            return []

    return []


def _bash_script() -> str:
    """Return the bash completion script."""
    script = """_dost_autocomplete() {
    local cur prev words cword
    _get_comp_words_by_ref cur prev words cword 2>/dev/null || {
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
        words=("${COMP_WORDS[@]}")
        cword=$COMP_CWORD
    }

    # Build context array (skip program name at index 0)
    local context=()
    local i
    for ((i=1; i<cword; i++)); do
        context+=("${words[i]}")
    done

    local completions=()
    mapfile -t completions < <(python3 -c "
import sys
sys.path.insert(0, '<<DOST_DIR>>')
from cli_autocomplete import get_completions
prefix = sys.argv[1]
context = sys.argv[2:]
print('\\n'.join(get_completions(prefix, context)))
" "$cur" "${context[@]}" 2>/dev/null)

    COMPREPLY=()
    for c in "${completions[@]}"; do
        COMPREPLY+=("$c")
    done
}

complete -F _dost_autocomplete dost
"""
    return script.replace("<<DOST_DIR>>", DOST_DIR)


def _zsh_script() -> str:
    """Return the zsh completion script."""
    script = """#compdef dost

_dost_autocomplete() {
    local cur context state line
    _arguments '*: :_dost_values'
}

_dost_values() {
    local cur="${words[$CURRENT]}"
    # Build context (skip program name)
    local context=("${(@)words[1,${CURRENT}-1]}")

    local completions=()
    completions=(${(f)"$(python3 -c "
import sys
sys.path.insert(0, '<<DOST_DIR>>')
from cli_autocomplete import get_completions
prefix = sys.argv[1]
context = sys.argv[2:]
print('\\n'.join(get_completions(prefix, context)))
" "$cur" "${(@)context}" 2>/dev/null)"})

    _describe 'dost completions' completions
}

_dost_autocomplete "$@"
"""
    return script.replace("<<DOST_DIR>>", DOST_DIR)


def register_autocomplete(shell: str = "bash") -> str:
    """Generate a shell completion script for dost.

    Args:
        shell: Either "bash" or "zsh".

    Returns:
        The shell completion script as a string.
    """
    shell = shell.lower()
    if shell == "zsh":
        return _zsh_script()
    return _bash_script()


def register_in_shell(rc_file: str = None) -> bool:
    """Register autocomplete in the shell rc file.

    Appends the bash completion script to ~/.bashrc or ~/.zshrc.

    Args:
        rc_file: Path to the rc file. Defaults to ~/.bashrc or ~/.zshrc
                 based on the SHELL env var.

    Returns:
        True if the script was appended successfully.
    """
    if rc_file is None:
        shell = os.environ.get("SHELL", "")
        if "zsh" in shell:
            rc_file = str(Path.home() / ".zshrc")
        else:
            rc_file = str(Path.home() / ".bashrc")

    rc_path = Path(rc_file)
    script = register_autocomplete("bash")
    marker = "# dost autocomplete"

    try:
        if rc_path.exists():
            existing = rc_path.read_text()
            if marker in existing:
                # Already registered
                return True
        else:
            existing = ""

        with open(rc_path, "a") as f:
            f.write(f"\n{marker}\n{script}\n")
        return True
    except OSError:
        return False
