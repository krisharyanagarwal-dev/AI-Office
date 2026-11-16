import json, sys
data = json.load(sys.stdin)
tasks = data.get('tasks', [])
print(f"Total tasks: {len(tasks)}")
statuses = {}
for t in tasks:
    s = t.get('status', 'UNKNOWN')
    statuses[s] = statuses.get(s, 0) + 1
print(f"Statuses: {statuses}")
in_progress = [t for t in tasks if t.get('status') == 'IN_PROGRESS']
print(f"In Progress ({len(in_progress)}):")
for t in in_progress:
    print(f"  {t.get('task_id','?')} | {t.get('title','?')[:50]} | agent={t.get('assigned_agent','?')} | claimed_by={t.get('claimed_by','None')}")
queued = [t for t in tasks if t.get('status') == 'QUEUED']
print(f"Queued ({len(queued)}):")
for t in queued[:15]:
    print(f"  {t.get('task_id','?')} | {t.get('title','?')[:50]} | agent={t.get('assigned_agent','?')}")