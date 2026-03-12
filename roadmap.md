# Alpha Analysis Downstream Processing — Roadmap

## Status as of 2026-03-12

### What Is Working (Confirmed)

- **Google Drive folder creation** — Folder named `{brand}, {city}, {street_address}` is created correctly under the fixed parent folder
- **Standard subfolders** — All 7 milestone-based subfolders (M1–M6 + Working) are created inside each new site folder
- **LOI attachment routing** — Email attachments are uploaded to `M1 - Acquire Property`
- **Wrike "Google Folder" field** — Updated with the Drive folder link after creation (`google_folder` custom field `IEAGN6I6JUAJK2MQ`)
- **Wrike Assignee (`responsibleIds`)** — Set to the same contact(s) as P1 Accountable
- **P1 Accountable custom field** — Auto-assigned based on state and workload
- **No-LOI site support** — Full downstream flow (Wrike update, notification, Drive folder, presentation) runs for every "New Site" email, even when no LOI is provided

---

## Open Issues

### 1. P1 Accountable Assignment — Needs Real-World Verification

The auto-assignment logic exists (`assign_p1_accountable_for_new_site()` in `wrike.py`) and is wired into `server.py`. The `responsibleIds` (Assignee) field is now also set to the same person.

**Rules as coded:**
- **Rule 1:** If a P1 Accountable already works in the target state → assign the one with fewest total sites
- **Rule 2:** If new state → find geographically nearest state (haversine distance on state centroids) → assign contact with fewest total sites there
- **Rule 3:** If no P1 Accountable anywhere → return `[]`

**Action needed:** Run a test LOI and verify the Wrike task shows correct Assignee and P1 Accountable custom field values.

---

## Completed Items

- [x] Google Drive folder creation under fixed parent folder
- [x] Standard subfolder creation (originally numbered, updated to milestone-based)
- [x] LOI attachment routing to `M1 - Acquire Property`
- [x] Wrike "Google Folder" custom field update
- [x] P1 Accountable auto-assignment logic (`assign_p1_accountable_for_new_site()`)
- [x] Added `responsibleIds` support — Wrike Assignee now set to same person as P1 Accountable
- [x] Updated subfolder names to milestone-based names (M1–M6 + Working)
- [x] Updated `FRAMEWORK.md` to match new subfolder structure
- [x] Deployed to MCP Hive (2026-03-02, commit `a8d1288`)
- [x] No-LOI site support (2026-03-03, commit `7eb25e7`):
  - `loi_signed_date` made optional (default `""`) in `update_wrike_site_record` — skips date validation when empty, passes `None` downstream
  - `create_drive_folder_with_attachments` no longer errors on zero attachments — folder + subfolders always created
  - `prompt.md` updated: mission broadened to all "New Site" emails, added `no_loi` boolean extraction, updated tool descriptions, error handling, expected success rates, and success checklist
- [x] Email body saved to Wrike comments (2026-03-11, commit `ab5f236`):
  - Added `email_body` parameter to `update_wrike_site_record` tool
  - Added `create_comment()` function in `wrike.py` — posts to Wrike `/folders/{id}/comments` API
  - Full new site email body is posted as an HTML comment on the Wrike record (not in the description)
  - Clarified in `prompt.md` that **all** email attachments (not just the LOI PDF) are uploaded to `M1 - Acquire Property`
- [x] CC P1 Accountable on CDS LOI notification email (2026-03-12, commit `abb3b7d`):
  - Added `get_contact_emails()` in `wrike.py` — resolves Wrike contact IDs to email addresses via `/contacts/{ids}` API
  - `send_loi_notification` now extracts P1 Accountable from the Wrike record and CCs their email on the CDS notification
  - `build_loi_email()` and `send_loi_email()` accept `extra_cc_addresses` parameter with deduplication against existing recipients
  - Lookup failure is non-blocking — email still sends if contact resolution fails
- [x] Flight route scoring tools + P1 assignment integration (2026-03-12):
  - Created `flights.py` — SerpAPI Google Flights client, in-memory cache (7-day TTL), scoring engine, team member configs
  - 6 new MCP tools: `check_nonstop_routes`, `score_location`, `assign_locations`, `resolve_school_location`, `list_team_preferences`, `manage_route_cache`
  - Team rules: Andrea (MSY, requires UA/DL), Robbie (SAT, prefers AA, nonstop-first), Devin (PHX, prefers AA, shortest flight)
  - P1 assignment Rule 1.5: when city + `SERPAPI_API_KEY` available, flight scoring ranks contacts before haversine fallback
  - Non-breaking: falls through to existing haversine logic if API key missing or scoring fails
  - 21 school locations mapped to IATA airport codes

---

## Critical Files

| File | Purpose |
|---|---|
| `src/alpha_analysis_downstream_processing_mcp/server.py` | `SITE_DRIVE_SUBFOLDERS` constant, P1 assignment call, `responsible_ids` passthrough |
| `src/alpha_analysis_downstream_processing_mcp/wrike.py` | `assign_p1_accountable_for_new_site()`, `update_site_record()`, `update_site_record_with_location_data()` |
| `prompt.md` | Agent behavior — update if workflow changes |
| `FRAMEWORK.md` | Architecture reference doc |
