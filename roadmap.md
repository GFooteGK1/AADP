# Alpha Analysis Downstream Processing — Roadmap

## Status as of 2026-03-03

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

---

## Critical Files

| File | Purpose |
|---|---|
| `src/alpha_analysis_downstream_processing_mcp/server.py` | `SITE_DRIVE_SUBFOLDERS` constant, P1 assignment call, `responsible_ids` passthrough |
| `src/alpha_analysis_downstream_processing_mcp/wrike.py` | `assign_p1_accountable_for_new_site()`, `update_site_record()`, `update_site_record_with_location_data()` |
| `prompt.md` | Agent behavior — update if workflow changes |
| `FRAMEWORK.md` | Architecture reference doc |
