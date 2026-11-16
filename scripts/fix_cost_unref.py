import pathlib

# cost.js is the runtime (node resolves require('./cost') to the .js);
# cost.ts is the hand-maintained lockstep copy. Same one-token change each.
JS = pathlib.Path("lib/llm/cost.js")
TS = pathlib.Path("lib/llm/cost.ts")

js_old = "setInterval(() => { const n = new Date(); if (n.getHours()===0 && n.getMinutes()===0) resetDailyCosts(); }, 60000);"
js_new = "setInterval(() => { const n = new Date(); if (n.getHours()===0 && n.getMinutes()===0) resetDailyCosts(); }, 60000).unref();"

ts_old = """setInterval(() => {
  const now = new Date();
  if (now.getHours() === 0 && now.getMinutes() === 0) {
    resetDailyCosts();
  }
}, 60000);"""
ts_new = """setInterval(() => {
  const now = new Date();
  if (now.getHours() === 0 && now.getMinutes() === 0) {
    resetDailyCosts();
  }
}, 60000).unref();"""

for path, old, new in ((JS, js_old, js_new), (TS, ts_old, ts_new)):
    s = path.read_text(encoding="utf-8")
    assert s.count(old) == 1, "%s: expected exactly 1 match, got %d" % (path, s.count(old))
    path.write_text(s.replace(old, new, 1), encoding="utf-8")
    print("  patched %s" % path)
