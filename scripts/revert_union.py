import pathlib

# Restore lib/llm/cost.js from HEAD (the verified dirty-tracking state, 33/33)
# and re-apply only the withLock return-value fix, which was independently
# verified. The union-merge experiment is abandoned: it could not be made to
# keep its existing tests green, and cost records with no identity field
# collapsed to a single key.
import subprocess

src = subprocess.check_output(["git", "show", "HEAD:lib/llm/cost.js"], text=True)

OLD = "try { return fn(); } finally { try { fs.closeSync(fd); } catch (e) {} try { fs.unlinkSync(lockPath); } catch (e) {} } }"
NEW = "try { fn(); return true; } finally { try { fs.closeSync(fd); } catch (e) {} try { fs.unlinkSync(lockPath); } catch (e) {} } }"

assert src.count(OLD) == 1, "withLock anchor %d" % src.count(OLD)
src = src.replace(OLD, NEW, 1)
pathlib.Path("lib/llm/cost.js").write_text(src, encoding="utf-8")
print("  restored cost.js from HEAD + withLock return fix")
print("  union merge abandoned; dirty-tracking + lock + atomic write retained")
