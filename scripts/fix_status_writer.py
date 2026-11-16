import pathlib

p = pathlib.Path("hive/agents/god/bin/agent_manager.js")
s = p.read_text(encoding="utf-8")

# The IDLE path calls writeStatus(status) with the local `status` object, which
# never receives the rollup patch. So reportStatus writes the verdict and then
# the very next thing that happens overwrites it, which is why the escalation
# logged correctly while status.json had no floor_rollup at all: the file is
# written twice per cycle, and the second write dropped it.
#
# The fix is to stop the cycle from writing a second, less complete object over
# the top of reportStatus's output. reportStatus is the single writer.

OLD_IDLE = """  if (!claim.success) { status.status = 'IDLE'; status.current_task = null; writeStatus(status); return { status: 'IDLE', worked, current_task: null, completed_task_id: null, result: null, evidence: null, floor_rollup: rollupPatchOut }; }"""
NEW_IDLE = """  // Do not writeStatus() here. reportStatus() runs immediately after this
  // returns and is the single writer for god's status, so writing a second,
  // less complete object here dropped fields -- including the floor-rollup
  // verdict -- the moment it was recorded.
  if (!claim.success) { status.status = 'IDLE'; status.current_task = null; return { status: 'IDLE', worked, current_task: null, completed_task_id: null, result: null, evidence: null, floor_rollup: rollupPatchOut }; }"""
assert s.count(OLD_IDLE) == 1, "idle anchor=%d" % s.count(OLD_IDLE)
s = s.replace(OLD_IDLE, NEW_IDLE, 1)

# The WORKING write is also a second writer, and it happens mid-cycle, so it can
# land after reportStatus on a fast cycle. Route the rollup verdict into it too
# rather than letting it go missing.
OLD_WORKING = """  status.status = 'WORKING'; status.current_task = task.task_id; writeStatus(status);"""
NEW_WORKING = """  status.status = 'WORKING'; status.current_task = task.task_id; if (rollupPatchOut && rollupPatchOut.floor_rollup) status.floor_rollup = rollupPatchOut.floor_rollup; writeStatus(status);"""
assert s.count(OLD_WORKING) == 1, "working anchor=%d" % s.count(OLD_WORKING)
s = s.replace(OLD_WORKING, NEW_WORKING, 1)

p.write_text(s, encoding="utf-8")
print("  single status writer: reportStatus no longer overwritten")
