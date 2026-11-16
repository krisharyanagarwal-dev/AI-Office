import pathlib

p = pathlib.Path("hive/agents/god/bin/agent_manager.js")
s = p.read_text(encoding="utf-8")

# reportStatus() builds the object and console.logs it but never persists it.
# The IDLE branch's writeStatus(status) was the only thing writing
# hive/agents/god/status.json. Removing that call to make reportStatus the
# "single writer" left reportStatus with no write at all, so status.json froze
# at the last write from the previous process. The STATUS lines kept appearing
# in the log, which is exactly why it looked healthy.
#
# So the correct shape is the one I intended: reportStatus persists, and nothing
# else does.
OLD = """    if (runResult.floor_rollup && runResult.floor_rollup.floor_rollup) status.floor_rollup = runResult.floor_rollup.floor_rollup;
    console.log('[' + AGENT_ID + '] STATUS: ' + JSON.stringify(status));
    return status;
  }"""
NEW = """    if (runResult.floor_rollup && runResult.floor_rollup.floor_rollup) status.floor_rollup = runResult.floor_rollup.floor_rollup;
    console.log('[' + AGENT_ID + '] STATUS: ' + JSON.stringify(status));
    // Persist here, once, and nowhere else. This is the only writer of
    // status.json: the console.log above is not persistence, and a status file
    // that only ever gets a log line beside it is a file that goes stale while
    // looking busy. Wrapped because a failed write must not kill the cycle.
    try {
      writeStatus(status);
    } catch (err) {
      logAgent('ERROR', 'status write failed: ' + (err && err.message));
    }
    return status;
  }"""
assert s.count(OLD) == 1, "anchor=%d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  reportStatus now persists status; single writer restored correctly")
