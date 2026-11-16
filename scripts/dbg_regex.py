import re, subprocess

line = subprocess.check_output(["ps", "-p", "15443", "-o", "args="], text=True).strip()
print("  actual cmdline: %s" % line[:130])

new_re = re.compile(r"agents/([A-Za-z0-9_.-]+)/bin/(agent_manager|office_manager)\.js")
old_re = re.compile(r"agents/([A-Za-z0-9_.-]+)/bin/agent_manager\.js")

m = new_re.search(line)
print("  new regex match: %s" % (m.group(0) if m else None))
m2 = old_re.search(line)
print("  old regex match: %s" % (m2.group(0) if m2 else None))

# Is the process still alive at all?
alive = subprocess.run(["ps", "-p", "15443"], capture_output=True, text=True)
print("  pid 15443 alive: %s" % (alive.returncode == 0))

# What does the tool's own agent_pids() return for office?
import importlib.util
spec = importlib.util.spec_from_file_location("rr", "scripts/rolling_restart_agents.py")
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
except SystemExit:
    pass
pids = mod.agent_pids()
print("  tool sees %d agent ids" % len(pids))
print("  office-manager in tool's view: %s" % ("office-manager" in pids))
print("  mainbot in tool's view       : %s" % ("mainbot" in pids))
