#!/bin/bash
# audit.sh — durable, read-only fleet audit. Report-only: it never remediates.
#
# Written against failures observed on 2026-10-16, four of which this script reproduced itself:
#   1. com.aryan.env-key-health exits 1 every run (its .env moved) and logs to a path its plist
#      does not use, so nothing recorded that it had been dead for weeks.
#   2. com.aryan.fleet-git-sync prints "FATAL no repo" then `exit 0`, so launchd calls a no-op a
#      success. A job that exits 0 while doing nothing is the dangerous kind of clean.
#   3. macOS has no `timeout`; probes wrapped in it yield "0 results" that read as "clean".
#   4. A catch-all SPA answers 200 on every path, so "got a 200" is not evidence of health —
#      but a bogus path in the WRONG namespace also falsely condemns a healthy service
#      (HUD: /api/anything -> 404, /anything -> 200). Bogus paths must share the real path's dir.
#   5. Where there is no remote branch to diff against, "nothing unpushed" must be reported as
#      UNMEASURED. Silence is not a clean.
#   6. A score of 2 told you nothing: SEVERITY is a MAX over {0,1,2}, one raise per non-empty group,
#      so 65 consecutive reports read 2 whether the run found one problem or forty. Every raise now
#      carries its item count, and the report prints `**Findings:** severity-2 = N, severity-1 = M`.
# Hence: absolute binaries, hard PATH, fail-loud preflight, and a non-vacuity count beside every verdict.

set -uo pipefail

export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/local/bin
export LC_ALL=C

B_GIT=/usr/bin/git
B_CURL=/opt/local/bin/curl
B_FIND=/usr/bin/find
B_SED=/usr/bin/sed
B_AWK=/usr/bin/awk
B_DATE=/bin/date
B_SHASUM=/usr/bin/shasum
B_LCTL=/bin/launchctl
B_PY=/usr/bin/python3
B_GREP=/usr/bin/grep
B_PLUTIL=/usr/bin/plutil
# /bin/kill -0 is a pure existence probe: it delivers no signal and writes nothing.
B_KILL=/bin/kill

AUDIT_HOME="$HOME/audit"
REPORT_DIR="$AUDIT_HOME/reports"
LOG_DIR="$AUDIT_HOME/logs"
STAMP="$($B_DATE -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/audit-$STAMP-$$.md"

# Credential classes. Length floors transcribed from the publish gate's own regexes
# (~/bin/fleet-workflow.sh SECRET_RE) where one exists - a stricter scanner than the gate
# reports a false clean, and the real historical exposure was exactly a 16-char fragment.
CRED_CLASSES=(
  'github_pat|github_pat_[A-Za-z0-9_]{20,}'
  'github_ghp|ghp_[A-Za-z0-9]{20,}'
  'nvidia_nvapi|nvapi-[A-Za-z0-9_-]{16,}'
  'openai_sk|sk-[A-Za-z0-9]{20,}'
  'aws_key|AKIA[A-Z0-9]{16}'
)

REQUIRED_BINS=("$B_GIT" "$B_CURL" "$B_FIND" "$B_SED" "$B_AWK" "$B_DATE" "$B_SHASUM" "$B_LCTL" "$B_PY" "$B_GREP" "$B_PLUTIL" "$B_KILL")

SEVERITY=0
# Per-severity finding counts. SEVERITY is only a MAX over {0,1,2} and there is no tier 3, so the score
# cannot distinguish one tier-2 finding from forty - the reason 65 consecutive reports all read 2.
# Every raise carries the number of findings it stands for, so the ceiling stays a ceiling and the
# tally is what ranks and trends. Tier 0 groups (historical statuses, informational notes, parser
# limits) are listed but deliberately not counted: they are not findings. The word "severity" is
# used on the emitted line rather than "tier" because README's layer table already calls the
# launchd job tier 1 and the digest reader tier 2 - two different meanings for one token.
S2=0; S1=0
raise() {
  local sev="$1" n="${2:-1}"
  case "$sev" in
    2) S2=$((S2 + n)) ;;
    1) S1=$((S1 + n)) ;;
  esac
  if [ "$sev" -gt "$SEVERITY" ] 2>/dev/null; then SEVERITY=$sev; fi
  return 0
}

digest8() { printf '%s' "$1" | "$B_SHASUM" -a 256 | "$B_AWK" '{print $1}' | cut -c1-8; }

# pid_state <pid> -> NOT_RUNNING | ALIVE | DEAD | UNVERIFIED
# `launchctl list` prints "-" in the PID column when a job is not running, so anything else is a
# candidate live PID - but a candidate is not proof. A nonzero status beside a stale or reused PID
# would be forgiven by mistake, which is the false-clean class this whole audit exists to refuse.
# ALIVE therefore requires a numeric PID AND a successful `/bin/kill -0` existence probe (delivers
# no signal, writes nothing). EPERM means the PID exists but belongs to someone else: for a job in
# our own GUI domain that is far more likely PID reuse than ownership, so it is UNVERIFIED, not
# ALIVE. Anything we cannot establish stays a fault and is labelled unverified.
pid_state() {
  local pid="${1:-}" err
  # "-" is launchd's explicit "not running" marker - definitive, so check it before the
  # non-digit guard, which would otherwise swallow it and call a stopped job unverified.
  if [ "$pid" = "-" ]; then echo NOT_RUNNING; return 0; fi
  case "$pid" in
    ''|*[!0-9]*) echo UNVERIFIED; return 0 ;;
  esac
  err=$("$B_KILL" -0 "$pid" 2>&1)
  case "$?" in
    0) echo ALIVE ;;
    *) case "$err" in
         *'No such process'*) echo DEAD ;;
         *)                   echo UNVERIFIED ;;
       esac ;;
  esac
}

# proc_name <pid> -> the live process's command, for annotation only. Optional: if ps is
# unavailable the classification still stands on the existence probe.
proc_name() {
  local n
  [ -x /bin/ps ] || { echo 'ps-unavailable'; return 0; }
  n=$(/bin/ps -o comm= -p "$1" 2>/dev/null | "$B_SED" -E 's/^[[:space:]]+//; s/[[:space:]]+$//')
  [ -n "$n" ] || n='gone'
  printf '%s' "$n"
}

# cred_class <haystack> -> "<class>|<token-length>|<sha256/8>". Reports the matched TOKEN's
# length, never the enclosing URL's, and never echoes the value: a diagnostic that reveals a
# secret is a flaw in the diagnostic.
cred_class() {
  local v="$1" entry cls pat m
  for entry in "${CRED_CLASSES[@]}"; do
    cls="${entry%%|*}"; pat="${entry#*|}"
    m=$(printf '%s' "$v" | "$B_GREP" -oE "$pat" | "$B_AWK" 'NR==1{print; exit}')
    if [ -n "$m" ]; then
      printf '%s|%d|%s' "$cls" "${#m}" "$(digest8 "$m")"
      return 0
    fi
  done
  return 1
}

emit_group() {
  local title="$1" sev="$2"; shift 2
  echo "### $title" >> "$REPORT"
  if [ "$#" -eq 0 ]; then
    echo "- none" >> "$REPORT"
  else
    printf -- '- %s\n' "$@" >> "$REPORT"
    # One raise per non-empty group used to discard how many items it held, which is what made the
    # ceiling uninformative: 1 leaked credential and 40 both moved SEVERITY from 1 to 2 and nothing
    # else. The item count is now carried through the raise.
    raise "$sev" "$#"
  fi
  echo >> "$REPORT"
}

mkdir -p "$REPORT_DIR" "$LOG_DIR" || { echo "FATAL: cannot create $REPORT_DIR" >&2; exit 3; }

# ---------------------------------------------------------------- preflight
MISSING=()
for b in "${REQUIRED_BINS[@]}"; do [ -x "$b" ] || MISSING+=("$b"); done
if [ "${#MISSING[@]}" -gt 0 ]; then
  {
    echo "# Fleet audit $STAMP"
    echo
    echo "**INSTRUMENT_FAILURE** - required binaries absent: ${MISSING[*]}"
    echo
    echo "No verdict in this run is valid. This report intentionally contains no CLEAN claims."
  } > "$REPORT"
  ln -sfn "$(basename "$REPORT")" "$REPORT_DIR/latest.md"
  echo "INSTRUMENT_FAILURE: missing ${MISSING[*]}" >&2
  exit 3
fi

# Truncate exactly once, here. Every other write in this script appends, so a second run that lands in
# the same second (same stamp, and the suite plus a manual kick often do) used to APPEND its body to the
# first run's file: the merged report carried two `**SEVERITY:**` lines and the older run's items sat
# under headings the newer run had already declared `- none`. A test mutant inherited its baseline's
# body this way and read as "MUTANT EQUIVALENT" - a false accusation against correct code.
: > "$REPORT" || { echo "FATAL: cannot reset $REPORT" >&2; exit 3; }
{
  echo "# Fleet audit $STAMP"
  echo
  echo "**Host:** $($B_DATE -u '+%Y-%m-%dT%H:%M:%SZ')  **Mode:** read-only, report-only"
  echo
} >> "$REPORT"

# ---------------------------------------------------------------- 1. git backing state
echo "## 1. Repository backing state" >> "$REPORT"
echo >> "$REPORT"
NOREMOTE=(); NOUPSTREAM=(); AHEAD=(); UNMEASURED=(); DIRTY=(); CREDREM=(); NOCOMMIT=()
BACKED=(); DETACHED=()
# Is this commit already published on SOME remote branch, not merely on the one branch this repo
# happens to track? Measured 2026-10-25: openalice-fleet read as "unpushed=2 vs
# origin/feat/hud-service-lifecycle" while HEAD was an ancestor of remote
# qoder/reconcile-office-20261023, and trading-bot's ba6772eb sat on the remote as
# backup/laptop-hermes-main-20261010. Two of five "unpushed" rows were therefore not data loss.
# Cached refs only - this audit never fetches - so a miss here proves nothing about the remote.
PUBREF=""
find_pub_ref() { # $1 = repo; sets PUBREF to the bare branch name (origin/ stripped) or empty
  PUBREF=""
  PUBREF=$("$B_GIT" -C "$1" for-each-ref --contains HEAD \
            --format='%(refname:short)' 'refs/remotes/origin/' 2>/dev/null \
          | "$B_AWK" 'NR==1{sub(/^origin\//,""); print}')
  [ -n "$PUBREF" ]
}
is_detached() { # $1 = repo; true when HEAD is not a branch
  ! "$B_GIT" -C "$1" symbolic-ref -q HEAD >/dev/null 2>&1
}
REPOS_SCAN=0
# maxdepth 5, not 3: at depth 3 this walk missed 8 real repos (agent-workspaces/PolymarketVault,
# .openalice/workspaces/*, fleet-workers/*/ws, oa-strat worktrees). An unmeasured repo is a false clean.
REPOLIST=$("$B_FIND" "$HOME" -maxdepth 5 \
  \( -name Library -o -name .Trash -o -name node_modules -o -name .qoder -o -name .claude \
     -o -name Backups -o -name Applications -o -name .secrets-backup -o -name '.hud-mgr-fixture-*' \
     -o -name 'site-packages' -o -name 'venv' -o -name '.venv' \) -prune -o \
  -name .git -type d -print 2>/dev/null | "$B_SED" 's#/.git$##')

while IFS= read -r r; do
  [ -n "$r" ] || continue
  [ -d "$r" ] || continue
  REPOS_SCAN=$((REPOS_SCAN + 1))
  url=$("$B_GIT" -C "$r" config --get remote.origin.url 2>/dev/null || true)
  branch=$("$B_GIT" -C "$r" rev-parse --abbrev-ref HEAD 2>/dev/null || echo NO-HEAD)
  dirty=$("$B_GIT" -C "$r" status --porcelain 2>/dev/null | "$B_AWK" 'END{print NR}')

  if [ -z "$url" ]; then
    NOREMOTE+=("$r dirty=${dirty:-0}")
  else
    if cinfo=$(cred_class "$url"); then
      CREDREM+=("$r class=$(printf '%s' "$cinfo" | cut -d'|' -f1) len=$(printf '%s' "$cinfo" | cut -d'|' -f2) id=$(printf '%s' "$cinfo" | cut -d'|' -f3)")
    fi
    up=$("$B_GIT" -C "$r" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
    if [ -n "$up" ]; then
      ahead=$("$B_GIT" -C "$r" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
      if [ "${ahead:-0}" -gt 0 ] 2>/dev/null; then
        if find_pub_ref "$r"; then
          BACKED+=("$r $ahead ahead of $up but published on origin/$PUBREF (cached refs; not fetched this run)")
        else
          AHEAD+=("$r unpushed=$ahead (vs $up; on no cached origin ref)")
        fi
      fi
    else
      # `rev-parse --abbrev-ref HEAD` answers the literal string "HEAD" when detached, so the
      # same-named-branch fallback below would build "origin/HEAD" - a default-branch pointer, not
      # this checkout's lineage. Measured: ~/.nvm is detached at a tag of upstream-owned nvm-sh/nvm
      # and was reported as tier-2 "unpushed=1 (vs origin/HEAD)". A detached commit is not
      # comparable to a branch, and the operator cannot push to a third-party upstream at all.
      # Tested BEFORE the NOUPSTREAM filing: a detached HEAD has no upstream by definition, so
      # filing it under "misconfiguration, not absence" as well double-counts it and labels the
      # first one wrong - proven by run 36, where the repo appeared in both groups.
      if is_detached "$r"; then
        DETACHED+=("$r HEAD=$("$B_GIT" -C "$r" rev-parse --short HEAD 2>/dev/null) detached - push state not comparable to any branch")
      else
        NOUPSTREAM+=("$r (origin exists, no tracking branch - misconfiguration, not absence)")
        # No upstream: fall back to the same-named remote branch, and if that is absent too say
        # UNMEASURED out loud rather than letting "none" imply "safe".
        rb="origin/$branch"
        if "$B_GIT" -C "$r" rev-parse --verify --quiet "$rb" >/dev/null 2>&1; then
          ahead=$("$B_GIT" -C "$r" rev-list --count "$rb..HEAD" 2>/dev/null || echo 0)
          if [ "${ahead:-0}" -gt 0 ] 2>/dev/null; then
            if find_pub_ref "$r"; then
              BACKED+=("$r $ahead ahead of $rb but published on origin/$PUBREF (cached refs; not fetched this run)")
            else
              AHEAD+=("$r unpushed=$ahead (vs $rb, no upstream configured; on no cached origin ref)")
            fi
          fi
        else
          UNMEASURED+=("$r branch=$branch has no $rb - pushed-state CANNOT be proven, do not read 'none' above as safe")
        fi
      fi
    fi
  fi
  [ "$branch" = "NO-HEAD" ] && NOCOMMIT+=("$r (zero commits - nothing to back up)")
  [ "${dirty:-0}" -gt 0 ] 2>/dev/null && DIRTY+=("$r dirty=$dirty")
done <<< "$REPOLIST"

# bash 3.2 + `set -u`: an empty array expansion must be guarded or the audit aborts mid-run.
emit_group "No remote at all (single copy on disk)" 1 ${NOREMOTE[@]+"${NOREMOTE[@]}"}
emit_group "Origin exists but no upstream tracking branch" 1 ${NOUPSTREAM[@]+"${NOUPSTREAM[@]}"}
emit_group "Zero-commit repo (backup impossible)" 1 ${NOCOMMIT[@]+"${NOCOMMIT[@]}"}
# Tier 1, not 2: the commit exists on the remote, just not on the tracked branch. Nothing is lost;
# reporting it as "unpushed" made two of five rows read as data loss when they were not.
emit_group "Published on another remote branch (not the tracked one)" 1 ${BACKED[@]+"${BACKED[@]}"}
emit_group "Detached HEAD (push state not comparable)" 1 ${DETACHED[@]+"${DETACHED[@]}"}
emit_group "Commits present but unpushed" 2 ${AHEAD[@]+"${AHEAD[@]}"}
emit_group "PUSH STATE UNMEASURED (no remote branch to diff against)" 2 ${UNMEASURED[@]+"${UNMEASURED[@]}"}
emit_group "Uncommitted changes" 1 ${DIRTY[@]+"${DIRTY[@]}"}
emit_group "CREDENTIAL EMBEDDED IN REMOTE URL (plaintext in .git/config)" 2 ${CREDREM[@]+"${CREDREM[@]}"}

{
  echo "**Non-vacuity:** repos scanned = $REPOS_SCAN"
  [ "$REPOS_SCAN" -eq 0 ] && echo "WARNING: zero repos found - every 'none' above is unmeasured, not clean."
  echo
} >> "$REPORT"

# ---------------------------------------------------------------- 2. scheduled jobs that lie
echo "## 2. Scheduled jobs: does each still point at something real?" >> "$REPORT"
echo >> "$REPORT"
# Python because BSD sed/grep differ from GNU, and a delimiter collision silently yields an empty
# result set - the exact false-clean class this audit exists to catch.
JOBROWS=$("$B_PY" - "$HOME" "$B_GIT" <<'PY'
import os, re, glob, plistlib, sys, subprocess
home = sys.argv[1]
gitbin = sys.argv[2]
assign = re.compile(r'^[ \t]*[A-Za-z_]+=([^\s#]+)')
scanned = 0
progcands = 0
# Installed/system locations are not the operator's authored, unbacked source.
SYS_PREFIX = ('/bin/', '/usr/', '/sbin/', '/opt/', '/etc/', '/Library/', '/System/', '/private/')
ARTIFACT_DIRS = ('node_modules', '.venv', 'venv', 'site-packages', '.nvm')

def repo_root(path):
    # Walk upward, but never past the scanned home: what lies above it is not in scope for this audit.
    d = os.path.dirname(path)
    while len(d) >= len(home) and (d == home or d.startswith(home + os.sep)):
        if os.path.exists(os.path.join(d, '.git')):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None

def load(path):
    # plistlib (pure-python XML) is stricter than Apple's parser and rejected three plists that
    # `plutil -lint` calls OK. Never report someone's config as broken because our parser is limited:
    # fall back to plutil-normalised XML, and label a real failure TOOL_LIMITED.
    try:
        return plistlib.load(open(path, 'rb')), ''
    except Exception as e1:
        try:
            xml = subprocess.run(['/usr/bin/plutil', '-convert', 'xml1', '-o', '-', path],
                                 capture_output=True, timeout=20)
            if xml.returncode == 0 and xml.stdout:
                import io
                return plistlib.load(io.BytesIO(xml.stdout)), 'via_plutil'
        except Exception:
            pass
        return None, str(e1)[:70]

for plist in sorted(glob.glob(os.path.join(home, 'Library', 'LaunchAgents', '*.plist'))):
    if '.bak' in plist:
        continue
    scanned += 1
    p, note = load(plist)
    if p is None:
        print('\t'.join(['TOOL_LIMITED', os.path.basename(plist), 'plistlib+plutil both failed: ' + note]))
        continue
    raw_label = p.get('Label')
    if not raw_label:
        # Do NOT fall back to the filename: that made `label + '.plist' != basename` below
        # unfalsifiable, so every label-less plist (Google's Keystone stubs here are `<dict/>`)
        # filed under the tier-2 mismatch group and pinned severity at the ceiling forever.
        print('\t'.join(['NO_LABEL', os.path.basename(plist), '']))
        continue
    label = raw_label
    if note:
        print('\t'.join(['PARSED_BY_FALLBACK', label, 'needed plutil fallback']))
    print('\t'.join(['LABEL', label, '']))
    if label + '.plist' != os.path.basename(plist):
        print('\t'.join(['LABEL_FILE_MISMATCH', label, os.path.basename(plist)]))
    args = p.get('ProgramArguments') or []
    prog = args[-1] if args else ''
    seenlog = set()
    for key in ('StandardOutPath', 'StandardErrorPath'):
        v = p.get(key) or ''
        if v.startswith('/tmp/') and v not in seenlog:
            seenlog.add(v)
            print('\t'.join(['LOGTMP', label, v]))
    # The executable is NOT necessarily the last argv element. On this host the live plists end with a
    # flag (`--watchdog`, `--apply`, `6`), so keying the scan on args[-1] skipped 4 of the 5 jobs that
    # execute ~/bin: `rm ~/bin/opencode-fleet-monitor.sh` produced zero findings while the report still
    # read "plists scanned = 39". Candidates are every absolute argv element that is not a system
    # binary; the interpreter (`/bin/bash`, a framework python3) is deliberately not a finding target.
    cands = [a for a in args if isinstance(a, str) and a.startswith('/') and not a.startswith(SYS_PREFIX)]
    missing = [c for c in dict.fromkeys(cands) if not os.path.exists(c)]
    for m in missing:
        print('\t'.join(['MISSING_SCRIPT', label, m]))
    if missing:
        continue
    regular = [c for c in cands if os.path.isfile(c)]
    if not regular:
        continue
    # Is the thing launchd executes under version control at all? A directory with no `.git` yields no
    # repo, so the repo section reports nothing about it - silence read as clean, twice over: the file
    # is unbacked AND invisible to `fleet-durable-backup.sh`, which enumerates `find $HOME -name .git`.
    # A gitignored script counts as unversioned: nothing can restore it either.
    progcands += len(set(regular))
    for c in dict.fromkeys(regular):
        if not (c == home or c.startswith(home + os.sep)): continue
        if any(seg in ARTIFACT_DIRS for seg in c.split(os.sep)) or '/.local/share/uv/' in c: continue
        try:
            if b'\x00' in open(c, 'rb').read(8192): continue
        except Exception:
            continue
        root = repo_root(c)
        if root is None:
            print('\t'.join(['UNVERSIONED', label, c + ' (no git repo above it)']))
            continue
        try:
            chk = subprocess.run([gitbin, '-C', root, 'ls-files', '--error-unmatch', c],
                                 capture_output=True, timeout=10)
        except Exception:
            print('\t'.join(['UNVERIFIED_PROG', label, c + ' (git ls-files could not run)']))
            continue
        if chk.returncode == 0: continue
        if chk.returncode == 1:
            print('\t'.join(['UNVERSIONED', label, c + ' (untracked inside ' + root + ')']))
            continue
        print('\t'.join(['UNVERIFIED_PROG', label, c + ' (git ls-files rc=' + str(chk.returncode) + ')']))
    prog = regular[0]
    try:
        head8 = open(prog, 'rb').read(8192)
    except Exception:
        continue
    if b'\x00' in head8:
        continue  # a Mach-O or other binary must never be regex-scanned as text
    try:
        text = open(prog, errors='replace').read()
    except Exception:
        continue
    seen = set()
    for line in text.splitlines():
        m = assign.match(line)
        if not m:
            continue
        val = m.group(1).strip("\"'")
        if '$' in val or '*' in val or ';' in val or not val:
            continue
        if not (val.startswith('~') or val.startswith('/Users/')):
            continue
        exp = os.path.expanduser(val)
        if exp in seen:
            continue
        seen.add(exp)
        if not os.path.exists(exp):
            print('\t'.join(['MISSING_TARGET', label, exp]))
print('\t'.join(['SCANNED', str(scanned), '']))
print('\t'.join(['PROGCANDS', str(progcands), '']))
PY
)

PLIST_SCAN=$(printf '%s\n' "$JOBROWS" | "$B_AWK" -F'\t' '$1=="SCANNED"{print $2}')
[ -n "$PLIST_SCAN" ] || PLIST_SCAN=0

DEADJOB=(); NOScript=(); LOGTMP=(); TOOLLIMIT=(); MISMATCH=(); UNMEASUREDJOBS=(); NOLABEL=()
FALLBACK=()
UNVERPROG=(); UNVERPROG_UNCERTAIN=()
PROG_CANDS=$(printf '%s\n' "$JOBROWS" | "$B_AWK" -F'\t' '$1=="PROGCANDS"{print $2}')
[ -n "$PROG_CANDS" ] || PROG_CANDS=0
SCANNED_LABELS=$(printf '%s\n' "$JOBROWS" | "$B_AWK" -F'\t' '$1=="LABEL"{print $2}')
while IFS=$'\t' read -r kind a b; do
  [ -n "$kind" ] || continue
  case "$kind" in
    # A plist that only the lenient plutil fallback could read is NOT a tool
    # limitation and was not a finding until now: `Parser could not read plist`
    # printed "none" while 5 of 44 installed plists were being read solely by
    # plutil, because plistlib raised ExpatError on a `--` inside an XML comment.
    # That line was a false clean about XML validity, and the repo's own rule
    # (.github/copilot-instructions.md) is that plutil accepting it IS the trap -
    # launchd's parser does not, and it has shipped twice. Kept separate from
    # TOOL_LIMITED on purpose: here the config really is malformed.
    SCANNED|LABEL|PROGCANDS) : ;;
    PARSED_BY_FALLBACK    ) FALLBACK+=("$a - $b (strict XML rejected it; Apple's lenient parser only)") ;;
    NO_LABEL            ) NOLABEL+=("$a (no Label key - launchd cannot load it; NOT a filename mismatch)") ;;
    MISSING_TARGET      ) DEADJOB+=("$a -> target no longer exists: $b") ;;
    MISSING_SCRIPT      ) NOScript+=("$a -> job script itself missing: $b") ;;
    UNVERSIONED         ) UNVERPROG+=("$b - job $a") ;;
    UNVERIFIED_PROG     ) UNVERPROG_UNCERTAIN+=("$b - job $a") ;;
    LOGTMP              ) LOGTMP+=("$a logs to $b (wiped on reboot; no audit trail survives)") ;;
    TOOL_LIMITED        ) TOOLLIMIT+=("$a - $b (NOT a config defect; our parser failed)") ;;
    LABEL_FILE_MISMATCH ) MISMATCH+=("$a: Label vs filename mismatch ($b) - launchd bootstrap fails silently") ;;
  esac
done <<< "$JOBROWS"

# Exit status only for labels we actually scanned - a hardcoded prefix would ignore com.user.* jobs.
# UNITS, measured here: `launchctl list` TABLE column 2 is the ALREADY-DECODED result
#   exit 2 -> table "2"  and  per-label LastExitStatus 512 (= 2<<8)
#   exit 1 -> table "1"  and  per-label LastExitStatus 256 (= 1<<8)
#   SIGKILL-> table "-9"
# So the table value must NOT be bit-shifted, and a negative value is a signal - not a non-number
# to be skipped. Skipping "-9" would have silently dropped every killed job, which is a false clean.
# Column 1 is the PID, and "-" means not running: a nonzero status beside a LIVE pid is history, not
# a current fault. Measured on this host: launchd keeps the last exit status next to the running pid.
EXITED=()
HISTORICAL=()
UNVERIFIED_LIVE=()
NOTLISTED=()
UNK_COUNT=0
LCTXT=$("$B_LCTL" list 2>/dev/null || true)
SELF_NOTE=""
while IFS= read -r label; do
  [ -n "$label" ] || continue
  row=$(printf '%s\n' "$LCTXT" | "$B_AWK" -v l="$label" '$3==l{print; exit}')
  if [ -z "$row" ]; then NOTLISTED+=("$label (plist present, not loaded in launchd)"); continue; fi
  pid=$(printf '%s' "$row" | "$B_AWK" '{print $1}')
  st=$(printf '%s' "$row" | "$B_AWK" '{print $2}')
  case "$st" in
    -'') UNK_COUNT=$((UNK_COUNT + 1)); continue ;;   # unknown is not evidence of health
    -*)  decoded="killed by signal ${st#-}" ;;
    0)   continue ;;
    *[!0-9]*) UNK_COUNT=$((UNK_COUNT + 1)); continue ;;
    *)   decoded="exited $st" ;;
  esac
  [ -n "${decoded:-}" ] || continue
  if [ "$label" = "com.aryan.audit" ]; then
    # This script exits with its severity by design; that is a verdict, not a fault.
    SELF_NOTE="com.aryan.audit -> $decoded (the audit declaring its own severity, not a fault)"
  else
    # NOT_RUNNING/DEAD keep the original EXITED wording so existing assertions still bind.
    pstate=$(pid_state "$pid")
    case "$pstate" in
      ALIVE) HISTORICAL+=("$label -> $decoded (table status $st) while pid $pid is running: HISTORICAL, not a current fault; pid currently=$(proc_name "$pid")") ;;
      UNVERIFIED) UNVERIFIED_LIVE+=("$label -> $decoded (table status $st, pid column '$pid'): LIVENESS UNVERIFIED - not claimed healthy") ;;
      *) EXITED+=("$label -> $decoded (table status $st)") ;;
    esac
  fi
  decoded=""
done <<< "$SCANNED_LABELS"

emit_group "Job targets a path that no longer exists (silently dead)" 2 ${DEADJOB[@]+"${DEADJOB[@]}"}
emit_group "Job script itself missing" 2 ${NOScript[@]+"${NOScript[@]}"}
# Severity 1, not 2: a GONE script is a dead job (2), an UNVERSIONED one is an unrecoverable edit (1) -
# and at 2 the ceiling would be pinned by something the operator may deliberately accept.
emit_group "Job executes a program that is not under version control (single copy, invisible to every backup)" 1 ${UNVERPROG[@]+"${UNVERPROG[@]}"}
emit_group "Program version-control state could NOT be verified (tool limit, not a clean)" 0 ${UNVERPROG_UNCERTAIN[@]+"${UNVERPROG_UNCERTAIN[@]}"}
emit_group "Last launchd exit status non-zero" 1 ${EXITED[@]+"${EXITED[@]}"}
emit_group "Non-zero exit status recorded while the job is running (HISTORICAL, not a current fault)" 0 ${HISTORICAL[@]+"${HISTORICAL[@]}"}
emit_group "Non-zero exit status whose liveness could NOT be verified (still reported as a fault)" 1 ${UNVERIFIED_LIVE[@]+"${UNVERIFIED_LIVE[@]}"}
emit_group "This audit's own job status (informational)" 0 ${SELF_NOTE:+"$SELF_NOTE"}
emit_group "plist on disk but job not loaded" 1 ${NOTLISTED[@]+"${NOTLISTED[@]}"}
emit_group "Label does not match filename (bootstrap fails)" 2 ${MISMATCH[@]+"${MISMATCH[@]}"}
emit_group "LaunchAgent plist has no Label key (cannot be loaded)" 1 ${NOLABEL[@]+"${NOLABEL[@]}"}
emit_group "Job logs into /tmp (history is destroyed)" 1 ${LOGTMP[@]+"${LOGTMP[@]}"}
emit_group "Parser could not read plist (tool limit, not your bug)" 0 ${TOOLLIMIT[@]+"${TOOLLIMIT[@]}"}
emit_group "Plist XML is invalid to a strict parser (only plutil could read it)" 1 ${FALLBACK[@]+"${FALLBACK[@]}"}

{
  echo "**Non-vacuity:** plists scanned = $PLIST_SCAN, labels checked = $(printf '%s\n' "$SCANNED_LABELS" | "$B_GREP" -c . || true), launchd rows = $(printf '%s\n' "$LCTXT" | "$B_AWK" 'END{print NR}'), status-unknown (never ran or unrecorded, NOT evidence of health) = $UNK_COUNT, current-faults = ${#EXITED[@]}, historical-live-pid = ${#HISTORICAL[@]}, liveness-unverified = ${#UNVERIFIED_LIVE[@]}, program candidates opened = $PROG_CANDS, unversioned-programs = ${#UNVERPROG[@]}, strict-parser-rejected = ${#FALLBACK[@]}"
  [ "${PLIST_SCAN:-0}" -eq 0 ] && echo "WARNING: zero plists scanned - the job checks above measured nothing."
  echo
} >> "$REPORT"

# ---------------------------------------------------------------- 3. service truth
echo "## 3. Loopback services: real route vs fabricated route in the SAME namespace" >> "$REPORT"
echo >> "$REPORT"
echo "A 200 alone is not evidence, and a bogus path in the wrong namespace falsely condemns a" >> "$REPORT"
echo "healthy service (HUD answers 200 on /anything for the SPA but 404 on /api/anything)." >> "$REPORT"
echo >> "$REPORT"

# Service ports list: space-separated lines (port path); env override for stubbing in tests
PROBE_LIST="${AUDIT_SERVICE_PORTS:-$(cat <<'EOF'
4747 /api/health
18789 /
19593 /v1/models
4950 /
EOF
)}"

UNDECIDABLE=0; PROBE_N=0
while IFS=' ' read -r port path; do
  # Skip empty lines
  [ -z "$port" ] && continue
  PROBE_N=$((PROBE_N + 1))

  dir=$("$B_SED" 's#/[^/]*$##' <<< "$path")
  case "$dir" in /*|"") : ;; *) dir="" ;; esac
  real=$("$B_CURL" -s -o /dev/null -m 6 -w '%{http_code}' "http://127.0.0.1:$port$path" 2>/dev/null)
  bogus=$("$B_CURL" -s -o /dev/null -m 6 -w '%{http_code}' "http://127.0.0.1:$port$dir/audit-bogus-zzz" 2>/dev/null)
  if [ -z "$real" ] || [ "$real" = "000" ]; then
    verdict="DEAD (no response)"; raise 2
  elif [ "$real" = "200" ] && [ "$bogus" = "200" ]; then
    verdict="UNPROVEN - 200 on a made-up sibling path too (catch-all); liveness NOT established"; UNDECIDABLE=$((UNDECIDABLE + 1))
  elif [ "$real" = "200" ]; then
    verdict="UP (200 real vs $bogus on $dir/audit-bogus-zzz = real router)"
  elif [ "$real" = "401" ] || [ "$real" = "403" ]; then
    verdict="LISTENING, auth-gated (real=$real) - reachable, health undetermined"; raise 1
  else
    verdict="DEGRADED (real=$real bogus=$bogus)"; raise 1
  fi
  printf -- '- :%s %s -> real=%s bogus=%s :: %s\n' "$port" "$path" "$real" "$bogus" "$verdict" >> "$REPORT"
done <<< "$PROBE_LIST"
printf '**Probes:** %s entries, %s undecidable from their probed namespace (reported, NOT scored)\n' "$PROBE_N" "$UNDECIDABLE" >> "$REPORT"
echo >> "$REPORT"

# ---------------------------------------------------------------- 4. redaction self-check
echo "## 4. Redaction self-check" >> "$REPORT"
echo >> "$REPORT"
LEAKS=0
for entry in "${CRED_CLASSES[@]}"; do
  pat="${entry#*|}"
  n=$("$B_GREP" -cE "$pat" "$REPORT" 2>/dev/null || true)
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  if [ "$n" -gt 0 ]; then LEAKS=$((LEAKS + n)); fi
done
if [ "$LEAKS" -gt 0 ]; then
  echo "**REDACTION_FAILURE:** $LEAKS credential-shaped string(s) survived in this report." >> "$REPORT"
  # Counted as ONE finding, not $LEAKS: LEAKS sums per-class line matches, so a single line can be
  # counted by several classes. The tally counts findings, the message counts matched strings.
  raise 2
else
  echo "Pass - report body re-scanned with all ${#CRED_CLASSES[@]} credential classes, matched none." >> "$REPORT"
fi
echo >> "$REPORT"

printf '**Findings:** severity-2 = %s, severity-1 = %s (SEVERITY is the max level reached, not a count)\n' "$S2" "$S1" >> "$REPORT"
echo "**SEVERITY:** $SEVERITY" >> "$REPORT"
ln -sfn "$(basename "$REPORT")" "$REPORT_DIR/latest.md"
"$B_FIND" "$REPORT_DIR" -maxdepth 1 -name 'audit-*.md' -mtime +30 -delete 2>/dev/null

echo "AUDIT_DONE stamp=$STAMP severity=$SEVERITY sev2=$S2 sev1=$S1 repos=$REPOS_SCAN plists=$PLIST_SCAN report=$REPORT"
exit "$SEVERITY"
