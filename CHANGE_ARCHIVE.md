# Change Archive

## Cycle 1

### Read

- Reviewed `littlecrawler_eg.md`
- Reviewed `xianyv_eg.md`
- Compared those patterns with the current scraper implementation

### Planned work

- Borrow persistent browser-profile reuse from the LittleCrawler-style approach
- Borrow a detail-page fallback path instead of relying on one network path only
- Archive session metadata so later retries need less guesswork

### Problems summarized

- The project only reused `storage_state.json`, which is weaker than a persistent browser profile
- Detail enrichment depended on captured network JSON only
- Session state had no metadata archive for later inspection

### Modifications

- Added `browser_profile_dir` and `session_meta_path` to [scraper/config.py](/d:/xiaohongshu_scraper/scraper/config.py:18)
- Reworked [scraper/auth.py](/d:/xiaohongshu_scraper/scraper/auth.py:1) to support persistent browser profiles and write `session/session_meta.json`
- Added `--persistent-context` and `--ephemeral-context` to [main.py](/d:/xiaohongshu_scraper/main.py:170)
- Added `detail_html` raw capture support in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:40)
- Added HTML embedded-state parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:147)
- Added detail HTML fallback in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:121)

### Improvement review

- High-value improvement still remained: checkpoints were written, but not reused to avoid repeated live traffic

## Cycle 2

### Read

- Re-read checkpoint persistence in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:20)
- Re-read detail and comment stage flow in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:18) and [scraper/comments.py](/d:/xiaohongshu_scraper/scraper/comments.py:17)
- Re-read CLI orchestration in [main.py](/d:/xiaohongshu_scraper/main.py:33)

### Planned work

- Reuse the latest checkpoint for the same query
- Avoid replaying search-stage traffic when a checkpoint already contains notes
- Resume detail and comment stages after the last successfully processed note

### Problems summarized

- The crawler persisted checkpoints but always started a new live search
- Partial failures still forced repeated visits to the same search flow
- Comment-stage checkpoint metadata was not precise enough for safe resume

### Modifications

- Added checkpoint loading via `CheckpointSnapshot` in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:12)
- Added `--resume` and `--fresh-run` in [main.py](/d:/xiaohongshu_scraper/main.py:273)
- Taught [main.py](/d:/xiaohongshu_scraper/main.py:84) to reuse checkpointed notes/comments/failures
- Taught [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:28) to skip notes already completed in a prior run
- Taught [scraper/comments.py](/d:/xiaohongshu_scraper/scraper/comments.py:18) to resume from existing comments and skip completed notes

### Improvement review

- The remaining improvements I considered would require real-site validation, so they are not good candidates for another offline-only cycle

## Final note

- The project now prefers persistent session reuse, can recover detail data from page state, and can continue from prior checkpoints without replaying the heaviest search traffic by default

## Cycle 3

### Read

- Re-read `scraper/search.py`, `scraper/detail.py`, `scraper/comments.py`, and `scraper/exporter.py`
- Re-read `AGENTS.md` verification requirements for fixtures, export validation, and failed-sample capture

### Planned work

- Add stable record deduplication so resumed runs do not inflate detail/comment traffic
- Archive page-level failure samples for offline debugging instead of repeating live retries
- Add fixed-fixture tests for parser, dedupe, export, and storage behavior

### Problems summarized

- Search/checkpoint reuse could still leave duplicate notes or comments in later stages
- Failures were exported as text only, without enough local artifacts for diagnosis
- Parser and export changes still lacked fixture-based regression coverage

### Modifications

- Added [scraper/dedupe.py](/d:/xiaohongshu_scraper/scraper/dedupe.py:1) and integrated it from [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Extended [scraper/models.py](/d:/xiaohongshu_scraper/scraper/models.py:1) failure exports with `page_url` and `artifact_ref`
- Added failure artifact capture in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)
- Wired failure artifact capture into [scraper/search.py](/d:/xiaohongshu_scraper/scraper/search.py:1), [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:1), and [scraper/comments.py](/d:/xiaohongshu_scraper/scraper/comments.py:1)
- Added fixed fixtures and regression tests under [tests](/d:/xiaohongshu_scraper/tests:1)
- Corrected runtime normalization/signals affected by garbled Chinese literals in [scraper/utils.py](/d:/xiaohongshu_scraper/scraper/utils.py:1), [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1), and [scraper/auth.py](/d:/xiaohongshu_scraper/scraper/auth.py:1)

### Improvement review

- The next meaningful gains now require real-site evidence: current payload variants, current risk prompts, or current comment pagination behavior

## Cycle 4

### Read

- Inspected the low-quality export `data/exports/哈尔滨_旅游_20260425_221521_notes.csv`
- Replayed saved raw detail responses from `data/raw/哈尔滨_旅游_20260425_221521/detail.jsonl`
- Re-read the detail parsing and response-recognition path in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1)

### Planned work

- Stop treating search suggestions, comment payloads, and user-profile payloads as note detail responses
- Prevent wrong detail payloads from overwriting search-stage titles, content, and author fields
- Add offline regression tests so the same data-quality bug can be caught without another live account run

### Problems summarized

- Detail response detection was too permissive: a payload with `title`, `content`, `desc`, or `note_id` could be accepted as detail data
- Search suggestion payloads caused `title=猜你想搜`
- Comment payloads caused note content/author fields to be replaced by comment text/comment users
- Profile payloads could be selected as the best detail object because they also contain `desc`, `nickname`, and avatar image fields
- `images` in CSV are intentionally exported as image URLs; actual image-file downloading is a separate feature

### Modifications

- Tightened `looks_like_detail_response` and `_detail_item_score` in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:39)
- Added explicit rejection for comment-like, search-suggestion-like, and profile-like payloads in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:731)
- Added note-id mismatch protection before detail updates are merged in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:92)
- Added regression coverage in [tests/test_detail_response_filtering.py](/d:/xiaohongshu_scraper/tests/test_detail_response_filtering.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 15 tests passed
- Ran `python main.py search --help`: CLI startup succeeded
- Replayed old bad `detail.jsonl`: `old_wrong_detail_lines=10`, `recognized_after_fix=0`
- Replayed old bad `detail.jsonl` through `parse_detail_response`: `usable_updates=0`, `bad_updates=0`

### Improvement review

- Polluted checkpoints from earlier detail runs can still contain bad exported fields. Use a fresh search checkpoint before validating this fix live.
- If local image files are required, add a separate opt-in image downloader instead of overloading the `images` export column.

## Cycle 5

### Read

- Inspected `data/exports/哈尔滨_旅游_20260425_224620_notes.csv`
- Replayed `data/raw/哈尔滨_旅游_20260425_224620/search.jsonl`
- Replayed `data/raw/哈尔滨_旅游_20260425_224650/detail.jsonl`
- Re-read count and cover parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1)

### Planned work

- Verify whether `like_count`, `collect_count`, `comment_count`, `share_count`, and `view_count` match raw payload fields
- Fix count aliases that are present in raw data but missing in parser mappings
- Avoid treating user-profile metric payloads as note-detail payloads
- Fix cover-image export so it stores a URL instead of a raw dict string

### Problems summarized

- Search raw uses `interact_info.shared_count`, but the parser only recognized `share_count`, `shares`, and `shareCount`
- `view_count` was not present in the current saved search/detail payloads, so it should remain blank instead of being guessed
- A detail-stage profile payload shaped like `basic_info + interact_info(fans/follows/interaction) + notes` was still being accepted as a usable detail payload
- `cover_image` could export the whole `cover` object instead of its first image URL

### Modifications

- Added `shared_count` and `sharedCount` aliases for `share_count` in search and detail parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:252)
- Tightened note-detail scoring so profile interaction metrics such as `fans`, `follows`, and `interaction` are not accepted as note metrics in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:732)
- Added first-image URL extraction for `cover_image` in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:121)
- Added regression tests in [tests/test_metric_field_mapping.py](/d:/xiaohongshu_scraper/tests/test_metric_field_mapping.py:1) and expanded [tests/test_detail_response_filtering.py](/d:/xiaohongshu_scraper/tests/test_detail_response_filtering.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 18 tests passed
- Replayed `224620/search.jsonl`: `share_count` now maps from `shared_count`
- Replayed `224650/detail.jsonl`: profile payload now returns `looks_like_detail=False` and no updates
- Generated corrected offline export from existing raw data: `data/exports/哈尔滨_旅游_20260425_224620_reparsed_notes.csv`

### Improvement review

- `view_count` should be treated as optional because current Xiaohongshu web payloads may not expose it
- Future export validation should compare parsed metric fields against raw fixture paths before live retries

## Cycle 6

### Read

- Inspected `data/exports/哈尔滨_旅游_20260425_224620_reparsed_notes.csv`
- Replayed `data/raw/哈尔滨_旅游_20260425_224620/search.jsonl`
- Checked `data/raw/哈尔滨_旅游_20260425_224650/detail_html.jsonl` for the target note id, title, note content, publish-time, location, IP, and tag markers

### Planned work

- Determine which empty fields are parser misses and which fields are absent from saved raw payloads
- Recover any fields that are present in search-card raw data
- Avoid inventing missing content/location/IP/tag fields when raw evidence is unavailable

### Problems summarized

- Search-card raw data did include publish date in `note_card.corner_tag_info`, but the parser did not read it
- The same search-card raw data did not include note body content, location, IP location, or tags
- The saved `224650` detail raw/HTML did not contain the target note id or title, so it cannot be used to recover note body content or metadata

### Modifications

- Added search-card `corner_tag_info(type=publish_time)` extraction in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:484)
- Added explicit partial-date normalization for `MM-DD` / `MM/DD` and common relative forms such as `3天前` in [scraper/utils.py](/d:/xiaohongshu_scraper/scraper/utils.py:157)
- Extended parser regression coverage in [tests/test_metric_field_mapping.py](/d:/xiaohongshu_scraper/tests/test_metric_field_mapping.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 19 tests passed
- Generated corrected offline export from existing raw data: `data/exports/哈尔滨_旅游_20260425_224620_reparsed_v3_notes.csv`
- Confirmed `publish_time` now fills from search raw where available

### Improvement review

- `content`, `location`, `ip_location`, and `tags` require a real note-detail payload or reliable detail DOM fallback; the current saved search raw cannot provide them
- The scraper should continue treating missing detail metadata as missing rather than copying title into content or fabricating tags

## Cycle 7

### Read

- Re-read detail-stage logs for `data/logs/哈尔滨_旅游_20260425_224650.log`
- Re-read [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:1) network/HTML fallback flow
- Re-read [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1) detail parsing behavior

### Planned work

- Explain why search-only raw cannot solve body/location/tag fields
- Add a conservative fallback for rendered detail-page text
- Ensure wrong pages do not become false successful detail enrichments
- Save enough raw DOM text for offline debugging when JSON detail payloads are unavailable

### Problems summarized

- The search-card payload does not contain full note body, location, IP location, or tags
- The saved `224650` detail attempt did not capture a target note-detail JSON payload
- Existing HTML-state fallback only handles embedded JSON state; it cannot extract rendered DOM text
- When the site renders detail content without a usable JSON payload, the crawler needs a DOM fallback

### Modifications

- Added `parse_detail_visible_text` in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:224)
- Added rendered DOM fallback in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:133)
- Saved DOM fallback samples as `detail_dom.jsonl` when `--save-raw-json` is enabled
- Taught resume logic in [main.py](/d:/xiaohongshu_scraper/main.py:110) to reprocess stale detail checkpoints that lack detail fields
- Added regression tests in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 23 tests passed
- Ran `python main.py search --help`: CLI startup succeeded

### Improvement review

- The next live validation should use only one detail note first. If DOM fallback works, `content`, `tags`, `location`, and `ip_location` may fill from visible page text.
- If the page opens but still lacks visible detail text, the export should show a failure record instead of pretending the detail stage succeeded.

## Cycle 8

### Read

- Inspected `data/exports/哈尔滨_旅游_20260425_233419_failed_records.csv`
- Inspected `data/logs/哈尔滨_旅游_20260425_233419.log`
- Inspected `data/raw/哈尔滨_旅游_20260425_233419/failure_context.jsonl`
- Re-read raw payload handling in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)

### Planned work

- Identify whether the latest failure was platform-related or caused by code
- Fix the raw-stage registration error for `detail_dom`
- Prevent future raw-stage additions from failing with `KeyError`

### Problems summarized

- The latest detail attempt reached the target note page, but failed with `KeyError: 'detail_dom'`
- `RunStorage.raw_files` did not register `detail_dom.jsonl`
- `append_raw` assumed every raw stage had been pre-registered, making future fallback stages fragile

### Modifications

- Added `detail_dom` to raw file registration in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:44)
- Made [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:52) create a stage-specific JSONL file for unknown future raw stages instead of raising `KeyError`
- Added storage regression tests in [tests/test_storage.py](/d:/xiaohongshu_scraper/tests/test_storage.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 25 tests passed
- Ran `python main.py search --help`: CLI startup succeeded

### Improvement review

- The next single-note live validation can retry the same command; this failure was a local raw-storage bug, not an account or site block.

## Cycle 9

### Read

- Inspected `data/exports/哈尔滨_旅游_20260425_234326_notes.csv`
- Inspected `data/raw/哈尔滨_旅游_20260425_234326/detail_dom.jsonl`
- Replayed the saved DOM text through [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:274)

### Planned work

- Fix DOM fallback so hashtag-only lines populate `tags` but do not pollute `content`
- Restrict DOM metadata extraction to the target note area instead of global page chrome/footer text
- Remove stale detail failure records when a later retry succeeds for the same note
- Make tag-only `content` checkpoints eligible for detail reprocessing

### Problems summarized

- The first DOM fallback output put the note hashtag line into `content`
- Global footer/legal text contained date-like strings and could be mistaken for publish time
- A successful detail retry still carried an older failure row from the checkpoint
- A checkpoint with `content="#tag..."` could be incorrectly treated as complete detail enrichment

### Modifications

- Added detail-section scoping for DOM metadata in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:274)
- Added tag-line filtering from DOM content extraction in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:852)
- Added stale detail-failure cleanup on success in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:54)
- Added tag-only content detection in [main.py](/d:/xiaohongshu_scraper/main.py:239)
- Expanded regression coverage in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1) and [tests/test_resume_safety.py](/d:/xiaohongshu_scraper/tests/test_resume_safety.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 28 tests passed
- Ran `python main.py search --help`: CLI startup succeeded
- Replayed `data/raw/哈尔滨_旅游_20260425_234326/detail_dom.jsonl`: `content=""`, `publish_time=2026-04-10`, `ip_location=黑龙江`, tags populated
- Generated corrected offline export: `data/exports/哈尔滨_旅游_20260425_234326_reparsed_notes.csv`

### Improvement review

- The target note appears to have no standalone body text beyond hashtags in the rendered detail page, so `content` should remain blank rather than copying tags or comments.
- A future live run over more notes should still start with a small batch because full body availability depends on what the rendered detail page exposes.

## Cycle 10

### Read

- Re-inspected `data/exports/哈尔滨_旅游_20260425_234326_reparsed_notes.csv`
- Replayed `data/raw/哈尔滨_旅游_20260425_234326/detail_dom.jsonl`
- Checked the saved failure HTML meta tags for the same note
- Re-read DOM fallback parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:274) and DOM capture in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:235)

### Planned work

- Stop relying only on `body.innerText` for distinguishing tags from body text
- Capture structured DOM nodes near the target note title, including tag name, class, href, role, aria label, and text
- Prefer structured node parsing before falling back to plain visible text
- Add a safe way to re-run detail enrichment without replaying search or keeping stale detail fields

### Problems summarized

- The old DOM raw had only flat text, so it could not distinguish UI tag elements from ordinary body text elements
- In the user-observed UI, `值得N刷的宝藏出游地` appears to be body text, but the old flat text snapshot represented it as `#值得N刷的宝藏出游地`
- A normal `--resume` could skip detail because the checkpoint was already marked as enriched
- Old incorrect tags/content could merge back into new results unless cleared before reprocessing

### Modifications

- Added `parse_detail_dom_snapshot` and structured-node parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:311)
- Added structured DOM capture in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:243)
- Added `--force-detail` CLI support in [main.py](/d:/xiaohongshu_scraper/main.py:416)
- Added stale detail-field clearing before forced detail reprocessing in [main.py](/d:/xiaohongshu_scraper/main.py:252)
- Added regression coverage in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1) and [tests/test_resume_safety.py](/d:/xiaohongshu_scraper/tests/test_resume_safety.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 30 tests passed
- Ran `python main.py search --help`: CLI startup succeeded and shows `--force-detail`
- Verified argument parsing for `--force-detail`

### Improvement review

- Existing `234326` raw cannot answer the UI-structure question because it lacks `structured_nodes`
- The next single-note validation should use `--force-detail` so it captures a fresh structured DOM snapshot without replaying search

## Cycle 11

### Read

- Re-read `AGENTS.md` harness workflow requirements
- Re-read resume/detail checkpoint flow in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Re-read detail-stage loop in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:1)
- Re-read checkpoint loading and persistence in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)
- Re-read the safe-run guidance in [SAFE_RUN.md](/d:/xiaohongshu_scraper/SAFE_RUN.md:1)

### Planned work

- Prevent normal expansion runs from reopening detail pages already validated in smaller runs
- Preserve `--force-detail` as an explicit parser/debug reprocessing mode
- Reuse historical detail fields when a larger `--max-notes-total` makes resume load an older checkpoint with more notes
- Add regression tests so this account-safety behavior is checked offline

### Problems summarized

- `--force-detail` intentionally reruns the same notes, which was useful for parser validation but unsafe for normal expansion
- `load_latest_checkpoint(..., min_notes=N)` may load an older checkpoint when increasing `--max-notes-total`
- Without historical detail reuse, the older checkpoint may not know that newer smaller runs already enriched the first notes
- Search-card-only tags should not count as detail completion, or real detail pages could be skipped too early

### Modifications

- Added internal `detail_processed` checkpoint state and reusable-detail helpers in [scraper/models.py](/d:/xiaohongshu_scraper/scraper/models.py:1)
- Added `RunStorage.load_reusable_detail_history(...)` in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:159)
- Added historical detail-field merge before resume detail processing in [main.py](/d:/xiaohongshu_scraper/main.py:102)
- Added default `--skip-enriched-detail` / `--no-skip-enriched-detail` CLI control in [main.py](/d:/xiaohongshu_scraper/main.py:444)
- Added detail-loop skip behavior in [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:46)
- Updated [SAFE_RUN.md](/d:/xiaohongshu_scraper/SAFE_RUN.md:1) and [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)
- Added regression coverage in [tests/test_resume_safety.py](/d:/xiaohongshu_scraper/tests/test_resume_safety.py:1) and [tests/test_storage.py](/d:/xiaohongshu_scraper/tests/test_storage.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 34 tests passed
- Ran `python main.py search --help`: CLI startup succeeded and shows `--skip-enriched-detail` / `--no-skip-enriched-detail`
- Ran an offline checkpoint simulation for `max_notes_total=5`: loaded `data/checkpoints/哈尔滨_旅游_20260425_224620_checkpoint.json`, merged 3 historical detail records, and left only notes 4-5 as not yet reusable

### Improvement review

- Normal expansion should now omit `--force-detail`; increase `--max-notes-total` gradually and let resume skip already processed detail pages
- If the user explicitly wants to revalidate parser quality on the same notes, `--force-detail` is still available and intentionally bypasses the skip

## Cycle 12

### Read

- Re-read export and storage flow in [scraper/exporter.py](/d:/xiaohongshu_scraper/scraper/exporter.py:1) and [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)
- Re-read CLI construction in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Re-ran the non-live baseline test suite before implementation

### Planned work

- Add a SQLite history database as the durable project memory
- Add per-run data quality reports so exports can be judged without manual column-by-column inspection
- Add a low-frequency batch keyword command
- Keep all additions non-invasive: no new third-party dependency, no live-site access during implementation

### Problems summarized

- CSV exports alone are weak for long-term dedupe, cross-run inspection, and repeated keyword work
- Users currently need to manually inspect data quality after every run
- Running multiple keywords manually increases operational mistakes and makes low-frequency pacing harder
- SQLite may fail in restricted environments; export files should still be preserved if history persistence fails

### Modifications

- Added `data/history.sqlite3` path support and `persist_history` option in [scraper/config.py](/d:/xiaohongshu_scraper/scraper/config.py:1)
- Added SQLite history persistence in [scraper/history.py](/d:/xiaohongshu_scraper/scraper/history.py:1)
- Added per-run quality reports in [scraper/quality.py](/d:/xiaohongshu_scraper/scraper/quality.py:1)
- Integrated history and quality reports from [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)
- Added keyword file loading and batch report output in [scraper/batch.py](/d:/xiaohongshu_scraper/scraper/batch.py:1)
- Added `main.py batch ...` and `--history / --no-history` CLI options in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Updated [README.md](/d:/xiaohongshu_scraper/README.md:1), [SAFE_RUN.md](/d:/xiaohongshu_scraper/SAFE_RUN.md:1), and [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)
- Added regression coverage in [tests/test_history_quality_batch.py](/d:/xiaohongshu_scraper/tests/test_history_quality_batch.py:1)

### Verification

- Ran `python -m unittest discover -s tests`: 37 tests passed
- Ran `python main.py search --help`: CLI startup succeeded and shows `--history / --no-history`
- Ran `python main.py batch --help`: CLI startup succeeded and shows batch keyword controls

### Improvement review

- The next live validation can keep using a single keyword first; quality reports will show whether expanding is justified
- Batch mode should use conservative `--keyword-delay-min` / `--keyword-delay-max`
- History persistence is best-effort: if SQLite fails, exports and quality reports still complete and a `*_history_error.txt` file is written

## Cycle 13

### Read

- Ran the first 5-note live validation after adding history and quality reports
- Inspected `data/exports/哈尔滨_旅游_20260426_153305_notes.csv`
- Inspected `data/raw/哈尔滨_旅游_20260426_153305/detail_dom.jsonl`
- Re-read DOM metadata extraction and SQLite history binding paths

### Planned work

- Fix a live-data parser regression without reopening Xiaohongshu
- Fix history persistence for legacy non-scalar fields from older checkpoints
- Generate corrected exports from the saved raw DOM evidence
- Add regression tests so both failures are caught offline

### Problems summarized

- The 5-note live run behaved correctly operationally: 3 historical details were reused, notes 4-5 were enriched, and failures stayed at 0
- One note body contained `2-3公里`, which the old visible metadata parser misread as a partial date and then as an IP-location suffix
- SQLite history persistence failed on an older dict-shaped `cover_image` value

### Modifications

- Tightened DOM metadata parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1)
- Added SQLite scalar serialization for legacy dict/list fields in [scraper/history.py](/d:/xiaohongshu_scraper/scraper/history.py:1)
- Added regression coverage in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1) and [tests/test_history_quality_batch.py](/d:/xiaohongshu_scraper/tests/test_history_quality_batch.py:1)
- Generated corrected offline exports from saved raw data:
  - `data/exports/哈尔滨_旅游_20260426_153305_reparsed_notes.csv`
  - `data/exports/哈尔滨_旅游_20260426_153305_reparsed_quality_report.json`

### Verification

- Ran `python -m unittest discover -s tests`: 38 tests passed
- Replayed `data/raw/哈尔滨_旅游_20260426_153305/detail_dom.jsonl` offline and confirmed note `69365d82000000001e03a3bc` now has body content and no false `ip_location`

### Improvement review

- The live command is safe to repeat without `--force-detail`; the first 5 notes are now all reusable and should be skipped on normal resume
- The corrected `*_reparsed_notes.csv` should be used for data-quality inspection instead of the first `153305_notes.csv`

## Cycle 14

### Read

- Re-ran `python -m unittest discover -s tests`
- Inspected `data/exports/哈尔滨_旅游_20260426_153305_reparsed_quality_report.json`
- Verified SQLite write capability with a temporary database under `data/`
- Checked that `data/history.sqlite3` had a real summary record after backfilling the corrected local export

### Planned work

- Decide whether the product foundation is truly complete enough to move on
- Strengthen quality reporting before moving to the next capability layer
- Add a quick history summary command so the SQLite store is inspectable without external tools

### Problems summarized

- The foundation is usable, but not "absolutely perfect"; no production crawler should be described that way without longer-running evidence
- The previous quality report had field coverage but did not explicitly list low-coverage optional fields
- There was no CLI command to quickly confirm whether the history database contained runs and notes

### Modifications

- Added `low_coverage_fields` and field importance classification in [scraper/quality.py](/d:/xiaohongshu_scraper/scraper/quality.py:1)
- Added `HistoryStore.summary()` in [scraper/history.py](/d:/xiaohongshu_scraper/scraper/history.py:1)
- Added `python main.py history` in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Extended regression tests in [tests/test_history_quality_batch.py](/d:/xiaohongshu_scraper/tests/test_history_quality_batch.py:1)
- Rewrote `data/exports/哈尔滨_旅游_20260426_153305_reparsed_quality_report.json` with the improved report schema
- Backfilled the corrected 5-note export into `data/history.sqlite3`

### Verification

- Ran `python -m unittest discover -s tests`: 38 tests passed
- Ran `python main.py history --help`: CLI startup succeeded
- Ran `python main.py history`: returned `runs_count=1`, `notes_count=5`, `failures_count=0`
- Rechecked `data/exports/哈尔滨_旅游_20260426_153305_reparsed_quality_report.json`: now includes `low_coverage_fields`

### Improvement review

- The product foundation is now good enough to proceed to the next layer
- It is still not "absolutely perfect" because batch live runs and comment live validation remain unproven

## Cycle 15

### Read

- Ran a minimal live comment validation on one resumed note with `--with-comments`
- Inspected the generated comments CSV and quality report
- Re-read [scraper/quality.py](/d:/xiaohongshu_scraper/scraper/quality.py:1), [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1), and existing quality tests

### Planned work

- Do not expand live traffic while the account risk is the main constraint
- Use the live result to identify offline harness gaps
- Add comment-field coverage to the quality report so comment success is measurable

### Problems summarized

- The live comment run succeeded operationally with 5 first-level comments and 0 failures
- The old quality report only counted `comments_count`; it did not show whether comment content, time, like count, and commenter fields were filled
- This made the comment pipeline harder to verify without manually opening the CSV

### Modifications

- Added `comment_field_coverage` and `low_comment_coverage_fields` to [scraper/quality.py](/d:/xiaohongshu_scraper/scraper/quality.py:1)
- Updated [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1) to pass full `CommentRecord` objects into the report builder
- Extended [tests/test_history_quality_batch.py](/d:/xiaohongshu_scraper/tests/test_history_quality_batch.py:1) with comment-quality coverage assertions
- Updated [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Verification

- Ran `python -m unittest discover -s tests`: 38 tests passed
- Rebuilt a local report from `data/checkpoints/哈尔滨_旅游_20260426_155516_checkpoint.json`
- Confirmed comment coverage from the rebuilt report: `comment_content=5/5`, `comment_time=5/5`, `comment_like_count=5/5`, `commenter_name=5/5`
- Wrote offline refreshed reports:
  - `data/exports/哈尔滨_旅游_20260426_155516_reparsed_quality_report.json`
  - `data/exports/哈尔滨_旅游_20260426_155516_reparsed_quality_report.csv`

### Improvement review

- Comment capture is now observable at the same level as note capture
- Remaining live validation should be deliberately scoped, not repeated casually

## Cycle 16

### Read

- Checked `git status --short`
- Checked whether `.gitignore` existed
- Checked whether `session`, `data`, and `__pycache__` files were already tracked by Git

### Planned work

- Prevent credentials/session state and generated crawler outputs from entering commits
- Keep local files intact while removing them from Git tracking
- Avoid cleaning or deleting user data unless explicitly requested

### Problems summarized

- `.gitignore` did not exist
- `session/storage_state.json` was tracked, which can contain login cookies/session state
- `data/` exports/checkpoints/logs and many `__pycache__` files were also tracked or visible in status
- Test runs generated `tests/.tmp/`, which polluted the worktree

### Modifications

- Added [.gitignore](/d:/xiaohongshu_scraper/.gitignore:1)
- Ignored Python caches, local env files, `session/`, `data/`, Playwright artifacts, and `tests/.tmp/`
- Ran `git rm --cached -f -r --ignore-unmatch __pycache__ scraper/__pycache__ tests/__pycache__ data session` to remove generated/sensitive files from the Git index without deleting local files

### Verification

- `git ls-files session data __pycache__ scraper/__pycache__ tests/__pycache__` now returns no tracked files
- `git check-ignore -v` confirms `session/storage_state.json`, `data/history.sqlite3`, exported CSV files, and `scraper/__pycache__` files are ignored

### Improvement review

- Version-control hygiene is now acceptable for continuing the product work
- The working tree still has many source/doc changes from previous cycles; those should be reviewed before any commit

## Cycle 17

### Read

- Ran `python main.py --help`
- Ran `python main.py search --help`
- Ran `python main.py batch --help`
- Re-read CLI argument construction in [main.py](/d:/xiaohongshu_scraper/main.py:1)

### Planned work

- Fix misleading help text for paired boolean flags
- Preserve existing CLI names such as `--headed/--headless`, `--resume/--fresh-run`, and `--with-comments/--no-comments`
- Add regression coverage for parser behavior and help text

### Problems summarized

- `argparse.ArgumentDefaultsHelpFormatter` displayed misleading defaults for paired flags
- Example: both `--headed` and `--headless` appeared with `default: True`
- This could make users choose unsafe or unintended run modes

### Modifications

- Added `_add_boolean_pair(...)` helper in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Converted paired boolean flags into mutually exclusive groups with `default=argparse.SUPPRESS`
- Added [tests/test_cli.py](/d:/xiaohongshu_scraper/tests/test_cli.py:1)
- Updated [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Verification

- Ran `python -m unittest discover -s tests`: 40 tests passed
- Ran `python main.py search --help`: boolean pairs now render without misleading paired defaults

### Improvement review

- CLI usage is now clearer and safer for small live validations
- The next live expansion should still require deliberate user approval because it touches the account/session

## Cycle 18

### Read

- Planned a one-run live validation with no fresh search and no forced detail
- Re-read comment resume logic in [main.py](/d:/xiaohongshu_scraper/main.py:1), [scraper/comments.py](/d:/xiaohongshu_scraper/scraper/comments.py:1), and [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)
- Dry-ran checkpoint selection against local checkpoints before live access

### Planned work

- Avoid repeating comments already collected in a newer checkpoint when an older larger checkpoint is selected
- Validate only two notes and at most three first-level comments per note
- Use the live result to improve offline diagnostics instead of running repeated live retries

### Problems summarized

- `--resume --max-notes-total 2` selected an older 5-note checkpoint that did not include the newest 1-note comment results
- Without historical comment reuse, the crawler would reopen the first note comments unnecessarily
- After live validation, one note had `raw_detail_json/detail_processed` markers but no usable detail fields; the old reusable-detail definition was too broad

### Modifications

- Added `RunStorage.load_reusable_comment_history(...)` in [scraper/storage.py](/d:/xiaohongshu_scraper/scraper/storage.py:1)
- Added comment-history merge and per-note cap logic in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Updated [scraper/comments.py](/d:/xiaohongshu_scraper/scraper/comments.py:1) to skip notes that already have enough existing comments
- Tightened `note_has_reusable_detail(...)` in [scraper/models.py](/d:/xiaohongshu_scraper/scraper/models.py:1) so raw/detail markers alone do not skip future detail attempts
- Added `detail_incomplete_count` and `detail_incomplete_note_ids` to [scraper/quality.py](/d:/xiaohongshu_scraper/scraper/quality.py:1)
- Extended tests in [tests/test_storage.py](/d:/xiaohongshu_scraper/tests/test_storage.py:1), [tests/test_resume_safety.py](/d:/xiaohongshu_scraper/tests/test_resume_safety.py:1), and [tests/test_history_quality_batch.py](/d:/xiaohongshu_scraper/tests/test_history_quality_batch.py:1)
- Updated [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Live verification

- Ran one approved live command:
  `python main.py search "哈尔滨 旅游" --resume --pages 1 --max-notes-total 2 --headed --detail --with-comments --max-comments-per-note 3 --no-replies --save-raw-json --debug --detail-delay-min 8 --detail-delay-max 12 --comment-delay-min 10 --comment-delay-max 15`
- Search replay was skipped
- Both detail pages were skipped by the pre-fix reusable-detail logic
- First note comments were skipped from history reuse
- Second note added 3 comments
- Final live result: `notes=2`, `comments=6`, `failures=0`

### Verification

- Ran `python -m unittest discover -s tests`: 44 tests passed
- Rebuilt quality report offline from `data/checkpoints/哈尔滨_旅游_20260426_230914_checkpoint.json`
- New report files:
  - `data/exports/哈尔滨_旅游_20260426_230914_reparsed_v2_quality_report.json`
  - `data/exports/哈尔滨_旅游_20260426_230914_reparsed_v2_quality_report.csv`
- The rebuilt report flags `detail_incomplete_note_ids=["698c2bd1000000000e00f2af"]`

### Improvement review

- Comment resume is now safer: newer checkpoint comments can be reused even when an older larger checkpoint is selected
- Future detail runs should no longer skip notes that only have raw/detail markers but no usable body/tags/IP/location fields
- Do not immediately rerun live for the incomplete detail note unless the user explicitly approves another validation

## Cycle 19

### Read

- Re-read [AGENTS.md](/d:/xiaohongshu_scraper/AGENTS.md:1) workflow requirements from the active session context
- Inspected [scraper/batch.py](/d:/xiaohongshu_scraper/scraper/batch.py:1), [scraper/detail_queue.py](/d:/xiaohongshu_scraper/scraper/detail_queue.py:1), [scraper/history_quality.py](/d:/xiaohongshu_scraper/scraper/history_quality.py:1), and CLI construction in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Used existing local checkpoints and history only; no Xiaohongshu live access was performed in this cycle

### Planned work

- Add a safe offline workflow planner before any further live expansion
- Generate review queues and recommended-only queues per keyword
- Produce explicit command manifests that separate offline commands from live commands requiring permission
- Preserve blocked detail failures instead of silently sending them back into retry files

### Problems summarized

- A direct live retry loop is unsafe when the recommended retry queue is empty and blocked rows exist
- Users needed one place to see what to run next, what is offline, and what requires account/session risk
- Windows PowerShell keyword files can include a UTF-8 BOM, which polluted planned keywords if not stripped
- Generated command text without BOM can display Chinese keywords incorrectly in older Windows PowerShell

### Modifications

- Added [scraper/workflow.py](/d:/xiaohongshu_scraper/scraper/workflow.py:1)
- Added `workflow-plan` CLI in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Updated [scraper/batch.py](/d:/xiaohongshu_scraper/scraper/batch.py:1) to strip UTF-8 BOM from keyword files
- Added [tests/test_workflow.py](/d:/xiaohongshu_scraper/tests/test_workflow.py:1) and [tests/test_batch.py](/d:/xiaohongshu_scraper/tests/test_batch.py:1)
- Extended [tests/test_cli.py](/d:/xiaohongshu_scraper/tests/test_cli.py:1)
- Updated [README.md](/d:/xiaohongshu_scraper/README.md:1) and [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Verification

- Ran `python -m unittest discover -s tests`: 74 tests passed
- Ran `python main.py workflow-plan data\batches\workflow_keywords_harbin.txt --max-notes-total 5 --output data\batches\workflow_harbin_plan`
- Verified generated files:
  - `data/batches/workflow_harbin_plan.csv`
  - `data/batches/workflow_harbin_plan.json`
  - `data/batches/workflow_harbin_plan_commands.txt`
  - `data/queues/workflow_harbin_plan_哈尔滨_旅游_review_detail_queue.csv`
  - `data/queues/workflow_harbin_plan_哈尔滨_旅游_recommended_detail_queue_note_ids.txt`
- Ran `python main.py history-quality --keyword "哈尔滨 旅游" --limit 20 --output data\exports\workflow_harbin_plan_哈尔滨_旅游_history_quality.csv`

### Result

- Current workflow plan for `哈尔滨 旅游` reports `queue_total_count=1`, `retry_recommended_count=0`, `blocked_count=1`, `recommended_next_action=review_blocked_detail_queue`
- The recommended note-id file is intentionally empty, so an automatic detail rerun would do zero notes instead of accidentally retrying blocked content

### Improvement review

- The next live action should not be another detail retry for the blocked note
- If the goal is more usable data, the next permissioned step should be a conservative fresh search-only run for new notes, followed by offline queue and quality review

## Cycle 20

### Read

- Reviewed `data/exports/哈尔滨_旅游_20260427_115640_notes.csv`
- Inspected saved raw files under `data/raw/哈尔滨_旅游_20260427_115640/`
- Re-read DOM fallback parsing in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1)

### Planned work

- Fix DOM fallback parsing without another live request
- Prevent parent/child DOM nodes from duplicating body text
- Keep inline hashtags in `tags` while removing them from `content`
- Stop comment/engagement UI text from entering `content`
- Add an offline reparse command so parser fixes can be applied to saved raw DOM snapshots

### Problems summarized

- `content` could contain repeated copies of the same body text from parent and child DOM nodes
- `content` could include `点击评论` / `说点什么...` UI text when a note had no body
- `location` could incorrectly become `击评论` because `荒地点击评论` accidentally matched the `地点` label pattern
- Existing exports could not be corrected without either one-off scripts or another live run

### Modifications

- Updated DOM fallback cleaning in [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1)
- Added offline reparse support in [scraper/reparse.py](/d:/xiaohongshu_scraper/scraper/reparse.py:1)
- Added `reparse-detail-dom` CLI in [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Updated [scraper/quality.py](/d:/xiaohongshu_scraper/scraper/quality.py:1) so no-comment runs do not get low comment-field warnings
- Added regression tests in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1), [tests/test_reparse.py](/d:/xiaohongshu_scraper/tests/test_reparse.py:1), and [tests/test_cli.py](/d:/xiaohongshu_scraper/tests/test_cli.py:1)
- Updated [README.md](/d:/xiaohongshu_scraper/README.md:1) and [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Verification

- Ran `python -m unittest discover -s tests`: 79 tests passed
- Ran `python main.py reparse-detail-dom --checkpoint data\checkpoints\哈尔滨_旅游_20260427_115640_checkpoint.json --detail-dom data\raw\哈尔滨_旅游_20260427_115640\detail_dom.jsonl --output data\exports\哈尔滨_旅游_20260427_115640_reparsed_v2`
- Generated:
  - `data/exports/哈尔滨_旅游_20260427_115640_reparsed_v2_notes.csv`
  - `data/exports/哈尔滨_旅游_20260427_115640_reparsed_v2_failed_records.csv`
  - `data/exports/哈尔滨_旅游_20260427_115640_reparsed_v2_quality_report.json`
  - `data/exports/哈尔滨_旅游_20260427_115640_reparsed_v2_quality_report.csv`

### Result

- Reparsed detail result has 4 notes and 4 reparsed detail snapshots
- `content` no longer contains repeated body copies
- `点击评论` / `说点什么...` no longer enters `content`
- False `location=击评论` is removed
- One note remains with empty `content` but valid tags; saved DOM showed tags/title and no independent body, so the conservative empty content is expected
- No-comment runs no longer report low comment-field warnings when comments were not collected

### Improvement review

- Future parser fixes can now be applied offline through `reparse-detail-dom`
- The next optional live step should be comments collection only if the user wants comment data; otherwise current note/detail workflow is usable for small controlled batches

## Cycle 21

### Read

- Ran one approved comments validation against the 4 recommended detail note ids
- Reviewed `data/exports/哈尔滨_旅游_20260427_121420_comments.csv`
- Reviewed `data/exports/哈尔滨_旅游_20260427_121420_quality_report.json`
- Compared comments-run notes export against the previously repaired detail DOM export

### Planned work

- Validate small-scale comment collection
- Confirm comments do not have field-shift or content pollution
- Preserve cleaned note detail fields after a later comments run
- Make future resume runs use clean data instead of polluted older checkpoint fields

### Problems summarized

- Comment collection worked, but the comments run reused an older checkpoint containing pre-fix duplicated note content
- The raw comments data was good, but the notes CSV from that run needed offline reparse cleanup
- `reparse-detail-dom` originally wrote clean CSVs only; future `--resume` could still pick the older polluted checkpoint

### Modifications

- Extended [scraper/reparse.py](/d:/xiaohongshu_scraper/scraper/reparse.py:1) to write a clean checkpoint
- Extended `reparse-detail-dom` in [main.py](/d:/xiaohongshu_scraper/main.py:1) with `--checkpoint-output`
- Updated [tests/test_reparse.py](/d:/xiaohongshu_scraper/tests/test_reparse.py:1) and [tests/test_cli.py](/d:/xiaohongshu_scraper/tests/test_cli.py:1)
- Updated [README.md](/d:/xiaohongshu_scraper/README.md:1) and [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Live verification

- Ran one approved command:
  `python main.py search "哈尔滨 旅游" --resume --pages 1 --max-notes-total 4 --headed --detail --with-comments --max-comments-per-note 3 --no-replies --note-ids-file "data\queues\workflow_harbin_plan_after_search_哈尔滨_旅游_recommended_detail_queue_note_ids.txt" --save-raw-json --debug --detail-delay-min 10 --detail-delay-max 15 --comment-delay-min 10 --comment-delay-max 15`
- Search replay was skipped
- Detail was not forced
- Comments result: `notes=4`, `comments=9`, `failures=0`

### Offline verification

- Ran `python -m unittest discover -s tests`: 79 tests passed
- Ran `python main.py reparse-detail-dom --checkpoint data\checkpoints\哈尔滨_旅游_20260427_121420_checkpoint.json --detail-dom data\raw\哈尔滨_旅游_20260427_115640\detail_dom.jsonl --output data\exports\哈尔滨_旅游_20260427_121420_reparsed_v2`
- Generated clean checkpoint:
  - `data/checkpoints/哈尔滨_旅游_20260427_121420_reparsed_v2_checkpoint.json`
- Generated clean exports:
  - `data/exports/哈尔滨_旅游_20260427_121420_reparsed_v2_notes.csv`
  - `data/exports/哈尔滨_旅游_20260427_121420_reparsed_v2_comments.csv`
  - `data/exports/哈尔滨_旅游_20260427_121420_reparsed_v2_quality_report.json`
- Ran workflow plan after clean checkpoint; result selected the clean checkpoint and reported no pending detail retry

### Result

- Final clean small sample has 4 notes, 9 first-level comments, and 0 failures
- Comment fields have full coverage in the quality report
- Clean notes preserve deduped content and tags from the repaired DOM parser
- Future resume runs should now prefer the clean reparsed checkpoint

### Improvement review

- Current small-batch note/detail/comment pipeline is usable for controlled expansion
- Next scale-up should still use `workflow-plan` first, then run live commands only when the recommended queue is explicit and small

## Cycle 22

### Read

- Reviewed current `best-export` implementation, CLI wiring, and tests
- Generated an initial merged export and found old polluted history rows entering the final table
- Inspected the latest 10-note search checkpoint and local quality reports

### Planned work

- Make merged exports use a stable row set from the latest suitable checkpoint
- Merge only matching note ids from history/checkpoints
- Prevent old invalid note ids, search suggestions, comments-as-content, duplicated body text, and body-text-in-tags from polluting the final table
- Keep the command fully offline and reproducible

### Problems summarized

- The first merge used all history/checkpoint rows for the query and could include old invalid rows such as search suggestions
- Historical comments could be selected as note `content`
- One old DOM fallback had stored `值得N刷的宝藏出游地` as a tag instead of body content

### Modifications

- Added anchor-checkpoint based merging in [scraper/best_export.py](/d:/xiaohongshu_scraper/scraper/best_export.py:1)
- Added best-export note/comment filtering for valid web note ids only
- Added content cleanup for comment-text pollution, inline hashtags, repeated DOM text, and body text misclassified as tags
- Extended CLI output in [main.py](/d:/xiaohongshu_scraper/main.py:1) with anchor checkpoint metadata
- Added regression coverage in [tests/test_best_export.py](/d:/xiaohongshu_scraper/tests/test_best_export.py:1)
- Documented usage in [README.md](/d:/xiaohongshu_scraper/README.md:1) and [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Offline verification

- Ran `python -m unittest tests.test_best_export tests.test_cli`: 10 tests passed
- Ran `python -m unittest discover -s tests`: 87 tests passed
- Ran `python main.py best-export "哈尔滨 旅游" --max-notes 10 --output data\exports\哈尔滨_旅游_best_merged_v3`

### Result

- Generated:
  - `data/exports/哈尔滨_旅游_best_merged_v3_notes.csv`
  - `data/exports/哈尔滨_旅游_best_merged_v3_comments.csv`
  - `data/exports/哈尔滨_旅游_best_merged_v3_failed_records.csv`
  - `data/exports/哈尔滨_旅游_best_merged_v3_quality_report.json`
  - `data/exports/哈尔滨_旅游_best_merged_v3_quality_report.csv`
  - `data/exports/哈尔滨_旅游_best_merged_v3_merge_report.json`
- Merge anchored to `data/checkpoints/哈尔滨_旅游_20260427_195842_checkpoint.json`
- Output has 10 anchored notes, 8 deduped comments, and 0 failure rows
- `69d8b420000000001d01e29c` now has `content=值得N刷的宝藏出游地` and the correct hashtag list
- Four notes still have incomplete detail fields because local history has no usable successful detail snapshot for them

### Improvement review

- The merged table is now the preferred offline view for reviewing accumulated local data quality
- Remaining detail gaps should be handled with `detail-queue` and small explicit live retries, not by inventing fields in the merge layer

## Cycle 23

### Read

- Reviewed `data/exports/哈尔滨_旅游_best_merged_v3_notes.csv`
- Inspected saved `detail_dom.jsonl` snapshots for `69d8b420000000001d01e29c`, `69ee0ffa00000000360313f4`, `69d73c6f000000001a0366a2`, and `69ee1ac6000000003701ea82`
- Re-read DOM metadata parsing and best-export field merge rules

### Planned work

- Verify whether `值得N刷的宝藏出游地` is body content or a hashtag
- Improve IP-location extraction for edited relative-date metadata visible in saved DOM snapshots
- Remove stale location pollution such as `击评论`
- Regenerate the best merged export offline without new live traffic

### Problems summarized

- Structured DOM evidence showed `#值得N刷的宝藏出游地` was an anchor tag, not body content, so the previous best-export cleanup was too aggressive
- DOM metadata such as `编辑于 昨天 22:04 黑龙江` and `编辑于 2天前 黑龙江` was visible but not parsed into `ip_location`
- Old polluted `location=击评论` could survive field-level merging

### Modifications

- Removed tag-to-content promotion from [scraper/best_export.py](/d:/xiaohongshu_scraper/scraper/best_export.py:1)
- Added location/IP cleanup in best-export merging
- Extended [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1) to parse edited relative-date metadata with trailing location
- Added regression tests in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1) and [tests/test_best_export.py](/d:/xiaohongshu_scraper/tests/test_best_export.py:1)
- Updated [docs/VERIFICATION.md](/d:/xiaohongshu_scraper/docs/VERIFICATION.md:1)

### Offline verification

- Ran `python -m unittest tests.test_detail_dom_fallback tests.test_best_export tests.test_cli`: 22 tests passed
- Ran `python -m unittest discover -s tests`: 89 tests passed
- Reparsed saved DOM snapshots:
  - `data/exports/哈尔滨_旅游_20260427_115640_reparsed_v3_notes.csv`
  - `data/exports/哈尔滨_旅游_20260427_200022_reparsed_v3_notes.csv`
  - `data/exports/哈尔滨_旅游_20260427_201558_reparsed_v3_notes.csv`
- Ran `python main.py best-export "哈尔滨 旅游" --max-notes 10 --output data\exports\哈尔滨_旅游_best_merged_v4`

### Result

- Generated:
  - `data/exports/哈尔滨_旅游_best_merged_v4_notes.csv`
  - `data/exports/哈尔滨_旅游_best_merged_v4_comments.csv`
  - `data/exports/哈尔滨_旅游_best_merged_v4_quality_report.json`
- `69d8b420000000001d01e29c` now correctly keeps `值得N刷的宝藏出游地` in `tags` and leaves `content` empty
- `ip_location` coverage improved from 3/10 to 6/10
- `location=击评论` was removed

### Improvement review

- The remaining 4 missing IP/detail rows do not have usable local target detail evidence; filling them requires a small explicit live detail retry or should remain blank

## Cycle 24

### Read

- Reviewed the current detail runtime path, CLI wiring, `workflow-plan`, and regression tests
- Confirmed that slow or incomplete detail-page rendering can produce empty snapshots or incomplete local evidence
- Kept the work offline; no Xiaohongshu page was opened during this cycle

### Planned work

- Record the render-wait speed bottleneck as a later speed optimization item
- Strengthen detail stability before speed tuning
- Keep all new behavior configurable from `search`, `batch`, and `workflow-plan`
- Add regression tests so empty snapshots, incomplete detail, and wrong-target detail pages remain distinguishable

### Problems summarized

- Slow rendering can make正文、IP、tags、comment area unavailable at the moment the parser runs
- Treating empty snapshots and incomplete detail as the same failure makes retry queues less precise
- Reopening details blindly can accidentally merge non-target content if the browser lands on another note
- Longer waits improve stability but can slow the crawler, so speed optimization must be handled separately after quality is stable

### Modifications

- Added configurable detail stability knobs in [scraper/config.py](/d:/xiaohongshu_scraper/scraper/config.py:1) and [main.py](/d:/xiaohongshu_scraper/main.py:1)
- Added `--detail-timeout`, `--detail-render-wait`, `--detail-empty-retries`, and `--detail-empty-retry-wait` to `search`, `batch`, and `workflow-plan`
- Updated [scraper/detail.py](/d:/xiaohongshu_scraper/scraper/detail.py:1) with target-page validation, render waiting, multi-stage DOM probes, empty-snapshot retry, and finer failure classification
- Updated [scraper/workflow.py](/d:/xiaohongshu_scraper/scraper/workflow.py:1) so generated live detail rerun commands use conservative stability parameters
- Added regression coverage in [tests/test_detail_success_policy.py](/d:/xiaohongshu_scraper/tests/test_detail_success_policy.py:1), [tests/test_cli.py](/d:/xiaohongshu_scraper/tests/test_cli.py:1), and [tests/test_workflow.py](/d:/xiaohongshu_scraper/tests/test_workflow.py:1)
- Documented the stability parameters and speed optimization backlog in [README.md](/d:/xiaohongshu_scraper/README.md:1)
- Updated [SAFE_RUN.md](/d:/xiaohongshu_scraper/SAFE_RUN.md:1) with conservative detail retry commands and explicit no-bypass operating rules

### Offline verification

- Ran `python -m unittest tests.test_detail_success_policy tests.test_cli tests.test_workflow`: 18 tests passed
- Ran `python -m unittest discover -s tests`: 94 tests passed
- Ran `python main.py search --help`, `python main.py batch --help`, and `python main.py workflow-plan --help`

### Result

- Detail empty snapshots now receive limited retry instead of being treated like parser failure
- Detail pages that only yield non-reusable fields still become explicit incomplete-detail failures
- Wrong-target detail pages fail explicitly before merging data
- Future workflow plans now generate safer detail retry commands with explicit stability waits

### Improvement review

- Next verification should run the full offline suite before live testing
- Later speed work should optimize adaptive waits and evidence-based early exit, not weaken the current correctness checks

## Cycle 25

### Read

- Reviewed the live retry interruption and the account-freeze screenshots
- Checked runtime interruption detection in [scraper/runtime_safety.py](/d:/xiaohongshu_scraper/scraper/runtime_safety.py:1)
- Checked login/session behavior in [scraper/auth.py](/d:/xiaohongshu_scraper/scraper/auth.py:1)

### Planned work

- Add a hard stop for account freeze and violation pages
- Keep account switching manual and explicit
- Avoid reusing the old persistent browser profile when a different personal account is used

### Problems summarized

- The previous live retry was interrupted by an account-freeze UI
- The runtime safety detector recognized login, CAPTCHA, verification, and abnormal access, but did not explicitly recognize account-freeze or violation pages
- Default persistent profile reuse can reopen the old account state unless the user intentionally uses an ephemeral login/context

### Modifications

- Added account-freeze and account-violation selectors to [scraper/runtime_safety.py](/d:/xiaohongshu_scraper/scraper/runtime_safety.py:1)
- Added regression tests in [tests/test_runtime_safety.py](/d:/xiaohongshu_scraper/tests/test_runtime_safety.py:1)
- Updated [SAFE_RUN.md](/d:/xiaohongshu_scraper/SAFE_RUN.md:1) with `login --ephemeral-context` and `--ephemeral-context` guidance for manual account switching

### Offline verification

- Ran `python -m unittest tests.test_runtime_safety tests.test_detail_success_policy`: 9 tests passed
- Ran `git diff --check`: no whitespace errors; only Windows line-ending warnings

### Result

- Future runs should stop when account-freeze or violation UI is visible instead of continuing into search/detail/comment stages
- New-account testing should use manual `--ephemeral-context` login and matching `--ephemeral-context` live commands to avoid carrying over the old browser profile

### Improvement review

- Before any further live retry, the user should manually log in with `python main.py login --ephemeral-context`
- The next live retry should be a minimal search-only smoke test before any detail retry

## Cycle 26

### Read

- Ran a minimal live search-only smoke test with the newly logged-in `--ephemeral-context` session
- Ran a one-note detail retry with conservative waits
- Reviewed the exported notes CSV, quality reports, and saved `detail_dom.jsonl`

### Planned work

- Verify that the new session can complete a tiny live search without account interruption
- Verify that one detail page can recover content, publish time, IP location, and tags
- Fix any parser pollution found from the saved raw DOM before doing more live traffic

### Problems summarized

- Search-only smoke test succeeded and collected card fields, but detail-only fields remained empty as expected
- One-note detail retry recovered usable detail fields
- The first detail DOM parse included a `猜你想搜` recommendation widget in `content`

### Modifications

- Updated [scraper/parser.py](/d:/xiaohongshu_scraper/scraper/parser.py:1) to skip `xhs-capsule-widget` / recommendation nodes and visible-text `猜你想搜` lines
- Added regression coverage in [tests/test_detail_dom_fallback.py](/d:/xiaohongshu_scraper/tests/test_detail_dom_fallback.py:1)
- Reparsed the saved live DOM offline instead of revisiting the page

### Live verification

- Ran `python main.py search "哈尔滨 旅游" --fresh-run --pages 1 --max-notes-total 3 --headed --ephemeral-context --no-detail --no-comments --save-raw-json --debug --search-delay-min 8 --search-delay-max 12`
- Result: 3 notes, 0 comments, 0 failures
- Ran `python main.py search "哈尔滨 旅游" --resume --force-detail --pages 1 --max-notes-total 1 --headed --ephemeral-context --detail --no-comments --save-raw-json --debug --detail-delay-min 15 --detail-delay-max 20 --detail-timeout 20 --detail-render-wait 8 --detail-empty-retries 1 --detail-empty-retry-wait 10`
- Result: 1 note, 0 comments, 0 failures; detail recovered from rendered DOM text

### Offline verification

- Ran `python -m unittest tests.test_detail_dom_fallback`: 14 tests passed
- Ran `python main.py reparse-detail-dom --checkpoint data\checkpoints\哈尔滨_旅游_20260428_155255_checkpoint.json --detail-dom data\raw\哈尔滨_旅游_20260428_155255\detail_dom.jsonl --output data\exports\哈尔滨_旅游_20260428_155255_reparsed`
- Ran `git diff --check`: no whitespace errors; only Windows line-ending warnings

### Result

- Clean detail output:
  - `data/exports/哈尔滨_旅游_20260428_155255_reparsed_notes.csv`
  - `data/exports/哈尔滨_旅游_20260428_155255_reparsed_quality_report.json`
- The repaired one-note detail output has `content`, `publish_time`, `ip_location`, and `tags`
- `猜你想搜` recommendation text is no longer included in `content`

### Improvement review

- Next live step, if explicitly approved, should be one-note comments only with `--max-comments-per-note 2 --no-replies`
- Do not expand to multi-note detail/comment runs until the one-note comment path is inspected

## Cycle 27

### Read

- Reviewed `scraper/parser.py`, `scraper/models.py`, `scraper/history.py`, `scraper/quality.py`, and existing parser/export tests
- Reused local raw files only; no Xiaohongshu live access was performed in this cycle

### Planned work

- Remove the fixed 12-line detail content cap so full visible note body is kept until a clear boundary
- Extend comment records for sentiment analysis without losing raw evidence
- Keep SQLite history, best export, dedupe, and quality reports compatible with the new comment fields

### Problems summarized

- Detail visible-text recovery stopped after 12 lines even when no tag/comment boundary had been reached
- Comment exports lacked direct reply target id, author-comment marker, and NLP-clean comment text
- Real comment raw payloads can contain nested `sub_comments`; these need to be flattened only when replies are explicitly requested

### Modifications

- Updated `scraper/parser.py` to keep full body text until tag/recommendation/metadata/comment boundaries
- Updated `scraper/parser.py` to flatten nested replies when `include_replies=True`
- Added `reply_to_comment_id`, `reply_to_user_id`, `is_author_comment`, and `comment_content_clean` to `CommentRecord`
- Updated SQLite history schema migration, history export, best export, dedupe scoring, and quality report coverage for the new fields
- Added parser regression tests for long detail body extraction and nested comment reply parsing
- Documented comment sentiment fields in `README.md`

### Offline verification

- Ran `python -m unittest tests.test_parser tests.test_detail_dom_fallback`: 21 tests passed
- Ran `python -m unittest tests.test_storage tests.test_history_export tests.test_best_export tests.test_dedupe tests.test_history_quality_batch`: 20 tests passed
- Ran `python -m unittest tests.test_exporter tests.test_resume_safety`: 20 tests passed
- Ran `python -m unittest discover -s tests`: 102 tests passed
- Ran `python main.py reparse-detail-dom --checkpoint data\checkpoints\哈尔滨_旅游_20260428_161505_checkpoint.json --detail-dom data\raw\哈尔滨_旅游_20260428_161505\detail_dom.jsonl --output data\exports\哈尔滨_旅游_20260428_161505_fullbody_reparsed`: 1 note reparsed
- Parsed local `data/raw/哈尔滨_旅游_20260428_162033/comments.jsonl` with `include_replies=True`: 20 comments/replies parsed from the first saved payload

### Result

- Future detail DOM reparses no longer truncate body text by line count
- Future comment exports include cleaner sentiment-analysis fields while preserving original `comment_content`
- Reply relationship fields are available for conversation-tree analysis

### Improvement review

- Next step should be a small live validation with `--include-replies` and a conservative `--max-comments-per-note`
- Speed optimization should wait until the full-body and comment-reply outputs are inspected

## Cycle 28

### Read

- Ran a small live validation for query `25考研 经验`
- Inspected the saved `detail_dom.jsonl`, notes CSV, comments CSV, and quality report
- Compared the initial exported body against the rendered DOM text from the saved raw snapshot

### Planned work

- Validate one fresh note with detail and public comments including replies
- Fix parser regressions offline instead of revisiting the page
- Keep the raw `comment_content` while adding cleaner relationship fields for sentiment analysis
- Add regression coverage for any parsing issue found in the live sample

### Problems summarized

- The first detail export truncated the full note body because visible text parsing stopped too early
- A normal body line containing `分享` was treated as an engagement boundary
- A normal body line containing `刚刚` was treated as a possible metadata line

### Modifications

- Updated `scraper/parser.py` so visible detail text only stops on exact engagement/comment boundaries
- Updated `scraper/parser.py` so publish time extraction only accepts date/relative-time tokens at the start of a metadata line, after optional `编辑于`
- Added a regression test in `tests/test_detail_dom_fallback.py` covering body lines that contain `分享` and `刚刚`
- Reparsed the saved `25考研 经验` DOM offline into a corrected full-body export

### Live verification

- Ran search-only for `25考研 经验`: 3 notes, 0 failures
- Ran one-note detail plus comments with `--include-replies`: 1 note, 17 comments/replies, 0 failures

### Offline verification

- Ran `python main.py reparse-detail-dom --checkpoint data\checkpoints\25考研_经验_20260428_164753_checkpoint.json --detail-dom data\raw\25考研_经验_20260428_164753\detail_dom.jsonl --output data\exports\25考研_经验_20260428_164753_fullbody_v2`
- Ran `python -m unittest tests.test_detail_dom_fallback tests.test_parser`: 23 tests passed
- Ran `python -m unittest tests.test_exporter tests.test_storage tests.test_history_export`: 12 tests passed
- Ran `python -m unittest discover -s tests`: 104 tests passed
- Ran `git diff --check`: no whitespace errors; only Windows line-ending warnings

### Result

- Corrected note output: `data/exports/25考研_经验_20260428_164753_fullbody_v2_notes.csv`
- Corrected comments output: `data/exports/25考研_经验_20260428_164753_fullbody_v2_comments.csv`
- Corrected quality report: `data/exports/25考研_经验_20260428_164753_fullbody_v2_quality_report.json`
- The corrected note body length is 719 characters with `publish_time=2026-04-16`, `ip_location=河北`, and 10 tags
- The comments output has 10 first-level comments and 7 second-level replies; reply relationship fields are filled for all 7 replies

### Improvement review

- `location` remains blank when the note has no official POI field; `ip_location` is the available location signal for this sample
- `view_count` remains blank because the captured public data did not expose a view count
- Next step should be comment pagination/depth validation before speed optimization

## Cycle 29

### Read

- Ran a low-frequency live validation on the existing `25考研 经验` checkpoint and selected note `69e091bd00000000230050a1`
- Reviewed comment CSV, quality report, saved comment raw payloads, and debug logs
- Checked whether increasing `--max-comments-per-note` could collect beyond the prior 17-comment sample

### Planned work

- Validate comment pagination without replaying search or reprocessing detail
- Fix resume behavior if old comment checkpoints prevent a higher comment cap from running
- Improve rendered-page scrolling before considering any direct API strategy
- Prevent URL query tokens from being written to debug logs or failure `page_url`

### Problems summarized

- A resume run with `--max-comments-per-note 50` reused 17 comments but skipped the selected note because `last_comment_note_id` marked it complete under an older, lower cap
- Plain page-wheel scrolling could still hit duplicate comment payloads and fail to trigger additional pages
- Debug logs could print full response URLs containing `xsec_token`

### Modifications

- Updated `main.py` so `last_comment_note_id` is cleared when existing comments for that note are below the newly requested `--max-comments-per-note`
- Updated `scraper/comments.py` to use bounded multi-round comment scrolling and to prefer the rendered comment container before falling back to page-wheel scrolling
- Added resume/comment scrolling regression tests in `tests/test_resume_safety.py`
- Added `redact_url` in `scraper/utils.py` and used it for response debug logs and failure artifact `page_url`
- Added URL redaction coverage in `tests/test_utils.py`
- Documented larger comment samples in `README.md`
- Redacted historical `data/logs/*.log` occurrences of `xsec_token`

### Live verification

- First retry after resume fix: comments increased from 17 to 24, 0 failures
- Retry before comment-container scrolling: no new comments beyond 24; raw payload still had `has_more=True`
- Final retry after comment-container scrolling: comments increased from 24 to 50, 0 failures

### Offline verification

- Ran `python -m unittest tests.test_resume_safety`: 22 tests passed
- Ran `python -m unittest tests.test_parser tests.test_detail_dom_fallback`: 23 tests passed
- Ran `python -m unittest tests.test_utils tests.test_resume_safety`: 23 tests passed
- Ran `python -m unittest discover -s tests`: 108 tests passed
- Ran `git diff --check`: no whitespace errors; only Windows line-ending warnings

### Result

- Final verified note output: `data/exports/25考研_经验_20260429_001211_notes.csv`
- Final verified comments output: `data/exports/25考研_经验_20260429_001211_comments.csv`
- Final quality report: `data/exports/25考研_经验_20260429_001211_quality_report.json`
- The final comments output has 50 unique comments/replies: 29 first-level comments and 21 second-level replies
- `comment_content_clean`, commenter fields, time, like count, IP location, and ids are filled for all 50 rows
- Reply relationship fields are filled for all 21 second-level replies

### Improvement review

- The bounded UI-scroll approach is stable for sampled public comments and avoids direct internal API requests
- For very large-scale sentiment datasets, future work should add an explicit comments-only command and a run-level comment pagination report before speed optimization
