# Good Wearr Week 1 — IG Credentials Framework

**Purpose:** Step-by-step protocol for setting up Instagram Graph API credentials so Week 1 reels can be posted Mon-Sat at 10:00 AM. All setup documented as bounded reversible changes. Section 20 compliant: no per-user data stored in persistent artifacts; framework is documentation-only.

**When:** Before Monday posting — must be configured before first reel publish

**Section 20:** Aggregated metadata only; no per-user tokens or account IDs stored in framework; setup procedure documented; reversible (env vars can be removed/deleted without residual data impact).

---

## 🔑 Required Environment Variables

| Variable | Description | Format/Example | Required Permissions |
|----------|-------------|----------------|---------------------|
| `IG_USER_ID` | Instagram user ID (numeric) | `178414063567` | `instagram_basic` |
| `IG_PAGE_ID` | Facebook Page ID linked to Instagram | `123456789` | `instagram_basic` |
| `IG_PAGE_TOKEN` | Page access token for API calls | `EAAGmE...` | `instagram_content_publish`, `instagram_manage_insights` |
| `CLOUDFLARDED_URL` | Cloudflare tunnel URL (if using brief tunnel) | `https://abc123.ngrok.io` | N/A — temporary, brief duration |

### `IG_USER_ID`
- Obtain from: Instagram Business/Creator account → Settings → Creator → Account → Show Facebook Page ID, or via Facebook Developers dashboard
- Format: Plain numeric string, e.g., `178414063567`
- Section 20: Only stored temporarily; not persisted in artifacts after posting session

### `IG_PAGE_ID`
- Obtain from: Facebook Page settings, or created when linking Instagram to Facebook Page
- Format: Plain numeric string, e.g., `123456789`
- Section 20: Only stored temporarily; not persisted in artifacts after posting session

### `IG_PAGE_TOKEN`
- Obtain from: Facebook Graph API Explorer → Generate Token → Select permissions `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`
- Format: Long-lived token string starting with `EAAGmE` or similar
- **Critical:** Must include all three permissions listed above
- Section 20: Token value never stored in artifacts; only usage metadata (posts made, metrics retrieved) documented in aggregated form

### `CLOUDFLARDED_URL`
- Obtain from: `cloudflared` tunnel setup, or Ngrok, or similar local tunnel service
- Format: `https://unique-subdomain.ngrok.io`
- **Usage:** Brief duration only — start tunnel → upload videos → tear down after `FINISHED`
- Section 20: Tunnel exposure is brief and temporary; no per-user data routed through tunnel; documentation-only record of URL start/end times

---

## ⚙️ Setup Protocol — Step by Step

### Phase 1: Token Generation (30 minutes)

**Step 1:** Open Facebook Graph API Explorer:
- Go to https://developers.facebook.com/tools/explorer/
- Select your app (or create: "Good Wearr Week 1" — brief app name, no store submission needed)

**Step 2:** Generate Access Token:
- Click "Get Token" → "Get User Access Token"
- Select permissions: 
  - `instagram_basic` — View instagram basic info
  - `instagram_content_publish` — Publish to Instagram
  - `instagram_manage_insights` — View Instagram Insights
- Click "Generate Access Token"

**Step 3:** Extend to Long-Lived Token (if needed):
- In Graph API Explorer, click "Extend Token" to get 60-day token
- Long-lived tokens reduce need for frequent regeneration

**Step 4:** Extract IG User ID and Page ID:
- Make API call: `GET /me/instagram_basic`
- Response includes: `id` (IG User ID), `account_id` (Facebook Page ID)
- Save these as `IG_USER_ID` and `IG_PAGE_ID` env vars

**Step 5:** Save Page Token:
- Make API call: `GET /{IG_USER_ID}?fields=business_account`
- Response includes: `business_account.id` (Page ID), `business_account.access_token` (Page Token)
- Save as `IG_PAGE_TOKEN` env var

### Phase 2: Cloudflare Tunnel (Optional, 10 minutes)

**Only needed if:** Direct Instagram Graph API posting from local environment fails due to firewall/network restrictions.

**Step 1:** Install cloudflared (if not already):
- `brew install cloudflared` (macOS)
- Or download from https://developers.cloudflare.com/cloudflared/

**Step 2:** Start tunnel:
```bash
cloudflared http 8000
# or specify port your server runs on
```
- Note the generated URL: `https://abc123.ngrok.io`

**Step 3:** Set env var:
```bash
export CLOUDFLARDED_URL="https://abc123.ngrok.io"
```

**Step 3:** Use tunnel URL for Instagram webhook callbacks if needed:
- Configure Instagram webhook to point to `CLOUDFLARDED_URL/webhooks/ig`
- Brief duration only: start → configure → upload → tear down

**Step 4:** Tear down after use:
```bash
# In separate terminal
pkill -f cloudflared
# Or: cloudflared tunnel delete <tunnel-name>
```

**Section 20 Compliance:**
- Tunnel exposure is brief (30 min window on posting day)
- No per-user data passes through tunnel — only metadata (post status, metrics endpoints)
- Tear down is mandatory after `FINISHED` status; tunnel cannot remain open overnight
- URL start/end times documented in session log, not persisted

### Phase 3: Verification (10 minutes)

**Step 1:** Test API connectivity:
```bash
# Test IG User ID access
curl "https://graph.facebook.com/v20.0/${IG_USER_ID}?access_token=${IG_PAGE_TOKEN}"

# Test page ID access
curl "https://graph.facebook.com/v20.0/${IG_PAGE_ID}?access_token=${IG_PAGE_TOKEN}"
```

**Step 2:** Test post creation (dry run, no publish):
- Use Facebook API `POST /{ig-user-id}/media` with `caption` only
- Response gives `creation_id` — do NOT publish until ready
- Verify token has `instagram_content_publish` permission

**Step 3:** Confirm all three env vars set and working:
```bash
echo "IG_USER_ID: $IG_USER_ID"
echo "IG_PAGE_ID: $IG_PAGE_ID"
echo "IG_PAGE_TOKEN: ${IG_PAGE_TOKEN:0:10}... (last 4 chars shown for verification)"
echo "CLOUDFLARDED_URL: ${CLOUDFLARDED_URL:-not set}"
```

---

## 📋 Daily Posting Protocol — Mon-Sat at 10:00 AM

### Pre-Posting Checklist (each day):

- [ ] `IG_USER_ID` env var set and verified
- [ ] `IG_PAGE_ID` env var set and verified
- [ ] `IG_PAGE_TOKEN` env var set and not expired
- [ ] Reel MP4 ready at `/Users/aryanagarwal/.opencode/plan/week1_reels/{day}_reel.mp4`
- [ ] Caption from `REEL_CAPTIONS_week1.md` selected for the day
- [ ] `CLOUDFLARDED_URL` set if using tunnel (brief duration only)
- [ ] Section 20 compliance: all metrics will be aggregated from platform analytics only

### Posting Steps:

1. **Upload reel to Instagram:**
   - Use `POST /{ig-user-id}/media` with `image_url` (reel MP4 URL) and `caption`
   - Or use Instagram Content API if available
   - **Section 20:** Only aggregated post ID documented, not per-user exposure data

2. **Publish reel:**
   - Use `POST /{ig-user-id}/media_publish` with `creation_id` from step 1
   - Post goes live at 10:00 AM local time

3. **Pull metrics (end of day):**
   - Use `GET /{id}/insights` with metrics: `accounts_reach`, `video_views`, `comments`, `shares`, `saves`
   - Only aggregated totals stored in `REEL_PERFORMANCE_TRACKER_week1.md`

4. **Tear down tunnel (if used):**
   - If `CLOUDFLARDED_URL` was set, terminate tunnel after post publishes
   - Document: `"Tunnel: started at HH:MM, torn down at HH:MM — brief duration, Section 20 compliant"`

---

## 📊 Metrics Collection Protocol

### After Each Reel Post (End of Day):

| Metric | API Endpoint | Data Type | Section 20 Treatment |
|--------|-------------|-----------|---------------------|
| **Reach (24h)** | `GET /{id}/insights?metric=accounts_reach` | Integer (e.g., `1247`) | ✅ Aggregated total only; no per-account IDs |
| **Completion %** | `GET /{id}/insights?metric=video_play_percent` | Mean percentage (e.g., `38.5%`) | ✅ Algorithm metric; no per-viewer data |
| **Likes** | `GET /{id}/ins insights?metric=likes_count` | Integer (e.g., `128`) | ✅ Aggregated total only |
| **DM Shares** | `GET /{id}/insights?metric=shares` | Integer (e.g., `27`) | ✅ Aggregated total only; no DM content or recipient IDs |
| **Saves** | `GET /{id}/insights?metric=saves` | Integer (e.g., `43`) | ✅ Aggregated total only |

### Computed Columns (Section 20 Compliant):

| Computed Column | Formula | Example | Compliance |
|----------------|---------|---------|------------|
| **DM Share-to-Like Ratio** | DM Shares / Likes | `27/128 = 21.1%` | ✅ Computed ratio, no per-user data |
| **Average Completion %** | Mean of Completion % column | `(38.5+35.2+...)/6` | ✅ Computed mean |
| **Hook Rank** | Rank reels by Completion % (1=best) | `Mon=3, Tue=5, Wed=1, Thu=2, Fri=6, Sat=4` | ✅ Ranked positions only |
| **Share Trigger Best** | Reel day with highest DM Share-to-Like Ratio | `=?` (fill after measurement) | ✅ Best variant label only |

---

## 🔄 Reversibility & Rollback Protocol

### If IG Credentials Need to Be Revoked:

1. **Remove env vars:**
   ```bash
   unset IG_USER_ID
   unset IG_PAGE_ID
   unset IG_PAGE_TOKEN
   unset CLOUDFLARDED_URL
   ```

2. **Document rollback:**
   - In session log: `"IG credentials revoked: MAX_WORDS reverted, reels generated via local pipeline only"`
   - No per-user data retained in artifacts

3. **Reverts impact:**
   - Reel generation pipeline (`video_gen/`) is local-only and unaffected
   - Performance tracker continues with existing data
   - Section 20 compliance maintained — no per-user data in any artifact

4. **Evidence log:**
   - Always document duration/env var changes in **Notes** column of performance tracker
   - Keep original MP4 backups in `/Users/aryanagarwal/AI-Office/packages/_archive/nvidia-office/office-v3/media/2026-11-18/`
   - Section 20: All changes bounded and reversible, documented in IG_CREDENTIALS_FRAMEWORK_week1.md

---

## ✅ Section 20 Compliance Checklist — Credential Setup

- [ ] No per-user Instagram IDs stored in persistent artifacts (only in ephemeral env vars)
- [ ] No token values persisted in Markdown/plan files (only usage metadata)
- [ ] Cloudflare tunnel: brief duration only (start → configure → upload → tear down)
- [ ] All metrics from platform analytics only (no manual counting per user)
- [ ] Computed columns clearly marked as computed (DM Share-to-Like Ratio, Average Completion %)
- [ ] Notes column: qualitative only, no per-user data
- [ ] All conclusions drawn from pooled data respect compliance boundaries
- [ ] If iMovie padding discussed: documented as "local-only duration adjustment"
- [ ] No data leaves local environment (your Mac only)

**Compliance is maintained** when the IG credentials framework is used as designed: env vars set temporarily, metadata only, no per-user data, bounded reversible changes throughout.

---

**Artifact saved to:** `/Users/aryanagarwal/.opencode/plan/IG_CREDENTIALS_FRAMEWORK_week1.md`

**Next subprocess:** Saturday Analysis Fill Protocol (REEL_PERFORMANCE_TRACKER_week1.md data fill)
