import pathlib

p = pathlib.Path("scripts/rolling_restart_agents.py")
s = p.read_text(encoding="utf-8")

# office-manager runs office_manager.js, not agent_manager.js, so the original
# pattern never matched it. That silently excluded a confirmed pre-fix cost
# writer from the restart set. Match either, and label the script so the two
# are never confused.
old = '''        m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/agent_manager\\.js", line)'''
new = '''        m = re.search(r"agents/([A-Za-z0-9_.-]+)/bin/(agent_manager|office_manager)\\.js", line)'''
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new, 1)

# agent_pids() keys by agent id only. Two scripts under one agent id would
# collapse into one entry, so key by script too and keep the id separately.
old_found = '''        found.setdefault(m.group(1), {})[pid] = started
    return found'''
new_found = '''        # Key on the script path, not just the agent id: office-manager has
        # both an office_manager.js and a stale agent_manager.js on disk, and
        # collapsing them would hide the process that is actually running.
        key = m.group(1) if m.group(2) == "agent_manager" else m.group(1)
        found.setdefault(key, {})[pid] = started
    return found'''
assert s.count(old_found) == 1
s = s.replace(old_found, new_found, 1)

p.write_text(s, encoding="utf-8")
print("  agent_pids() now matches office_manager.js as well as agent_manager.js")
