# Testing Guide

## Test Mode Detection

A run is considered a **test** when either condition is true:

| Trigger | How detected |
|---|---|
| **Sender email** | The "New Site" email originates from `greg.foote@trilogy.com` |
| **Dry-run flag** | The environment variable `DRY_RUN=true` is set |

When test mode is active, the agent and server must apply the rules below.

---

## Side-Effect Rules

Each external integration falls into one of three categories during a test run:

### Execute normally (real writes allowed)

| Integration | Reason |
|---|---|
| **Gmail read** | Reading emails is non-destructive |
| **Wrike record lookup** | Read-only |
| **Wrike record creation / field updates** | Must verify end-to-end Wrike integration works |
| **Wrike comment creation** | Useful for marking the record as a test (see below) |
| **SerpAPI flight lookups** | OK to run; results are read-only (watch quota in bulk testing) |
| **LOI PDF parsing** | Local computation, no side effects |
| **Flight score calculation** | Local computation, no side effects |

### Simulate (log intent, skip execution)

| Integration | What to log instead |
|---|---|
| **Google Drive folder + subfolder creation** | Log the folder name, parent ID, and subfolder list that *would* be created |
| **Google Drive file upload** | Log the filename, target folder, and byte size |
| **Google Slides presentation copy + update** | Log the template ID, target folder, and replacement values |
| **Wrike P1 Accountable assignment** | Compute the assignment (for verification), log the result, but do **not** write the P1 contact IDs or responsible IDs to the Wrike record |
| **Wrike Assignee (responsibleIds)** | Same as P1 — skip the write |

### Suppress entirely

| Integration | Why |
|---|---|
| **SES email to CDS / partners** | External stakeholders must never receive test emails |
| **Google Chat webhook** | Avoid noise in the team channel |

---

## Wrike Test Record Hygiene

When a Wrike record is created during a test run:

1. **Prefix the title** with `[TEST]` so it is visually distinct in the Wrike UI.
2. **Add a comment** on the record: `"⚠️ Test record created by automated test run. Safe to delete."`
3. After the test, the tester is responsible for manually deleting or archiving the record.

---

## Logging Requirements

In test mode, every simulated or suppressed action must produce a structured log entry at `INFO` level:

```
[test-mode] SIMULATED <action> | <details>
[test-mode] SUPPRESSED <action> | <reason>
```

Examples:

```
[test-mode] SIMULATED create_folder | name="123 Main St, Dallas, TX" parent_id="1RqwLyx..." subfolders=7
[test-mode] SIMULATED upload_file | filename="LOI.pdf" folder_id="abc123" size_bytes=54210
[test-mode] SIMULATED assign_p1 | contacts=["KUAHX4WI"] reasoning="Nonstop ATL→DFW, fewest sites"
[test-mode] SUPPRESSED send_loi_email | to=["mswannie@cdsdevelopment.com",...] reason="test mode"
[test-mode] SUPPRESSED google_chat_webhook | reason="test mode"
```

---

## How to Run a Test

### Option A — Send a test email

Send an email **from `greg.foote@trilogy.com`** with subject matching `New Site - <address>` to the `edu.ops@trilogy.com` inbox. The agent detects the sender and enters test mode automatically.

### Option B — Dry-run via environment variable

Set the environment variable before starting the server:

```bash
DRY_RUN=true uv run alpha-analysis-downstream-processing-mcp
```

This forces test mode regardless of the sender email.

---

## Checklist — What to Verify After a Test Run

- [ ] Wrike record was created with `[TEST]` prefix
- [ ] Wrike custom fields (address, market, scores) populated correctly
- [ ] P1 assignment was **computed** and logged but **not written** to the record
- [ ] No Google Drive folders were created (check logs for `SIMULATED` entries)
- [ ] No Google Slides presentation was created
- [ ] No email was sent (check SES send logs or CloudWatch)
- [ ] No Google Chat message was posted
- [ ] Flight scoring logic ran and produced expected output in logs
