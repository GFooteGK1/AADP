# Alpha Analysis Downstream Processing — Roadmap

## Status as of 2026-02-27

### What Is Working (Confirmed)

- **Google Drive folder creation** — Folder named `{brand}, {city}, {street_address}` is created correctly under the fixed parent folder
- **Standard subfolders** — All 7 subfolders are created inside each new site folder
- **LOI attachment routing** — Email attachments are uploaded to `M1 - Acquire Property`
- **Wrike "Google Folder" field** — Updated with the Drive folder link after creation (`google_folder` custom field `IEAGN6I6JUAJK2MQ`)
- **Wrike Assignee (`responsibleIds`)** — Now set to the same contact(s) as P1 Accountable

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

## Completed Items (this session)

- [x] Added `responsibleIds` support to `update_site_record()` — the Wrike Assignee field is now set to the same person as P1 Accountable
- [x] Updated subfolder names to milestone-based names (M1–M6 + Working)
- [x] Updated LOI attachment upload target to `M1 - Acquire Property`

---

## Critical Files

| File | Purpose |
|---|---|
| `src/alpha_analysis_downstream_processing_mcp/server.py` | `SITE_DRIVE_SUBFOLDERS` constant, P1 assignment call, `responsible_ids` passthrough |
| `src/alpha_analysis_downstream_processing_mcp/wrike.py` | `assign_p1_accountable_for_new_site()`, `update_site_record()`, `update_site_record_with_location_data()` |
| `prompt.md` | Agent behavior — update if workflow changes |
| `FRAMEWORK.md` | Architecture reference doc |
