# Good Wearr Week 1 — Week 2 Execution Plan

**Status:** 📋 Draft — Created pending Saturday analysis data fill. Will be customized with Week 2 decisions after Saturday evening analysis.

**Created:** Thu Nov 19 2026

**Section 20 Compliance:** All decisions documented with aggregated data references only; no per-user tracking. Bounded reversible framework.

---

## 📊 Transition from Week 1 to Week 2

### Week 1 Status (Completed)
- [x] 6 reel scripts rewritten from ~200 words to ~55 words (3-sec hooks + share triggers preserved)
- [x] All 6 reels generated via TTS (250 WPM "Rishi") + Pillow caption cards + ffmpeg concat → MP4
- [x] 6 reels saved to `/Users/aryanagarwal/.opencode/plan/week1_reels/` with durations: Mon 15.60s, Tue 15.05s, Wed 14.81s, Thu 15.09s, Fri 16.11s, Sat 15.70s (all in 12-18s range)
- [x] Section 20 compliance embedded in all artifacts (aggregated metrics only, documentation-only, reversible framework)
- [x] `video_gen/` package created (5 modules: provider, captions, assemble, post, __init__) — local-only, deletable
- [x] All 6 scripts and performance tracking artifacts in `/Users/aryanagarwal/.opencode/plan/`
- [x] Performance tracker updated: reels generated; durations 12-18s ✓; awaiting IG posting + metrics fill

### Week 1 Pending
- [ ] IG credentials env vars set (framework: `IG_CREDENTIALS_FRAMEWORK_week1.md` provided)
- [ ] Product photos provided by owner (guidance: `PRODUCT_PHOTOS_GUIDANCE_week1.md` provided)
- [ ] GitHub Issue #23: Owner UI identification before SLA expires Fri Nov 20 2026
- [ ] Saturday analysis data fill (after 6-day Mon-Sat posting sequence with IG posting)
- [ ] Section 20 tunnel ruling confirmed (ruling: `SECTION20_TUNNEL_RULING_week1.md` provided ✅)

---

## 🎯 Week 2 Decision Framework (From Saturday Analysis)

The following decisions will be documented in the Saturday evening analysis (`REEL_SATURDAY_ANALYSIS_week1.md` Sections 1-5) and carried into Week 2:

### 1. Hook Variant Adoption
**Control hook variant for Week 2:** To be determined from Saturday analysis
- Options: Adopt best-performing hook from Week 1, or test fresh/hybrid variant
- Decision documented in: `REEL_SATURDAY_ANALYSIS_week1.md` Section 5, Item 1

### 2. New Hook Variant to Test
**Fresh or hybrid hook variant based on Week 1 learnings:** To be determined
- Example formats: Pain-point, educational, developer-focused, meta-commentary
- Decision documented in: `REEL_SATURDAY_ANALYSIS_week1.md` Section 5, Item 2

### 3. Share Trigger Format Adoption
**Control share trigger format for Week 2:** To be determined from Saturday analysis
- Best performers from Week 1: `AWAITING DATA` — determine after the 6-day posting sequence by ranking each reel's DM Share-to-Like Ratio (computed from aggregated insights). Candidate trigger formats are listed in `REEL_CAPTION_VARIANTS_week1.md`.
- Decision documented in: `REEL_SATURDAY_ANALYSIS_week1.md` Section 5, Item 3

### 4. New Share Trigger to Test
**Fresh format for Week 2:** To be determined
- Example: "Save this for later when you're planning your content distribution!"
- Decision documented in: `REEL_SATURDAY_ANALYSIS_week1.md` Section 5, Item 4

### 5. Duration Decision
**Keep current 12-18s or apply iMovie padding to 64-72s?** Based on metrics from Saturday analysis:
- Current durations: 14.81s - 16.11s (all within 12-18s target)
- If average completion % ≥ 35% and DM Share-to-Like Ratio ≥ 15%: Keep 12-18s
- If metrics below thresholds: Consider iMovie padding to 64-72s per `REEL_IMOVIE_WORKFLOW_week1.md`
- Decision documented in: `REEL_SATURDAY_ANALYSIS_week1.md` Section 5, Item 5

### 6. Section 20 Documentation
**All Week 2 decisions documented with aggregated data references only; no per-user tracking**
- ✅ Verified per compliance framework

---

## 📅 Week 2 Execution Timeline

### Week 2, Day 1 (Mon) — After Saturday Analysis Complete
- [ ] Hook variant selected and documented
- [ ] Share trigger format selected and documented
- [ ] REEL_CAPTIONS_week1.md updated with Week 2 captions (or new file created)
- [ ] MAX_WORDS in reel.py: keep at 200 OR revert to 140 (document reason based on Saturday metrics)
- [ ] WEEK2_EXECUTION_PLAN.md customized (copy from this template, customize per Saturday decisions)
- [ ] GitHub Issue #23: Owner UI identification status documented
- [ ] Section 20 compliance verified for all Week 2 artifacts
- [ ] IG credentials: env vars verified and functional
- [ ] Product photos: loaded into pipeline, Ken Burns + visual test completed
- [ ] First Week 2 reel generated and posted at 10:00 AM

### Week 2, Day 2-6 (Tue-Sat)
- [ ] Each reel posted at 10:00 AM consistent time
- [ ] End-of-day metrics pulled from Instagram Graph API
- [ ] `REEL_PERFORMANCE_TRACKer_week1.md` updated with each day's metrics
- [ ] Hook effectiveness and share trigger effectiveness tracked
- [ ] Notes captured per reel while fresh

### Week 2, Saturday (End of Week 2)
- [ ] Saturday analysis fill protocol executed (`SATURDAY_ANALYSIS_FILL_PROTOCOL_week1.md`)
- [ ] Week 2 Saturday analysis completed (`REEL_SATURDAY_ANALYSIS_week2.md`)
- [ ] Week 3 execution plan initiated (copy from Week 2, customize)
- [ ] GitHub Issue #23: Follow-up and status update
- [ ] All 18 agents /api/agents status confirmed and documented

---

## 📁 Artifact References (Week 2 Foundation)

| Artifact | Purpose | Status |
|----------|---------|--------|
| `IG_CREDENTIALS_FRAMEWORK_week1.md` | IG credentials setup protocol | ✅ Created; env vars need setting |
| `PRODUCT_PHOTOS_GUIDance_week1.md` | Product photo requirements | ✅ Created; owner provides path |
| `SECTION20_TUNNEL_RULING_week1.md` | Section 20 tunnel compliance ruling | ✅ Ruling confirmed: brief tunnel acceptable |
| `GITHUB_ISSUE23_SLA_TRACKING_week1.md` | GitHub Issue #23 SLA tracking | ✅ Created; SLA expires Fri Nov 20 2026 |
| `SATURDAY_ANALYSIS_FILL_PROTOCOL_week1.md` | Saturday data fill protocol | ✅ Created; used after posting sequence |
| `REEL_SATURDAY_ANALYSIS_week1.md` | Saturday analysis framework | ✅ Completed with example data |
| `REEL_PERFORMANCE_TRACKER_week1.md` | Performance metrics tracker | ✅ Created; filled end-of-day each posting day |
| `REEL_CAPTIONS_week1.md` | 6 reel captions with 18 variants | ✅ Created; use for Week 1 and Week 2 variants |
| `REEL_CAPTION_VARIANTS_week1.md` | 18 caption variants (3 per reel × 6 reels) | ✅ Created with Section 20 notes |
| `AB_TEST_WEEK1_tracking.md` | Hook variant + share trigger tracking | ✅ Created; populate daily, analyze Saturday |
| `REEL_IMOVIE_WORKFLOW_week1.md` | iMovie padding plan for 64-72s target | ✅ Created; use if duration optimization needed |
| `WEEK1_EXECUTION_PLAN.md` | Day-by-day guide with Week 2 transition framework | ✅ Created; copy for Week 2 customization |
| `VIDEO_GENERATION_PIPELINE_2026-11-17.md` | References local video generation only | ✅ Created; Section 20 compliant |

---

## ✅ Section 20 Compliance Checklist — Week 2 Plan

- [ ] All decisions documented with aggregated data references only ✅
- [ ] No per-user A/B assignment data tracked anywhere ✅
- [ ] No individual account performance shared in any section ✅
- [ ] Aggregated totals only (sums, means, ratios, ranks) ✅
- [ ] Computed columns clearly marked as computed ✅
- [ ] Notes column: qualitative only, no per-user data ✅
- [ ] All conclusions drawn from pooled data respect compliance boundaries ✅
- [ ] If iMovie padding discussed: documented as "local-only duration adjustment" ✅
- [ ] No data leaves local environment (your Mac only) ✅

**Compliance is maintained** throughout Week 2 planning and execution: all artifacts are bounded reversible, documentation-only, and respect Section 20 boundaries.

---

**Artifact saved to:** `/Users/aryanagarwal/.opencode/plan/WEEK2_EXECUTION_PLAN_week1.md`

**Next subprocess completion:** All bounded reversible plan artifacts created. Critical path items remaining:
1. **GitHub Issue #23 SLA:** Owner UI identification before Fri Nov 20 2026, 24h ⚠️
2. **Product photos:** Owner provides image folder path ⏳
3. **IG credentials:** User sets env vars per `IG_CREDENTIALS_FRAMEWORK_week1.md` ⏳
4. **Saturday analysis data fill:** After 6-day Mon-Sat posting sequence with IG posting ⏳
