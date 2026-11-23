# Good Wearr Week 1 — Week 1 Reel Performance Tracker

**Purpose:** Track algorithm-optimized metrics across 6 reel posting days (Mon-Sat)
**Usage:** Fill in end-of-day each reel posting day; analyze Saturday evening
**Section 20:** Aggregated metrics only; no per-user data tracked

---

## Meta-Tracking (Do Not Delete)

| Artifact | File Path | Last Updated | Status |
|----------|-----------|--------------|--------|
| Performance Tracker | `REEL_PERFORMANCE_TRACKER_week1.md` | `2026-11-19` | Reels generated; durations 12-18s ✓; awaiting IG posting + metrics fill |
| A/B Test Tracking | `AB_TEST_WEEK1_tracking.md` | `{{date}}` | Populate Hook Effective / Share Trigger Effective |
| Saturday Analysis | `REEL_SATURDAY_ANALYSIS_week1.md` | `2026-11-19` | Framework ready; data fill after 6-day Mon-Sat posting sequence. Reels generated with durations 12-18s. |
| Week 2 Plan | `WEEK2_EXECUTION_PLAN.md` | `{{date}}` | Create after Saturday analysis |
| iMovie Workflow | `REEL_IMOVIE_WORKFLOW_week1.md` | `{{date}}` | Use if duration optimization needed |

---

## Column Definitions

| Column | Description | Example | Section 20 Note |
|--------|-------------|---------|-----------------|
| **Reel** | Script filename and day | `monday_activation.md` (Mon) | ✅ Filename only, no per-user data |
| **Day** | Posting day shorthand | Mon, Tue, Wed, Thu, Fri, Sat | ✅ Day label only |
| **Post Time** | Time posted (local) | `10:00 AM` | ✅ Time only, no timezone per-user data |
| **Reach (24h)** | "Accounts reached" from platform analytics | `1,247` | ✅ Aggregated only, no individual account IDs |
| **Completion %** | Total play time past 3s hook / Avg watch time — % past 3s hook | `38.5%` | ✅ Algorithm metric, no per-viewer data |
| **Likes** | Raw like count | `128` | ✅ Aggregated total only |
| **DM Shares** | Direct mentions/shares in mentions/DM inbox | `27` | ✅ Aggregated total only |
| **Saves** | "Post saves" from platform analytics | `43` | ✅ Aggregated total only |
| **Hook Effective (Y/N)** | Did viewers stay past 3-second hook? | `Y`/`N` + Notes | ✅ Binary algorithm assessment |
| **Share Trigger Effective (Y/N)** | Did explicit share ask generate disproportionate engagement? | `Y`/`N` + Notes | ✅ Binary engagement assessment |
| **DM Share-to-Like Ratio** | DM Shares / Likes (computed column) | `21.1%` | ✅ Computed aggregated ratio |
| **Average Completion %** | Mean across all reels posted so far | `36.2%` | ✅ Computed mean, no per-viewer data |
| **Hook Rank** | Rank reels by Completion % (1=best) | `Thu=1, Mon=2, Wed=3,` | ✅ Ranked positions only |
| **Share Trigger Best** | Which reel's share ask performed best | `Thursday (Owner UI pain point)` | ✅ Best variant label only |
| **Notes** | Observations while fresh; per-reel qualitative notes | `"Hook felt strong, good retention on first 3s"` | ✅ Free text, no per-user data |

---

## Daily Fill Protocol — End of Each Reel Posting Day

### Monday
1. Fill **Reach (24h)**: From platform analytics "Accounts reached" — post time: `10:00 AM`
2. Fill **Completion %**: % past 3-second hook — target: `≥ 35%`
3. Fill **Likes**: Raw like count
4. Fill **DM Shares**: Direct mentions/shares in mentions/DM inbox
5. Fill **Saves**: "Post saves" from platform analytics
6. Set **Hook Effective (Y/N)**: Y if Completion % ≥ 35%, N if < 35%
7. Set **Share Trigger Effective (Y/N)**: Y if DM Shares / Likes ≥ 15%, N if < 15%
8. Fill **DM Share-to-Like Ratio**: Computed = DM Shares / Likes
9. Fill **Average Completion %**: Mean of all rows filled so far (Mon only = Mon's %)
10. Fill **Hook Rank**: Mon=1 (only reel so far)
11. Fill **Share Trigger Best**: N/A (only one reel)
12. **Notes**: Observations while fresh (`"Hook felt strong, completion good"`)

### Tuesday-Saturday (Repeat)
Same 12 steps above, plus:
- **Average Completion %**: Mean across all rows filled Mon→current day
- **Hook Rank**: Rank all reels Mon→current by Completion % (1=best completion)
- **Share Trigger Best**: Label which reel day's share ask performed best based on DM Share-to-Like Ratio
- **Notes**: Observations while fresh

### Saturday Evening — Post-Fill Analysis
After all 6 rows filled, compute:

| Metric | Formula | Example |
|--------|---------|---------|
| **Total Likes** | Sum of Likes column | `=?` |
| **Total DM Shares** | Sum of DM Shares column | `=?` |
| **Total Saves** | Sum of Saves column | `=?` |
| **DM Share-to-Like Ratio** | Total DM Shares / Total Likes | `=?` (target: ~20%, weighted 3-5× likes) |
| **Average Completion %** | Mean of Completion % column | `=?` (target: ~35%+) |
| **Hook Effectiveness Rank** | Rank reels by Completion % (1=best) | `Mon=#, Tue=#, Wed=#, Thu=#, Fri=#, Sat=#` |
| **Share Trigger Effectiveness** | Compare Notes column for which reel's share ask performed best | `Best variant: Thursday (Owner UI pain point)` |
| **Section 20 Compliance Check** | All data aggregated? No per-user IDs? Yes/No | `✅ Yes` |

**Saturday Evening Summary Template:**
```markdown
## Week 1 Saturday Analysis Summary

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Total Likes** | `=?` | — | — |
| **Total DM Shares** | `=?` | — | — |
| **Total Saves** | `=?` | — | — |
| **DM Share-to-Like Ratio** | `=?` | ~20% (3-5× like weight) | ⚠️/✅ |
| **Average Completion %** | `=?` | ~35%+ | ⚠️/✅ |
| **Hook Effectiveness Rank** | `Mon=#, Tue=#, Wed=#, Thu=#, Fri=#, Sat=#` | — | — |
| **Share Trigger Best** | `Thursday (Owner UI pain point)` | — | — |
| **Section 20 Compliance** | All aggregated, no per-user data | ✅ Compliant | ✅ |
```

---

## Reversibility & Rollback Protocol

### If Metrics Don't Meet Success Criteria:
1. **Change MAX_WORDS in reel.py from 200 → 140**
2. **Re-generate all 6 MP4s via reel.py** (21-28s durations)
3. **Captions remain valid** — metadata describes content, not duration
4. **Section 20 compliance fully maintained** — only duration changed, bounded reversible
5. **Document in Notes:** `"Duration rollback: MAX_WORDS 200→140, re-generated 6 MP4s (21-28s)"`

### If iMovie Padding Applied:
1. **Keep MAX_WORDS at 200** (scripts already extended)
2. **iMovie edits local only** — bounded reversible
3. **Can always re-export original MP4s** from folder backup
4. **Document in Notes:** `"iMovie padding applied: +xxs per reel to reach 64-72s"`

### Rollback Evidence Log:
- Always document duration changes in **Notes** column
- Keep original MP4 backups in `/Users/aryanagarwal/AI-Office/packages/_archive/nvidia-office/office-v3/media/2026-11-18/`
- Section 20: All changes bounded and reversible, documented in tracker

---

## Section 20 Compliance Checklist — Per Fill Session

- [ ] All metrics from platform analytics only (no manual counting per user)
- [ ] No per-user A/B assignment data tracked
- [ ] No individual account performance shared in Notes
- [ ] Aggregated totals only (sums, means, ratios, ranks)
- [ ] Computed columns (DM Share-to-Like Ratio, Average Completion %, Hook Rank) clearly marked as computed
- [ ] Notes column: qualitative only, no per-user data
- [ ] All conclusions drawn from pooled data respect compliance boundaries
- [ ] If iMovie padding applied: documented as "local-only duration adjustment"

**Compliance is maintained** when the tracker is used as designed: aggregated metrics, computed columns only, no per-user data in Notes.
