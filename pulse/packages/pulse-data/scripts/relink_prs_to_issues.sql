-- relink_prs_to_issues.sql
--
-- One-off backfill: populate eng_pull_requests.linked_issue_ids by scanning
-- PR titles for Jira-style issue keys (e.g. ANCR-1234) and matching them to
-- existing eng_issues rows.
--
-- Use this when:
--   1. The PR linker was added after PRs were already ingested (the case
--      at the time of ADR-005 migration), OR
--   2. A full Jira backfill just completed and you want to catch newly-
--      imported issues in already-persisted PRs without re-fetching 60k+
--      PRs from GitHub.
--
-- Cost: ~1-3 seconds on 100k PRs / 50k issues. Pure SQL, no Python.
--
-- Scope: matches on title only (since `head_ref` is not persisted). New
-- PRs coming through the live pipeline are linked on title + head_ref +
-- base_ref — see normalizer.apply_pr_issue_links().
--
-- Usage:
--   docker exec -i pulse-postgres psql -U pulse -d pulse < relink_prs_to_issues.sql

BEGIN;

WITH pr_keys AS (
    SELECT
        pr.id           AS pr_id,
        UPPER(m[1])     AS issue_key
    FROM eng_pull_requests pr
    CROSS JOIN LATERAL regexp_matches(
        COALESCE(pr.title, ''),
        '([A-Z][A-Z0-9]+-\d+)',
        'gi'
    ) AS m
),
issue_keys AS (
    SELECT
        external_id,
        UPPER(SUBSTRING(external_id FROM '([A-Z][A-Z0-9]+-[0-9]+)')) AS issue_key
    FROM eng_issues
    WHERE external_id ~ '[A-Z][A-Z0-9]+-[0-9]+'
),
matches AS (
    SELECT DISTINCT pk.pr_id, ik.external_id
    FROM pr_keys pk
    JOIN issue_keys ik USING (issue_key)
),
agg AS (
    SELECT pr_id, jsonb_agg(DISTINCT to_jsonb(external_id)) AS links
    FROM matches
    GROUP BY pr_id
)
UPDATE eng_pull_requests p
SET linked_issue_ids = agg.links,
    updated_at       = NOW()
FROM agg
WHERE p.id = agg.pr_id;

-- Verification
SELECT
    COUNT(*)                                                      AS total_prs,
    COUNT(*) FILTER (WHERE jsonb_array_length(linked_issue_ids) > 0) AS linked_prs,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE jsonb_array_length(linked_issue_ids) > 0) / NULLIF(COUNT(*), 0),
        1
    ) AS linked_pct
FROM eng_pull_requests;

COMMIT;
