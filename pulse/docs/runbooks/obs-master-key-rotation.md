# Observability Master-Key Rotation Runbook

- **Last updated:** 2026-05-11 (FDD-OBS-001 Phase 1 T1.2)
- **Owner:** Platform / SRE — coordinate with CISO on first run
- **Related:** ADR-021 (credential encryption), RISK-8 (rotation gap),
  `scripts/rotate_obs_master_key.py`

This runbook describes how to rotate `PULSE_OBS_MASTER_KEY` — the
pgcrypto master key that encrypts every row in
`tenant_observability_credentials`. Rotation re-encrypts the existing
ciphertexts with a new key in a single transaction per row.

The script is **idempotent** and defaults to **dry-run**. You will
not damage anything by following the order below.

---

## When to rotate

| Trigger | Urgency | Notes |
|---------|---------|-------|
| Suspected leak (key in chat history, logs, screen-share) | Immediate | Treat the key as compromised even if you can't prove it. |
| Quarterly cadence | Scheduled | Calendar-driven hygiene. |
| Team turnover (anyone with prod env access leaves) | Within 7 days | Same hygiene rule we apply to AWS IAM keys. |
| Suspected DB breach | Immediate | Combine with credential re-issue from each tenant's vendor side. |

**Do NOT rotate** in response to a routine `--validate` failure or an
expired vendor API key — those are tenant-side rotations (handled by
`POST /v1/admin/integrations/<provider>/credentials`).

---

## Pre-flight checklist

Run these checks **in order**. Do not proceed until each one is green.

- [ ] **Generate the new master key** with a CSPRNG, NOT a clipboard-paste
      from a webpage:
      ```bash
      openssl rand -hex 32
      # 64 hex chars = 32 bytes. Minimum acceptable length.
      ```
- [ ] **Take a database backup** of `tenant_observability_credentials`
      (this is the only table the script touches — small, fast).
      ```bash
      docker compose exec -T postgres \
          pg_dump -U pulse -d pulse \
              -t tenant_observability_credentials \
              > /tmp/tenant_obs_creds_$(date +%F).sql
      ```
- [ ] **Pause the obs-rollup-worker** so a credential read mid-rotation
      can't blow up:
      ```bash
      docker compose stop obs-rollup-worker
      ```
      (The worker reads decrypted credentials per cycle. If a row is
      being re-encrypted at the exact moment the worker tries to read
      it, the read returns garbage because the worker's env still has
      the OLD key. Pause prevents this.)
- [ ] **Confirm pulse-data API still serves**: hit `/health` (returns
      200) — capacity to validate post-rotation.
- [ ] **Note the current `key_fingerprint` values** for audit:
      ```bash
      docker compose exec -T postgres psql -U pulse -d pulse -c \
          "SELECT tenant_id, provider, key_fingerprint, last_rotated_at
           FROM tenant_observability_credentials
           ORDER BY tenant_id, provider;"
      ```
      The fingerprints are derived from the **plaintext API key** (not
      the master key), so they will NOT change after rotation. If any
      of them change, that's a bug — investigate before continuing.

---

## Step-by-step rotation

### Step 1 — Set both env vars

In the **operator's own shell** (do NOT edit shared `.env` files yet):

```bash
export PULSE_OBS_MASTER_KEY=<the CURRENT key from pulse/.env>
export PULSE_OBS_MASTER_KEY_NEW=<the NEW key from openssl rand -hex 32>
```

CRITICAL: never paste either key into chat, ticket, Slack, email.
If you accidentally do, treat the rotation as compromised before it
started and start over with a third key.

### Step 2 — Dry-run

```bash
cd pulse/
python scripts/rotate_obs_master_key.py --dry-run
```

Expected output (one INFO line per credential row):

```
2026-05-11 14:30:00 [INFO] DRY-RUN MODE — no rows will be updated. Pass --apply to write.
2026-05-11 14:30:00 [INFO] found 1 credential rows to consider
2026-05-11 14:30:00 [INFO] DRY-RUN would rotate tenant=... provider=datadog new_fp=a1b2c3d4...
2026-05-11 14:30:00 [INFO] DONE. rotated=1 failed=0 idempotent_skip=0 dry_run=True
2026-05-11 14:30:00 [INFO] rows touched: 1
```

If any row shows `FAILED tenant=... err_class=...`, **stop here**. The
OLD key cannot decrypt that row. Possibilities:
  - You typed the wrong OLD key — re-check `.env`.
  - The row was already partially rotated — see Recovery section below.
  - DB corruption — restore from backup and escalate.

### Step 3 — Apply

```bash
python scripts/rotate_obs_master_key.py --apply
```

Expected output:

```
2026-05-11 14:31:00 [WARN] APPLY MODE — rows will be re-encrypted.
2026-05-11 14:31:00 [INFO] found 1 credential rows to consider
2026-05-11 14:31:00 [INFO] rotated tenant=... provider=datadog new_fp=a1b2c3d4...
2026-05-11 14:31:00 [INFO] DONE. rotated=1 failed=0 idempotent_skip=0 dry_run=False
2026-05-11 14:31:00 [INFO] rows touched: 1
```

The `new_fp` value MUST match what you noted in the pre-flight check
(same plaintext → same fingerprint). If it differs, investigate
immediately.

### Step 4 — Update `pulse/.env`

The user (not Claude — see CRITICAL SAFETY RULES) must now:

1. Edit `pulse/.env` in their own editor.
2. Replace the OLD `PULSE_OBS_MASTER_KEY=...` with the NEW value.
3. Save.
4. Run `make rotate-secrets` from `pulse/` — this re-creates the
   pulse-data + worker containers so they pick up the new env.

### Step 5 — Resume workers + validate

```bash
docker compose up -d obs-rollup-worker
```

Verify the credential round-trip works with the NEW key:

```bash
# Per-tenant metadata-only readback (no plaintext output).
curl -sf -H "X-Tenant: <your-tenant-uuid>" \
    http://localhost:8000/data/v1/admin/integrations/datadog/metadata \
    | python3 -m json.tool
```

The response should include `validated_at`, `last_rotated_at` (now
within minutes of `NOW()`), and `key_fingerprint` (unchanged from
pre-flight). If `validated_at` is null OR the fingerprint changed,
something is wrong — see Recovery.

### Step 6 — Remove OLD env var from operator shell

```bash
unset PULSE_OBS_MASTER_KEY        # the OLD value
unset PULSE_OBS_MASTER_KEY_NEW
```

(The `.env` now carries only the NEW key; the operator's shell should
not retain the old one after this point.)

### Step 7 — Audit log

Record in the team's secrets ledger:
  - Date / time of rotation.
  - Number of rows rotated (from script output).
  - Trigger (suspected leak / scheduled / turnover).
  - Operator name (not the keys themselves).

---

## Recovery: half-completed rotation

The script processes rows one at a time, each in its own transaction.
If it crashes mid-run, some rows are encrypted with OLD and others
with NEW. To recover:

1. **Don't panic — restore is not the first move.** The script is
   idempotent: a re-run with `--apply` will succeed for rows already
   re-encrypted with NEW (they decrypt cleanly with OLD only if they
   weren't yet rotated; rows that ARE already rotated will FAIL the
   decrypt step and skip).

   Wait — that means re-running with the OLD key in env will fail
   on the already-rotated rows. To complete:

2. **Run the script a SECOND time** with the **NEW key as the OLD env
   var** (i.e. swap so the script reads ciphertexts written with NEW
   and re-writes them with NEW — idempotent no-op for those rows;
   rows still encrypted with OLD will fail the decrypt and need
   manual handling).

   Actually simpler: identify the failed rows via the script's log
   (each `FAILED tenant=...` line), restore those rows from the
   backup taken in pre-flight, and re-run from scratch.

3. **If both OLD and NEW are lost**: restore from the
   `tenant_obs_creds_<date>.sql` backup taken in pre-flight, and
   either re-issue credentials from each tenant's vendor side (every
   tenant must rotate their API key in their Datadog org) or
   restore the previous master key from the secrets vault.

The script logs `err_class=<ExceptionClass>` for failed rows — that
class name (e.g. `OperationalError`, `IntegrityError`) is your
debugging starting point. NEVER log `str(exc)` because pgcrypto
errors can include the bound parameter values.

---

## Smoke test (programmatic)

After rotation, the unit tests under
`tests/unit/test_rotate_obs_master_key.py` cover the round-trip:

```bash
cd pulse/
docker compose exec -T pulse-data python -m pytest \
    tests/unit/test_rotate_obs_master_key.py -v
```

All tests must pass before declaring the rotation complete.

---

## What rotation does NOT change

- `tenant_id`, `provider`, `site`, `validated_at` — preserved.
- `key_fingerprint` — recomputed from the same plaintext API key,
  so the VALUE doesn't change (defense against tampering).
- Tenant's vendor-side API key — that's a separate rotation handled
  via the admin `POST /credentials` endpoint with a fresh DD API key.
- The pgcrypto algorithm — still `pgp_sym_*`.

If you need to rotate the tenant's vendor-side API key, that's a
DIFFERENT runbook — `POST /v1/admin/integrations/datadog/credentials`
with the new key, then this rotation is unaffected.
