import pathlib

p = pathlib.Path("hive/agents/god/bin/agent_manager.js")
lines = p.read_text(encoding="utf-8").split("\n")

# Locate the console.log of STATUS inside reportStatus, and insert the write
# after it. Anchored on the log line + the following `return status;` so the
# insertion cannot land in a different function.
log_i = next((i for i, l in enumerate(lines)
              if "console.log('[' + AGENT_ID + '] STATUS: '" in l), None)
assert log_i is not None, "STATUS log line not found"
ret_i = next((i for i in range(log_i, min(log_i + 6, len(lines)))
              if lines[i].strip() == "return status;"), None)
assert ret_i is not None, "return status; not found after the log line"

INSERT = [
    "  // Persist here, once, and nowhere else. This is the only writer of",
    "  // status.json for this agent. The console.log above is not persistence:",
    "  // a status file that only has a log line beside it goes stale while the",
    "  // log looks busy. Wrapped because a failed write must not kill the cycle.",
    "  try {",
    "    writeStatus(status);",
    "  } catch (err) {",
    "    logAgent('ERROR', 'status write failed: ' + (err && err.message));",
    "  }",
]
lines[ret_i:ret_i] = INSERT
p.write_text("\n".join(lines), encoding="utf-8")
print("  inserted writeStatus into reportStatus at line %d" % (ret_i + 1))
