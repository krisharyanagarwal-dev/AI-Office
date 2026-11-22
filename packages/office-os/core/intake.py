"""
Intake watcher - polls a directory for .md files and converts them to tasks.
Any .md file dropped into ~/office-os/inbox/ becomes a task:

    # Task Title
    Task description goes here.
    
    <!-- agent: principal-architect -->
    <!-- priority: high -->

Files are moved to inbox/done/ after processing.
"""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.hive import Hive
from core.router import ProviderRouter
from agents.god_agent import GodAgent

INBOX_DIR = Path((os.environ.get("OFFICE_OS_HOME") or str(Path.home() / "office-os"))) / "inbox"
DONE_DIR = INBOX_DIR / "done"


def parse_markdown_task(md_path: Path) -> dict:
    """Parse a markdown file into task fields."""
    content = md_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Title from first # heading
    title = ""
    desc_lines = []
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## ") or line.startswith("### "):
            # Skip sub-headers as title candidates
            continue
        elif line.strip().startswith("<!--"):
            # HTML comment - skip
            continue
        elif line.strip().startswith("-->"):
            continue
        elif title and line.strip():
            desc_lines.append(line)
        elif title and not line.strip():
            desc_lines.append("")

    description = "\n".join(desc_lines).strip() or content.strip()

    # Parse HTML comments for agent and priority
    agent_id = None
    priority = "normal"
    for line in content.split("\n"):
        m = re.match(r"^\s*<!--\s*agent:\s*(\S+)\s*-->\s*$", line, re.IGNORECASE)
        if m:
            agent_id = m.group(1)
        m = re.match(r"^\s*<!--\s*priority:\s*(\w+)\s*-->\s*$", line, re.IGNORECASE)
        if m:
            priority = m.group(1).lower()

    return {
        "title": title or md_path.stem,
        "description": description,
        "agent_id": agent_id,
        "priority": priority,
    }


def process_inbox(hive: Hive, router: ProviderRouter, god: GodAgent):
    """Scan inbox dir for new .md files and convert them to tasks."""
    if not INBOX_DIR.exists():
        INBOX_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)

    for md_file in sorted(INBOX_DIR.glob("*.md")):
        try:
            task_data = parse_markdown_task(md_file)
            result = god.create_task(
                title=task_data["title"],
                description=task_data["description"],
                agent_id=task_data["agent_id"],
                priority=task_data["priority"],
                user_id="aryan",  # intake watcher runs as aryan
            )
            print(f"[intake] Created task {result['task_id']}: {task_data['title']}")
            # Move to done
            shutil.move(str(md_file), str(DONE_DIR / md_file.name))
        except Exception as e:
            print(f"[intake] Error processing {md_file.name}: {e}")
            # Move to done anyway to avoid reprocessing
            shutil.move(str(md_file), str(DONE_DIR / md_file.name))


def run_watch_loop(poll_interval: int = 10):
    """Continuously watch the inbox directory."""
    hive = Hive()
    router = ProviderRouter()
    god = GodAgent(hive, router)

    print(f"[intake] Watching {INBOX_DIR} every {poll_interval}s")
    while True:
        try:
            process_inbox(hive, router, god)
        except Exception as e:
            print(f"[intake] Error: {e}")
        time.sleep(poll_interval)


if __name__ == "__main__":
    run_watch_loop()