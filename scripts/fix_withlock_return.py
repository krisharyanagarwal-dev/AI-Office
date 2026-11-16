import pathlib

p = pathlib.Path("lib/llm/cost.js")
s = p.read_text(encoding="utf-8")

OLD = "try { return fn(); } finally { try { fs.closeSync(fd); } catch (e) {} try { fs.unlinkSync(lockPath); } catch (e) {} } }"
NEW = "try { fn(); return true; } finally { try { fs.closeSync(fd); } catch (e) {} try { fs.unlinkSync(lockPath); } catch (e) {} } }"

assert s.count(OLD) == 1, "anchor count = %d" % s.count(OLD)
p.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")
print("  withLock now returns whether the LOCK was taken (true/false), not fn()'s value")
