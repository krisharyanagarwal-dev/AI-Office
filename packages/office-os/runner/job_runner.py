#!/usr/bin/env python3
"""
job_runner - executes one job spec against a local model, on the Mac mini.

RUNS ON THE MINI under /usr/bin/python3 3.9.6: standard library only, no f-strings,
no 3.10+ syntax, no third-party packages. It never raises: a failure is a record.

    base64 < jobs/<id>.json | ssh a@macmini "/usr/bin/python3 - $(cat)" < runner/job_runner.py

The spec arrives base64-encoded in argv[1] so nothing has to survive two layers of
shell quoting. Evidence is read locally from the mini, the model is called on the
local shim, and the answer is accepted only if it passes, in order:

  1. valid JSON
  2. every schema field present, right type, no invented keys
  3. the acceptance rules - crucially require_evidence, which checks the EVIDENCE
     rather than the answer, so a verdict can only be claimed when the facts
     actually support it. That is the anti-hallucination gate.

Records go to records.jsonl, rejects to failures.jsonl. Both are the compiler's input.
"""
import base64
import json
import os
import sys
import time
import urllib.request

HOME = os.path.expanduser("~")
OUT_DIR = os.path.join(HOME, "office-jobs")
OLLAMA = "http://localhost:11434/api/generate"


def log(msg):
    sys.stderr.write("[runner] " + msg + "\n")


# ---------- evidence ----------
def read_evidence(spec):
    """Read the declared files. A missing file is a fact, not a crash."""
    facts = {}
    missing = []
    for rel in spec.get("evidence_files", []):
        path = os.path.join(HOME, rel)
        try:
            doc = json.load(open(path))
        except Exception as e:
            missing.append(rel + ": " + type(e).__name__)
            continue
        for key, value in doc.items():
            if key in facts and facts[key] != value:
                continue  # first file wins; never silently merge conflicting facts
            facts[key] = value
    wanted = spec.get("evidence_fields")
    if wanted:
        facts = dict((k, v) for k, v in facts.items() if k in wanted)
    return facts, missing



# ---------- derived facts ----------
def iso_age_min(value):
    """Minutes since an ISO-8601 stamp. Written for 3.9: fromisoformat there does
    not accept a trailing Z, so the parse is explicit."""
    import calendar
    text = str(value or "").strip().replace("Z", "")
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = time.strptime(text.split("+")[0], fmt)
        except ValueError:
            continue
        return round((time.time() - calendar.timegm(parsed)) / 60.0, 1)
    return None


def derive_facts(facts, rules):
    """Compute what the model must NOT be asked to work out.

    A language model is unreliable at arithmetic and worse at dates, so ages,
    counts and totals are produced here, deterministically, and handed to it as
    plain facts. The model's only job is to classify what it is given.
    """
    for name, rule in (rules or {}).items():
        try:
            if "age_min_of" in rule:
                facts[name] = iso_age_min(facts.get(rule["age_min_of"]))
            elif "count_of" in rule:
                value = facts.get(rule["count_of"])
                facts[name] = len(value) if isinstance(value, (list, dict)) else None
            elif "count_where_false" in rule:
                field, key = rule["count_where_false"]
                items = facts.get(field)
                if isinstance(items, list):
                    facts[name] = sum(1 for i in items
                                      if isinstance(i, dict) and not i.get(key))
                else:
                    facts[name] = None
            elif "is_empty" in rule:
                value = facts.get(rule["is_empty"])
                facts[name] = (len(value) == 0) if isinstance(value, (list, dict)) else None
        except Exception as e:
            facts[name] = None
            log("derive " + name + " failed: " + type(e).__name__ + ": " + str(e)[:80])
    return facts

# ---------- schema ----------
def check_type(value, declared):
    if isinstance(declared, list):
        return value in declared, "not one of " + repr(declared)
    name = declared
    nullable = name.endswith("|null")
    if nullable:
        name = name[: -len("|null")]
    if value is None:
        return nullable, "null not allowed"
    if name == "string":
        return isinstance(value, str), "not a string"
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool), "not an integer"
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool), "not a number"
    if name == "boolean":
        return isinstance(value, bool), "not a boolean"
    return False, "unknown declared type " + repr(declared)


def validate_schema(answer, schema):
    problems = []
    if not isinstance(answer, dict):
        return ["answer is not a JSON object"]
    for field, declared in schema.items():
        if field not in answer:
            problems.append("missing field " + field)
            continue
        ok, why = check_type(answer[field], declared)
        if not ok:
            problems.append("field " + field + ": " + why + " (got " + repr(answer[field])[:60] + ")")
    for field in answer:
        if field not in schema:
            problems.append("invented field " + field)
    return problems


# ---------- acceptance ----------
def as_text(value):
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)



def check_clause(clause, evidence):
    """One require_evidence clause: field==value, or a numeric <=, <, >=, >.

    An absent field never satisfies a clause. Silence is not consent: a verdict
    cannot rest on a fact the evidence does not contain.
    """
    for op in ("<=", ">=", "==", "<", ">"):
        if op not in clause:
            continue
        key, _, expected = clause.partition(op)
        key, expected = key.strip(), expected.strip()
        actual = evidence.get(key, "<<absent>>")
        if actual == "<<absent>>":
            return False, "evidence has no " + key + " (needs " + op + " " + expected + ")"
        if op == "==":
            ok = as_text(actual).lower() == expected.lower()
        else:
            try:
                left, right = float(actual), float(expected)
            except (TypeError, ValueError):
                return False, key + "=" + as_text(actual) + " is not numeric, needs " + op + " " + expected
            ok = {"<=": left <= right, ">=": left >= right,
                  "<": left < right, ">": left > right}[op]
        if ok:
            return True, ""
        return False, "evidence has " + key + "=" + as_text(actual) + ", needs " + op + " " + expected
    return True, ""   # a clause with no operator constrains nothing


def check_acceptance(answer, evidence, rules):
    """require_evidence is the important one: it tests the FACTS, not the answer."""
    problems = []
    for rule in rules or []:
        when = rule.get("when") or {}
        if not all(answer.get(k) == v for k, v in when.items()):
            continue
        label = "; ".join(k + "=" + as_text(v) for k, v in when.items())
        for clause in rule.get("require_evidence", []):
            ok, detail = check_clause(clause, evidence)
            if not ok:
                problems.append("claimed " + label + " but " + detail +
                                " (" + rule.get("why", "") + ")")
        for field in rule.get("require_output_not_null", []):
            if answer.get(field) is None:
                problems.append(
                    "claimed " + label + " but " + field + " is null (" + rule.get("why", "") + ")")
        for field, ev_key in (rule.get("require_output_matches_evidence") or {}).items():
            expected = evidence.get(ev_key, "<<absent>>")
            if expected == "<<absent>>":
                problems.append("cannot check " + field + ": evidence has no " + ev_key)
                continue
            actual = answer.get(field)
            same = as_text(actual).lower() == as_text(expected).lower()
            if not same:
                try:
                    same = float(actual) == float(expected)
                except (TypeError, ValueError):
                    same = False
            if not same:
                problems.append(
                    "reported " + field + "=" + as_text(actual) + " but the evidence says " +
                    ev_key + "=" + as_text(expected) + " (" + rule.get("why", "") + ")")
    return problems


# ---------- model ----------
def ask_model(spec, prompt):
    body = json.dumps({
        "model": spec["model"],
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=spec.get("timeout_sec", 180)) as r:
        payload = json.loads(r.read().decode("utf-8", "replace"))
    return payload.get("response", ""), round(time.time() - started, 1)


# ---------- output ----------
def append(path, row):
    try:
        if not os.path.isdir(OUT_DIR):
            os.makedirs(OUT_DIR)
        fh = open(path, "a")
        fh.write(json.dumps(row) + "\n")
        fh.close()
    except Exception as e:
        log("could not write " + path + ": " + str(e))


def main(argv):
    if not argv:
        log("usage: job_runner.py <base64 job spec>")
        return 2
    spec = json.loads(base64.b64decode(argv[0]).decode("utf-8"))
    job_id = spec["id"]
    records = os.path.join(OUT_DIR, job_id + ".records.jsonl")
    failures = os.path.join(OUT_DIR, job_id + ".failures.jsonl")

    evidence, missing = read_evidence(spec)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    base = {"job": job_id, "model": spec["model"], "ts": stamp}
    if missing:
        base["evidence_missing"] = missing
    if not evidence:
        row = dict(base)
        row.update({"outcome": "NO_EVIDENCE", "reason": "no evidence file could be read"})
        append(failures, row)
        print(json.dumps(row))
        return 1

    evidence = derive_facts(evidence, spec.get("evidence_derive"))
    prompt = spec["prompt"].replace("{evidence}", json.dumps(evidence, indent=2, sort_keys=True))
    attempts = int(spec.get("retries", 2)) + 1
    last = None
    for attempt in range(1, attempts + 1):
        try:
            text, took = ask_model(spec, prompt)
        except Exception as e:
            last = {"stage": "call", "problems": [type(e).__name__ + ": " + str(e)[:160]]}
            log("attempt " + str(attempt) + ": call failed: " + str(e)[:120])
            continue
        try:
            answer = json.loads(text)
        except Exception:
            last = {"stage": "parse", "problems": ["not valid JSON"], "raw": text[:400]}
            log("attempt " + str(attempt) + ": answer was not JSON")
            continue
        problems = validate_schema(answer, spec["output_schema"])
        stage = "schema"
        if not problems:
            problems = check_acceptance(answer, evidence, spec.get("acceptance"))
            stage = "acceptance"
        if problems:
            last = {"stage": stage, "problems": problems, "answer": answer}
            log("attempt " + str(attempt) + ": " + stage + " rejected: " + problems[0][:140])
            continue
        row = dict(base)
        row.update({"outcome": "OK", "attempt": attempt, "took_sec": took, "answer": answer})
        append(records, row)
        print(json.dumps(row))
        return 0

    row = dict(base)
    row.update({"outcome": "REJECTED", "attempts": attempts})
    row.update(last or {})
    append(failures, row)
    print(json.dumps(row))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
