# Safe Run Guide

This guide is for the first real run when account safety matters more than throughput.

## Current conservative defaults

- `--pages` defaults to `1`
- `--detail` is off by default
- `--max-notes-total` defaults to `10`
- `--persistent-context` is on by default
- `--resume` is on by default
- `--skip-enriched-detail` is on by default
- `--history` is on by default
- Search delays default to `4-7` seconds
- Detail delays default to `3-5` seconds
- Comment delays default to `4-6` seconds
- Detail network wait defaults to `--detail-timeout 12`
- Detail render wait defaults to `--detail-render-wait 4`
- Empty detail snapshots can retry once with `--detail-empty-retries 1`
- The crawler stops early when it sees repeated empty batches
- The crawler stops early when the page looks like login or verification flow
- The crawler does not implement CAPTCHA bypass, signature forging, access-control bypass, or high-frequency request logic

## Recommended first live attempts

0. If you need to switch from an old account/profile to a different personal account, use an ephemeral login first:

```bash
python main.py login --ephemeral-context
```

Then add `--ephemeral-context` to the next live command. This avoids reusing `session/browser_profile` from the previous account.

1. Search only, no detail:

```bash
python main.py search "<keyword>" --pages 1 --max-notes-total 5 --headed --no-detail
```

2. Search with a small amount of detail enrichment:

```bash
python main.py search "<keyword>" --pages 1 --max-notes-total 5 --headed --detail --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10
```

If you already validated a smaller detail batch, increase `--max-notes-total` without `--force-detail`.
The crawler will reuse historical detail fields and skip notes that were already processed:

```bash
python main.py search "<keyword>" --resume --pages 1 --max-notes-total 10 --headed --detail --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10
```

4. Batch keywords, sequential and low frequency:

```bash
python main.py batch keywords.txt --resume --pages 1 --max-notes-total 5 --headed --detail --no-comments --keyword-delay-min 30 --keyword-delay-max 60 --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10
```

5. Only after the previous step is stable, try comments:

```bash
python main.py search "<keyword>" --pages 1 --max-notes-total 3 --headed --detail --with-comments --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10
```

6. If you want to ignore an older checkpoint and force a completely new search run:

```bash
python main.py search "<keyword>" --fresh-run --pages 1 --max-notes-total 5 --headed --no-detail
```

7. If detail quality is incomplete, generate a local queue before any live retry:

```bash
python main.py detail-queue "<keyword>" --max-notes-total 5 --only-recommended
```

Then retry only the recommended note ids:

```bash
python main.py search "<keyword>" --resume --detail --no-comments --note-ids-file data/queues/<queue>_note_ids.txt --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10
```

## What changed in the code

- Login and crawl now prefer a persistent browser profile directory
- Session metadata is archived to `session/session_meta.json`
- Search scrolling now uses smaller steps and longer settle times
- Search stops after the first empty batch instead of blindly continuing
- Search respects a run-wide `--max-notes-total` cap
- The crawler can reuse the latest checkpoint for the same query without replaying search traffic
- Resume mode can reuse historical detail fields from newer checkpoints even when it loads an older checkpoint with more notes
- Detail enrichment skips already processed notes by default; use `--force-detail` only for parser/debug validation
- Each completed run writes quality reports next to the normal exports
- Each completed run attempts to persist normalized records into `data/history.sqlite3`
- Batch mode runs keywords sequentially and writes batch reports under `data/batches/`
- Detail and comment phases stop after repeated failures
- Detail and comment phases stop when the page looks unsafe to continue
- Detail enrichment can fall back to embedded page state when network JSON is missing
- Detail enrichment validates the target `note_id` before merging fields
- Detail enrichment distinguishes empty snapshots from incomplete-but-nonempty detail evidence
- Detail enrichment can capture multi-stage DOM probes when `--save-raw-json` is enabled
- The CLI now defaults to a smaller first run instead of an aggressive crawl

## Suggested operating rule

Do not scale up immediately after a failed run. Fix the log signal first, then retry once with the same small scope.
Do not use `--force-detail` for normal expansion runs; it intentionally reopens already processed detail pages.
If the browser shows CAPTCHA, verification, login interruption, or obvious risk-control content, stop the run and do not add bypass logic.
Do not use another account to bypass an account-specific restriction. Use account switching only when the account is yours, in good standing, and manually logged in.
Use `best-export` and local reparse commands to improve existing data before increasing live traffic.
