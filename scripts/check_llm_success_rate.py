#!/usr/bin/env python3
"""Fleet LLM success rate: is the fleet actually able to do work?

Every other check in the truth summary looks at structure: credentials
present, feeds fresh, completions backed. None of them ask the question that
matters most operationally, which is whether agents are still getting
completions at all.

A fleet can pass every structural check and still be doing nothing. That is
exactly what happened: 46 of 58 agents were reporting

    [F1] executor llm_error All LLM providers failed [attempted: ...]
    [F1] executor finished: status=llm_error turns=0 tools=0 edits=0

while provider_credentials reported the required key missing and nothing
failed, because a missing credential is not an outage by itself when a
fallback can serve the request. Only the aggregate success rate shows that
nothing is being served.

This measures the semantic signal rather than request volume. A high request
count proves activity, not success. What proves failure is an executor
finishing a turn with zero work produced.

Exit codes match the truth-summary contract: 0 clean, 1 a real problem,
2 could not verify.
"""
import argparse
import glob
import os
import re
import sys
import time

DEFAULT_WINDOW_S = 900
DEFAULT_MIN_RATE = 70.0

FAIL_RE = re.compile(r"All LLM providers failed")
OK_RE = re.compile(r"LLM Response|Response received")
# An executor turn that ended without producing anything is the real signal.
NO_WORK_RE = re.compile(r"status=llm_error turns=0 tools=0 edits=0")


def scan(window_s, limit_bytes):
    now = time.time()
    attempts = 0
    failures = 0
    successes = 0
    no_work = 0
    agents = 0
    bad_agents = 0
    providers = {}

    for path in glob.glob("/tmp/*_manager.log"):
        try:
            if now - os.path.getmtime(path) > window_s:
                continue
            with open(path, errors="ignore") as fh:
                fh.seek(0, os.SEEK_END)
                size = os.fstat(fh.fileno()).st_size
                fh.seek(max(0, size - limit_bytes))
                tail = fh.read()
        except OSError:
            continue

        agents += 1
        f = len(FAIL_RE.findall(tail))
        s = len(OK_RE.findall(tail))
        nw = len(NO_WORK_RE.findall(tail))
        failures += f
        successes += s
        no_work += nw
        attempts += f + s
        if f:
            bad_agents += 1
        for m in re.finditer(r"Provider (\w+) failed: .*?(HTTP (\d{3})|aborted)", tail):
            key = "%s/%s" % (m.group(1), m.group(3) or "aborted")
            providers[key] = providers.get(key, 0) + 1

    return {
        "agents": agents,
        "bad_agents": bad_agents,
        "attempts": attempts,
        "failures": failures,
        "successes": successes,
        "no_work": no_work,
        "providers": providers,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW_S,
                    help="seconds of log history to consider")
    ap.add_argument("--min-rate", type=float, default=DEFAULT_MIN_RATE,
                    help="success rate below this is a finding (percent)")
    ap.add_argument("--limit-bytes", type=int, default=25000,
                    help="bytes of log tail read per agent")
    args = ap.parse_args()

    m = scan(args.window, args.limit_bytes)

    print("  window                    : %ds" % args.window)
    print("  agents with recent logs   : %d" % m["agents"])
    print("  agents with total failure : %d" % m["bad_agents"])
    print("  LLM attempts measured     : %d" % m["attempts"])
    print("  failures                  : %d" % m["failures"])
    print("  successes                 : %d" % m["successes"])
    print("  turns finished with no work: %d" % m["no_work"])
    rate = (m["successes"] / m["attempts"] * 100.0) if m["attempts"] else 0.0
    print("  success rate              : %.0f%% (floor %.0f%%)" % (rate, args.min_rate))
    if m["providers"]:
        print("  provider faults           : %s" % ", ".join(
            "%s=%d" % (k, v) for k, v in sorted(m["providers"].items(), key=lambda x: -x[1])))
    print()

    if m["attempts"] == 0:
        print("  UNVERIFIABLE  no LLM attempts in the window, nothing to judge.")
        return 2

    if rate < args.min_rate:
        print("  FAIL  the fleet is not completing LLM work at a usable rate.")
        print("        %.0f%% of %d attempts succeeded, and %d turns ended with"
              % (rate, m["attempts"], m["no_work"]))
        print("        turns=0 tools=0 edits=0, so no work was produced on those.")
        print("        This is measured from executor outcomes, not request volume.")
        return 1

    print("  OK  the fleet completes LLM work at %.0f%% of attempts." % rate)
    return 0


if __name__ == "__main__":
    sys.exit(main())
