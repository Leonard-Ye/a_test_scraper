import argparse
import csv
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from playwright.sync_api import sync_playwright

from scraper.auth import create_authenticated_context, interactive_login
from scraper.batch import load_keywords_file, write_batch_report
from scraper.best_export import export_best_records
from scraper.comments import CommentCollector, should_reuse_existing_comments
from scraper.comment_filters import filter_comments_for_options, level_counts_by_note, normalize_comment_ids
from scraper.comment_queue import COMMENT_QUEUE_SORT_OPTIONS, build_comment_queue, write_comment_queue
from scraper.config import (
    AppPaths,
    CrawlOptions,
    DEFAULT_DETAIL_EMPTY_RETRY_WAIT_MS,
    DEFAULT_DETAIL_RENDER_WAIT_MS,
    DEFAULT_DETAIL_WAIT_TIMEOUT_MS,
    MAX_DETAIL_EMPTY_RETRIES,
    RATE_PROFILE_NAMES,
    get_rate_profile,
)
from scraper.dedupe import dedupe_comments, dedupe_notes
from scraper.detail import DetailCollector
from scraper.detail_queue import build_detail_queue, load_note_ids_file, parse_note_ids, write_detail_queue
from scraper.history import HistoryStore
from scraper.history_export import export_history_records
from scraper.history_quality import export_history_quality_summary
from scraper.logger import configure_logging
from scraper.models import (
    CommentRecord,
    FailedRecord,
    NoteRecord,
    note_content_is_tag_only,
    note_has_detail_enrichment,
    note_has_reusable_detail,
)
from scraper.reparse import reparse_detail_dom_checkpoint
from scraper.runtime_profile import RuntimeStageProfile
from scraper.runtime_safety import looks_like_web_note_id, looks_like_web_note_url
from scraper.search import SearchCollector
from scraper.storage import RunStorage
from scraper.utils import json_dumps, slugify_filename
from scraper.workflow import WorkflowPlanOptions, create_safe_workflow_plan


RUN_DEFAULT_RATE_PROFILE = "standard"
RUN_DEFAULT_NOTES = 5
RUN_DEFAULT_FIRST_COMMENTS = 10
RUN_DEFAULT_SECOND_COMMENTS = 30
RUN_DEFAULT_MERGED_COMMENTS = False
RUN_DEFAULT_AUTO_BEST_EXPORT = False
RUN_DEFAULT_VERIFICATION_WAIT_SECONDS = 180
RUN_DEFAULT_SEARCH_KWARGS: dict[str, object] = {
    "pages": 1,
    "detail": True,
    "force_detail": False,
    "skip_enriched_detail": True,
    "with_comments": True,
    "include_replies": True,
    "expand_replies": True,
    "headed": True,
    "save_raw_json": True,
    "debug": True,
    "verification_wait_seconds": RUN_DEFAULT_VERIFICATION_WAIT_SECONDS,
}


def login(*, use_persistent_context: bool = True) -> None:
    """Open a visible browser for the first manual login and save storage_state."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    log_path = paths.logs_dir / "login.log"
    logger = configure_logging(log_path, debug=False)

    with sync_playwright() as playwright:
        interactive_login(
            playwright,
            paths,
            logger,
            use_persistent_context=use_persistent_context,
        )


def run_workflow(
    query: str,
    *,
    rate_profile: str = RUN_DEFAULT_RATE_PROFILE,
    dry_run: bool = False,
    notes: int = RUN_DEFAULT_NOTES,
    first_comments: int = RUN_DEFAULT_FIRST_COMMENTS,
    second_comments: int = RUN_DEFAULT_SECOND_COMMENTS,
    with_comments: bool = True,
    export_merged_comments: bool = RUN_DEFAULT_MERGED_COMMENTS,
    auto_best_export: bool = RUN_DEFAULT_AUTO_BEST_EXPORT,
    output: Optional[str] = None,
) -> None:
    """Preview the high-level run workflow configuration without live access."""
    profile = get_rate_profile(rate_profile)
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    search_kwargs = _build_run_search_kwargs(
        notes=notes,
        first_comments=first_comments,
        second_comments=second_comments,
        rate_profile=rate_profile,
        with_comments=with_comments,
        export_merged_comments=export_merged_comments,
        output=output,
    )
    search_argv = _build_run_search_argv(
        query,
        notes=notes,
        first_comments=first_comments,
        second_comments=second_comments,
        rate_profile=rate_profile,
        with_comments=with_comments,
        export_merged_comments=export_merged_comments,
        output=output,
    )
    startup_plan = _build_run_startup_plan(
        paths=paths,
        query=query,
        notes=notes,
        first_comments=first_comments,
        second_comments=second_comments,
        with_comments=with_comments,
    )
    best_export_kwargs = _build_run_best_export_kwargs(
        notes=notes,
        with_comments=with_comments,
        export_merged_comments=export_merged_comments,
        output=output,
    )
    best_export_argv = _build_run_best_export_argv(query, **best_export_kwargs)
    best_export_result = None
    if auto_best_export and not dry_run:
        result = export_best_records(
            paths=paths,
            query=query,
            output_base=Path(str(best_export_kwargs["output"])) if best_export_kwargs.get("output") else None,
            max_notes=int(best_export_kwargs["max_notes"]),
            include_comments=bool(best_export_kwargs["include_comments"]),
            include_merged_comments=bool(best_export_kwargs["include_merged_comments"]),
            export_format=str(best_export_kwargs["export_format"]),
        )
        best_export_result = _best_export_result_to_dict(result)
    summary = _build_run_summary(
        startup_plan=startup_plan,
        search_command="python main.py " + subprocess.list2cmdline(search_argv),
        best_export_command=(
            "python main.py " + subprocess.list2cmdline(best_export_argv)
            if auto_best_export
            else ""
        ),
        auto_best_export=auto_best_export,
        best_export_result=best_export_result,
    )
    print(
        json_dumps(
            {
                "command": "run",
                "dry_run": dry_run,
                "query": query,
                "rate_profile": profile.name,
                "delay_kwargs": profile.to_delay_kwargs(),
                "status": "offline_best_export_completed" if best_export_result is not None else "preview_only",
                "live_access": False,
                "auto_best_export": auto_best_export,
                "search_argv": search_argv,
                "search_kwargs": search_kwargs,
                "search_command": summary["recommended_search_command"],
                "best_export_argv": best_export_argv if auto_best_export else [],
                "best_export_kwargs": best_export_kwargs if auto_best_export else {},
                "best_export_command": summary["recommended_best_export_command"],
                "best_export_result": best_export_result,
                "summary": summary,
                "startup_plan": startup_plan,
                "reuse_preview": startup_plan,
                "reused_detail_count": startup_plan["reused_detail_count"],
                "reused_comment_count": startup_plan["reused_comment_count"],
                "live_required_notes": startup_plan["live_required_notes"],
            }
        )
    )


def _build_run_search_kwargs(
    *,
    notes: int,
    first_comments: int,
    second_comments: int,
    rate_profile: str,
    with_comments: bool = True,
    export_merged_comments: bool = RUN_DEFAULT_MERGED_COMMENTS,
    output: Optional[str] = None,
) -> dict[str, object]:
    delay_kwargs = get_rate_profile(rate_profile).to_delay_kwargs()
    search_kwargs = {
        **RUN_DEFAULT_SEARCH_KWARGS,
        "max_notes_total": notes,
        **delay_kwargs,
    }
    if output:
        search_kwargs["output"] = output
    if with_comments:
        search_kwargs.update(
            {
                "max_first_level_comments_per_note": first_comments,
                "max_second_level_comments_per_note": second_comments,
                "export_merged_comments": export_merged_comments,
            }
        )
        return search_kwargs

    search_kwargs.update(
        {
            "with_comments": False,
            "include_replies": False,
            "expand_replies": False,
            "export_merged_comments": False,
        }
    )
    search_kwargs.pop("comment_delay_min", None)
    search_kwargs.pop("comment_delay_max", None)
    return search_kwargs


def _build_run_search_argv(
    query: str,
    *,
    notes: int,
    first_comments: int,
    second_comments: int,
    rate_profile: str,
    with_comments: bool = True,
    export_merged_comments: bool = RUN_DEFAULT_MERGED_COMMENTS,
    output: Optional[str] = None,
) -> list[str]:
    search_kwargs = _build_run_search_kwargs(
        notes=notes,
        first_comments=first_comments,
        second_comments=second_comments,
        rate_profile=rate_profile,
        with_comments=with_comments,
        export_merged_comments=export_merged_comments,
        output=output,
    )
    argv = [
        "search",
        query,
        "--pages",
        str(search_kwargs["pages"]),
        "--max-notes-total",
        str(search_kwargs["max_notes_total"]),
        "--detail",
        "--skip-enriched-detail",
        "--headed",
        "--save-raw-json",
        "--debug",
        "--verification-wait",
        str(search_kwargs["verification_wait_seconds"]),
        "--search-delay-min",
        str(search_kwargs["search_delay_min"]),
        "--search-delay-max",
        str(search_kwargs["search_delay_max"]),
        "--detail-delay-min",
        str(search_kwargs["detail_delay_min"]),
        "--detail-delay-max",
        str(search_kwargs["detail_delay_max"]),
    ]
    if search_kwargs.get("output"):
        argv.extend(["--output", str(search_kwargs["output"])])
    if search_kwargs["with_comments"]:
        argv.extend(
            [
                "--with-comments",
                "--include-replies",
                "--expand-replies",
                "--max-first-level-comments-per-note",
                str(search_kwargs["max_first_level_comments_per_note"]),
                "--max-second-level-comments-per-note",
                str(search_kwargs["max_second_level_comments_per_note"]),
                "--comment-delay-min",
                str(search_kwargs["comment_delay_min"]),
                "--comment-delay-max",
                str(search_kwargs["comment_delay_max"]),
            ]
        )
        if search_kwargs["export_merged_comments"]:
            argv.append("--merged-comments")
    else:
        argv.append("--no-comments")
    return argv


def _build_run_summary(
    *,
    startup_plan: dict[str, object],
    search_command: str,
    best_export_command: str,
    auto_best_export: bool,
    best_export_result: dict[str, object] | None,
) -> dict[str, object]:
    best_export_outputs: list[str] = []
    if best_export_result is not None:
        best_export_outputs = list(best_export_result.get("outputs", []))  # type: ignore[arg-type]
    return {
        "checkpoint_found": startup_plan["checkpoint_found"],
        "search_required": startup_plan["search_required"],
        "candidate_note_count": startup_plan["candidate_note_count"],
        "reused_detail_count": startup_plan["reused_detail_count"],
        "reused_comment_count": startup_plan["reused_comment_count"],
        "detail_live_required_count": len(startup_plan["detail_live_required_note_ids"]),  # type: ignore[arg-type]
        "comment_live_required_count": len(startup_plan["comment_live_required_note_ids"]),  # type: ignore[arg-type]
        "live_required_note_count": startup_plan["live_required_note_count"],
        "offline_reusable_note_count": len(startup_plan["offline_reusable_note_ids"]),  # type: ignore[arg-type]
        "recommended_search_command": search_command,
        "auto_best_export": auto_best_export,
        "recommended_best_export_command": best_export_command,
        "best_export_completed": best_export_result is not None,
        "best_export_outputs": best_export_outputs,
    }


def _build_run_best_export_kwargs(
    *,
    notes: int,
    with_comments: bool,
    export_merged_comments: bool,
    output: Optional[str] = None,
) -> dict[str, object]:
    return {
        "output": output or "",
        "max_notes": notes,
        "include_comments": with_comments,
        "include_merged_comments": bool(with_comments and export_merged_comments),
        "export_format": "csv",
    }


def _build_run_best_export_argv(query: str, **kwargs: object) -> list[str]:
    argv = [
        "best-export",
        query,
        "--max-notes",
        str(kwargs["max_notes"]),
        "--format",
        str(kwargs["export_format"]),
    ]
    if kwargs.get("output"):
        argv.extend(["--output", str(kwargs["output"])])
    argv.append("--comments" if kwargs.get("include_comments") else "--no-comments")
    argv.append("--merged-comments" if kwargs.get("include_merged_comments") else "--no-merged-comments")
    return argv


def _best_export_result_to_dict(result: Any) -> dict[str, object]:
    return {
        "notes_count": result.notes_count,
        "comments_count": result.comments_count,
        "history_notes_count": result.history_notes_count,
        "checkpoint_notes_count": result.checkpoint_notes_count,
        "history_comments_count": result.history_comments_count,
        "checkpoint_comments_count": result.checkpoint_comments_count,
        "anchor_checkpoint": str(result.anchor_checkpoint or ""),
        "anchor_notes_count": result.anchor_notes_count,
        "outputs": [str(path) for path in result.output_paths],
    }


class _SilentLogger:
    def info(self, *_args: object, **_kwargs: object) -> None:
        pass

    def warning(self, *_args: object, **_kwargs: object) -> None:
        pass

    def debug(self, *_args: object, **_kwargs: object) -> None:
        pass


def _build_run_startup_plan(
    *,
    paths: AppPaths,
    query: str,
    notes: int,
    first_comments: int,
    second_comments: int,
    with_comments: bool,
) -> dict[str, object]:
    options = CrawlOptions(
        query=query,
        detail=True,
        with_comments=with_comments,
        include_replies=with_comments,
        expand_replies=with_comments,
        max_notes_total=notes,
        max_first_level_comments_per_note=first_comments if with_comments else None,
        max_second_level_comments_per_note=second_comments if with_comments else None,
    )
    checkpoint = RunStorage.load_latest_checkpoint(paths, query, min_notes=options.max_notes_total)
    if checkpoint is None or not checkpoint.notes:
        return {
            "checkpoint_found": False,
            "checkpoint_path": "",
            "candidate_note_count": 0,
            "search_required": True,
            "reused_detail_count": 0,
            "reused_comment_count": 0,
            "reused_detail_note_ids": [],
            "reused_comment_note_ids": [],
            "detail_required_note_ids": [],
            "detail_live_required_note_ids": [],
            "detail_skipped_note_ids": [],
            "comment_required_note_ids": [],
            "comment_live_required_note_ids": [],
            "comment_skipped_note_ids": [],
            "comment_collection_enabled": with_comments,
            "first_level_comment_target": first_comments if with_comments else None,
            "second_level_comment_target": second_comments if with_comments else None,
            "offline_reusable_note_ids": [],
            "force_detail": False,
            "skip_reusable_detail": True,
            "live_required_notes": [],
            "live_required_note_count": 0,
        }

    logger = _SilentLogger()
    prepared_notes = _prepare_notes_for_run(list(checkpoint.notes), logger, options, stage="run-dry-run")
    detail_history = RunStorage.load_reusable_detail_history(paths, query)
    _merge_reusable_detail_history(prepared_notes, detail_history, logger)

    comments: list[CommentRecord] = []
    if with_comments:
        comments = _dedupe_comments_with_log(checkpoint.comments, logger, stage="run-dry-run")
        historical_comments = RunStorage.load_reusable_comment_history(paths, query)
        comments = _merge_reusable_comment_history(
            comments,
            historical_comments,
            prepared_notes,
            logger,
            options,
        )

    comment_counts = _comment_counts_by_note(comments)
    level_counts = level_counts_by_note(comments)
    reused_detail_note_ids: list[str] = []
    reused_comment_note_ids: list[str] = []
    detail_required_note_ids: list[str] = []
    comment_required_note_ids: list[str] = []
    offline_reusable_note_ids: list[str] = []
    live_required_notes: list[str] = []
    for note in prepared_notes:
        detail_reused = note_has_reusable_detail(note)
        comment_reused = True
        if with_comments:
            comment_reused = should_reuse_existing_comments(
                note=note,
                options=options,
                existing_count=comment_counts.get(note.note_id, 0),
                level_counts=level_counts,
            )
        if detail_reused:
            reused_detail_note_ids.append(note.note_id)
        if with_comments and comment_reused:
            reused_comment_note_ids.append(note.note_id)
        if not detail_reused:
            detail_required_note_ids.append(note.note_id)
        if with_comments and not comment_reused:
            comment_required_note_ids.append(note.note_id)
        if detail_reused and comment_reused:
            offline_reusable_note_ids.append(note.note_id)
        else:
            live_required_notes.append(note.note_id)

    return {
        "checkpoint_found": True,
        "checkpoint_path": str(checkpoint.path),
        "candidate_note_count": len(prepared_notes),
        "search_required": len(prepared_notes) < notes,
        "reused_detail_count": len(reused_detail_note_ids),
        "reused_comment_count": len(reused_comment_note_ids),
        "reused_detail_note_ids": reused_detail_note_ids,
        "reused_comment_note_ids": reused_comment_note_ids,
        "detail_required_note_ids": detail_required_note_ids,
        "detail_live_required_note_ids": detail_required_note_ids,
        "detail_skipped_note_ids": reused_detail_note_ids,
        "comment_required_note_ids": comment_required_note_ids,
        "comment_live_required_note_ids": comment_required_note_ids,
        "comment_skipped_note_ids": reused_comment_note_ids,
        "comment_collection_enabled": with_comments,
        "first_level_comment_target": first_comments if with_comments else None,
        "second_level_comment_target": second_comments if with_comments else None,
        "offline_reusable_note_ids": offline_reusable_note_ids,
        "force_detail": False,
        "skip_reusable_detail": True,
        "live_required_notes": live_required_notes,
        "live_required_note_count": len(live_required_notes),
    }


def _build_run_reuse_preview(**kwargs: object) -> dict[str, object]:
    return _build_run_startup_plan(**kwargs)  # type: ignore[arg-type]


def _comment_counts_by_note(comments: Sequence[CommentRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for comment in comments:
        note_id = str(comment.note_id or "").strip()
        if not note_id:
            continue
        counts[note_id] = counts.get(note_id, 0) + 1
    return counts


def _log_done_output_paths(logger: Any, output_paths: Sequence[Path]) -> None:
    logger.info("[done] outputs: %s", ", ".join(str(path) for path in output_paths))


def search(
    query: str,
    *,
    pages: int = 1,
    export_format: str = "csv",
    export_merged_comments: bool = False,
    output: Optional[str] = None,
    detail: bool = False,
    search_delay_min: float = 4.0,
    search_delay_max: float = 7.0,
    detail_delay_min: float = 3.0,
    detail_delay_max: float = 5.0,
    detail_wait_timeout_ms: int = DEFAULT_DETAIL_WAIT_TIMEOUT_MS,
    detail_render_wait_ms: int = DEFAULT_DETAIL_RENDER_WAIT_MS,
    detail_empty_retries: int = MAX_DETAIL_EMPTY_RETRIES,
    detail_empty_retry_wait_ms: int = DEFAULT_DETAIL_EMPTY_RETRY_WAIT_MS,
    comment_delay_min: float = 4.0,
    comment_delay_max: float = 6.0,
    headed: bool = True,
    use_persistent_context: bool = True,
    debug: bool = False,
    save_raw_json: bool = False,
    max_items_per_page: Optional[int] = None,
    max_notes_total: Optional[int] = 10,
    with_comments: bool = False,
    max_comments_per_note: int = 50,
    include_replies: bool = False,
    expand_replies: bool = False,
    max_reply_expansions_per_note: int = 3,
    max_replies_per_comment: Optional[int] = None,
    max_first_level_comments_per_note: Optional[int] = None,
    max_second_level_comments_per_note: Optional[int] = None,
    root_comment_ids: Optional[str] = None,
    root_comment_ids_file: Optional[str] = None,
    comments_only: bool = False,
    resume: bool = True,
    force_detail: bool = False,
    skip_enriched_detail: bool = True,
    persist_history: bool = True,
    manual_verification: bool = True,
    verification_wait_seconds: int = 180,
    note_ids: Optional[str] = None,
    note_ids_file: Optional[str] = None,
) -> None:
    """Search Xiaohongshu and export normalized note data."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    selected_note_ids = _resolve_note_id_filter(note_ids=note_ids, note_ids_file=note_ids_file)
    note_id_filter_active = bool(note_ids) or bool(note_ids_file)
    selected_root_comment_ids = _resolve_comment_id_filter(
        comment_ids=root_comment_ids,
        comment_ids_file=root_comment_ids_file,
    )
    root_comment_id_filter_active = bool(root_comment_ids) or bool(root_comment_ids_file)
    options = CrawlOptions(
        query=query,
        pages=pages,
        export_format=export_format,
        export_merged_comments=export_merged_comments,
        output=Path(output) if output else None,
        detail=detail,
        headed=headed,
        use_persistent_context=use_persistent_context,
        debug=debug,
        save_raw_json=save_raw_json,
        max_items_per_page=max_items_per_page,
        max_notes_total=max_notes_total,
        with_comments=with_comments,
        comments_only=comments_only,
        max_comments_per_note=max_comments_per_note,
        include_replies=include_replies,
        expand_replies=expand_replies,
        max_reply_expansions_per_note=max_reply_expansions_per_note,
        max_replies_per_comment=max_replies_per_comment,
        max_first_level_comments_per_note=max_first_level_comments_per_note,
        max_second_level_comments_per_note=max_second_level_comments_per_note,
        root_comment_ids=selected_root_comment_ids,
        root_comment_id_filter_active=root_comment_id_filter_active,
        force_detail=force_detail,
        skip_enriched_detail=skip_enriched_detail,
        persist_history=persist_history,
        manual_verification=manual_verification,
        verification_wait_seconds=verification_wait_seconds,
        note_ids=selected_note_ids,
        note_id_filter_active=note_id_filter_active,
        search_delay_min=search_delay_min,
        search_delay_max=search_delay_max,
        detail_delay_min=detail_delay_min,
        detail_delay_max=detail_delay_max,
        detail_wait_timeout_ms=detail_wait_timeout_ms,
        detail_render_wait_ms=detail_render_wait_ms,
        detail_empty_retries=detail_empty_retries,
        detail_empty_retry_wait_ms=detail_empty_retry_wait_ms,
        comment_delay_min=comment_delay_min,
        comment_delay_max=comment_delay_max,
    )
    storage = RunStorage(paths, options)
    logger = configure_logging(storage.log_path, debug=debug)

    failed_records: list[FailedRecord] = []
    notes = []
    comments = []
    checkpoint = (
        RunStorage.load_latest_checkpoint(paths, query, min_notes=options.max_notes_total)
        if resume
        else None
    )
    last_completed_page = 0
    resume_detail_after = ""
    resume_comment_after = ""

    if checkpoint and checkpoint.notes:
        notes = _prepare_notes_for_run(checkpoint.notes, logger, options, stage="resume")
        if options.detail and not options.force_detail:
            detail_history = RunStorage.load_reusable_detail_history(paths, query)
            _merge_reusable_detail_history(notes, detail_history, logger)
        failed_records = checkpoint.failures
        if options.with_comments:
            comments = _dedupe_comments_with_log(checkpoint.comments, logger, stage="resume")
            historical_comments = RunStorage.load_reusable_comment_history(paths, query)
            comments = _merge_reusable_comment_history(
                comments,
                historical_comments,
                notes,
                logger,
                options,
            )
        last_completed_page = int(checkpoint.meta.get("last_completed_page", 0) or 0)
        resume_detail_after = str(checkpoint.meta.get("last_detail_note_id", "") or "")
        resume_comment_after = str(checkpoint.meta.get("last_comment_note_id", "") or "")
        if options.detail and options.force_detail:
            logger.info("[resume] Force-detail enabled; reprocessing detail stage from the first prepared note")
            resume_detail_after = ""
            _clear_detail_fields(notes)
        if resume_detail_after and not _has_note_id(notes, resume_detail_after):
            logger.info("[resume] Ignoring stale last_detail_note_id=%s", resume_detail_after)
            resume_detail_after = ""
        if resume_detail_after and not _note_has_detail_enrichment(notes, resume_detail_after):
            logger.info(
                "[resume] Reprocessing last_detail_note_id=%s because checkpoint lacks detail fields",
                resume_detail_after,
            )
            resume_detail_after = ""
        resume_comment_after = _resolve_resume_comment_after(
            resume_comment_after,
            notes,
            comments,
            options,
            logger,
        )
        logger.info("[resume] Loaded checkpoint: %s", checkpoint.path)
        logger.info(
            "[resume] Reusing notes=%s comments=%s failures=%s without replaying search traffic",
            len(notes),
            len(comments),
            len(failed_records),
        )

    if options.comments_only and not notes:
        logger.warning(
            "[comments-only] No reusable checkpoint notes found for query=%s; search traffic was not replayed",
            query,
        )
        _record_search_runtime_stage(
            storage,
            duration_seconds=0.0,
            status="skipped",
            skipped_count=0,
            stop_reason="comments_only_no_checkpoint",
        )
        output_paths = storage.export_final(notes=notes, comments=comments, failures=failed_records)
        logger.info("[done] notes=%s comments=%s failures=%s", len(notes), len(comments), len(failed_records))
        _log_done_output_paths(logger, output_paths)
        logger.info("[done] log file: %s", storage.log_path)
        if options.save_raw_json:
            logger.info("[done] raw json dir: %s", storage.raw_run_dir)
        logger.info("[done] checkpoint: %s", storage.checkpoint_path)
        if options.persist_history:
            logger.info("[done] history db: %s", paths.history_db_path)
        return

    with sync_playwright() as playwright:
        browser = None
        context = None
        try:
            browser, context = create_authenticated_context(
                playwright,
                paths,
                headed=options.headed,
                logger=logger,
                use_persistent_context=options.use_persistent_context,
            )

            if not notes:
                search_collector = SearchCollector(logger)
                search_started_at = time.monotonic()
                search_failures_before = len(failed_records)
                try:
                    notes = search_collector.collect_notes(
                        context=context,
                        options=options,
                        storage=storage,
                        failed_records=failed_records,
                    )
                    notes = _prepare_notes_for_run(notes, logger, options, stage="search")
                except Exception as exc:
                    _record_search_runtime_stage(
                        storage,
                        duration_seconds=time.monotonic() - search_started_at,
                        status="failed",
                        failure_count=max(1, len(failed_records) - search_failures_before),
                        stop_reason=type(exc).__name__,
                    )
                    raise
                _record_search_runtime_stage(
                    storage,
                    duration_seconds=time.monotonic() - search_started_at,
                    status="completed",
                    success_count=len(notes),
                    failure_count=max(0, len(failed_records) - search_failures_before),
                )
                last_completed_page = options.pages
            else:
                logger.info("[resume] Search stage skipped because checkpoint already contains notes")
                _record_search_runtime_stage(
                    storage,
                    duration_seconds=0.0,
                    status="skipped",
                    skipped_count=len(notes),
                    stop_reason="checkpoint_reused",
                )

            if options.detail and notes:
                notes = _prepare_notes_for_run(notes, logger, options, stage="detail-prep")
                detail_collector = DetailCollector(logger)
                detail_started_at = time.monotonic()
                detail_failures_before = len(failed_records)
                try:
                    detail_collector.enrich_notes(
                        context=context,
                        notes=notes,
                        options=options,
                        storage=storage,
                        failed_records=failed_records,
                        existing_comments=comments,
                        last_completed_page=last_completed_page,
                        start_after_note_id=resume_detail_after,
                    )
                except Exception as exc:
                    _record_detail_runtime_stage(
                        storage,
                        duration_seconds=time.monotonic() - detail_started_at,
                        status="failed",
                        failure_count=max(1, len(failed_records) - detail_failures_before),
                        stop_reason=type(exc).__name__,
                    )
                    raise
                detail_failure_count = max(0, len(failed_records) - detail_failures_before)
                _record_detail_runtime_stage(
                    storage,
                    duration_seconds=time.monotonic() - detail_started_at,
                    status="completed",
                    success_count=max(0, len(notes) - detail_failure_count),
                    failure_count=detail_failure_count,
                )

            if options.with_comments and notes:
                comment_collector = CommentCollector(logger)
                comments_started_at = time.monotonic()
                comments_before = len(comments)
                comment_failures_before = len(failed_records)
                try:
                    comments = comment_collector.collect_comments(
                        context=context,
                        notes=notes,
                        options=options,
                        storage=storage,
                        failed_records=failed_records,
                        last_completed_page=last_completed_page,
                        existing_comments=comments,
                        start_after_note_id=resume_comment_after,
                    )
                except Exception as exc:
                    _record_comments_runtime_stage(
                        storage,
                        duration_seconds=time.monotonic() - comments_started_at,
                        status="failed",
                        failure_count=max(1, len(failed_records) - comment_failures_before),
                        stop_reason=type(exc).__name__,
                    )
                    raise
                comments = _dedupe_comments_with_log(comments, logger, stage="comments")
                _record_comments_runtime_stage(
                    storage,
                    duration_seconds=time.monotonic() - comments_started_at,
                    status="completed",
                    success_count=max(0, len(comments) - comments_before),
                    failure_count=max(0, len(failed_records) - comment_failures_before),
                )
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()

    notes = _prepare_notes_for_run(notes, logger, options, stage="final")
    comments = _dedupe_comments_with_log(comments, logger, stage="final")
    output_paths = storage.export_final(notes=notes, comments=comments, failures=failed_records)
    logger.info("[done] notes=%s comments=%s failures=%s", len(notes), len(comments), len(failed_records))
    _log_done_output_paths(logger, output_paths)
    logger.info("[done] log file: %s", storage.log_path)
    if options.save_raw_json:
        logger.info("[done] raw json dir: %s", storage.raw_run_dir)
    logger.info("[done] checkpoint: %s", storage.checkpoint_path)
    if options.persist_history:
        logger.info("[done] history db: %s", paths.history_db_path)


def batch_search(
    keywords_file: str,
    *,
    keyword_delay_min: float = 30.0,
    keyword_delay_max: float = 60.0,
    stop_on_error: bool = False,
    **search_kwargs: object,
) -> None:
    """Run search sequentially for multiple keywords from a text file."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    keywords = load_keywords_file(Path(keywords_file))
    if not keywords:
        raise ValueError(f"No keywords found in {keywords_file}")

    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    delays = sorted((keyword_delay_min, keyword_delay_max))
    results: list[dict[str, object]] = []
    for index, keyword in enumerate(keywords, start=1):
        result: dict[str, object] = {
            "keyword": keyword,
            "index": index,
            "total": len(keywords),
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "succeeded",
            "error_type": "",
            "error_message": "",
        }
        try:
            keyword_kwargs = dict(search_kwargs)
            if keyword_kwargs.get("output"):
                output_base = Path(str(keyword_kwargs["output"]))
                keyword_kwargs["output"] = str(
                    output_base.with_name(f"{output_base.name}_{slugify_filename(keyword)}")
                )
            search(keyword, **keyword_kwargs)
        except Exception as exc:
            result["status"] = "failed"
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)
            results.append(result)
            if stop_on_error:
                report_path = write_batch_report(paths=paths, started_at=started_at, results=results)
                print(f"Batch stopped after failure. Report: {report_path}")
                raise
        else:
            results.append(result)

        if index < len(keywords):
            time.sleep(random.uniform(delays[0], delays[1]))

    report_path = write_batch_report(paths=paths, started_at=started_at, results=results)
    print(f"Batch report: {report_path}")


def comments_only(
    query: str,
    **search_kwargs: object,
) -> None:
    """Collect additional public comments for checkpointed notes without replaying search/detail."""
    search(
        query,
        pages=1,
        detail=False,
        with_comments=True,
        resume=True,
        force_detail=False,
        comments_only=True,
        **search_kwargs,
    )


def history_summary() -> None:
    """Print a compact JSON summary of the SQLite history database."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    print(json_dumps(HistoryStore(paths.history_db_path).summary()))


def history_export(
    *,
    record_type: str,
    output: str,
    keyword: str = "",
    note_id: str = "",
    failure_type: str = "",
    stage: str = "",
    limit: Optional[int] = None,
) -> None:
    """Export filtered rows from data/history.sqlite3 to CSV."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    result = export_history_records(
        db_path=paths.history_db_path,
        output_path=Path(output),
        record_type=record_type,
        keyword=keyword,
        note_id=note_id,
        failure_type=failure_type,
        stage=stage,
        limit=limit,
    )
    print(
        json_dumps(
            {
                "record_type": result.record_type,
                "count": result.count,
                "output": str(result.output_path),
                "db_path": str(result.db_path),
            }
        )
    )


def history_quality(
    *,
    output: str,
    keyword: str = "",
    limit: Optional[int] = None,
) -> None:
    """Export a per-run quality dashboard from data/history.sqlite3."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    result = export_history_quality_summary(
        db_path=paths.history_db_path,
        output_path=Path(output),
        keyword=keyword,
        limit=limit,
    )
    print(
        json_dumps(
            {
                "count": result.count,
                "output": str(result.output_path),
                "db_path": str(result.db_path),
            }
        )
    )


def best_export(
    query: str,
    *,
    output: Optional[str] = None,
    max_notes: Optional[int] = None,
    include_comments: bool = True,
    include_merged_comments: bool = False,
    export_format: str = "csv",
) -> None:
    """Export best merged local notes/comments for a query."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    result = export_best_records(
        paths=paths,
        query=query,
        output_base=Path(output) if output else None,
        max_notes=max_notes,
        include_comments=include_comments,
        include_merged_comments=include_merged_comments,
        export_format=export_format,
    )
    print(
        json_dumps(
            {
                "query": query,
                "notes_count": result.notes_count,
                "comments_count": result.comments_count,
                "history_notes_count": result.history_notes_count,
                "checkpoint_notes_count": result.checkpoint_notes_count,
                "history_comments_count": result.history_comments_count,
                "checkpoint_comments_count": result.checkpoint_comments_count,
                "anchor_checkpoint": str(result.anchor_checkpoint or ""),
                "anchor_notes_count": result.anchor_notes_count,
                "include_merged_comments": include_merged_comments,
                "outputs": [str(path) for path in result.output_paths],
            }
        )
    )


def detail_queue(
    query: str,
    *,
    max_notes_total: Optional[int] = None,
    output: Optional[str] = None,
    only_recommended: bool = False,
    include_blocked_note_ids: bool = False,
) -> None:
    """Build a local queue of notes whose detail fields should be retried."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    items, checkpoint_path = build_detail_queue(
        paths=paths,
        query=query,
        max_notes_total=max_notes_total,
    )
    output_paths = write_detail_queue(
        paths=paths,
        query=query,
        items=items,
        output=Path(output) if output else None,
        only_recommended=only_recommended,
        include_blocked_note_ids=include_blocked_note_ids,
    )
    visible_count = sum(1 for item in items if item.retry_recommended or not only_recommended)
    print(
        json_dumps(
            {
                "query": query,
                "checkpoint": str(checkpoint_path or ""),
                "count": visible_count,
                "total_count": len(items),
                "output_mode": "recommended" if only_recommended else "review",
                "note_ids_mode": "visible_items" if include_blocked_note_ids else "recommended",
                "outputs": [str(path) for path in output_paths],
            }
        )
    )


def comment_queue(
    query: str,
    *,
    first_level_target: int,
    second_level_target: int,
    max_notes_total: Optional[int] = None,
    output: Optional[str] = None,
    only_recommended: bool = False,
    include_blocked_note_ids: bool = False,
    sort_by: str = "input-order",
    batch_size: Optional[int] = None,
    batch_no: Optional[int] = None,
) -> None:
    """Build a local queue of notes whose comment quotas should be retried."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    items, checkpoint_path = build_comment_queue(
        paths=paths,
        query=query,
        first_level_target=first_level_target,
        second_level_target=second_level_target,
        max_notes_total=max_notes_total,
        sort_by=sort_by,
        batch_size=batch_size,
    )
    output_paths = write_comment_queue(
        paths=paths,
        query=query,
        items=items,
        output=Path(output) if output else None,
        only_recommended=only_recommended,
        include_blocked_note_ids=include_blocked_note_ids,
        batch_no=batch_no,
    )
    visible_count = sum(1 for item in items if item.retry_recommended or not only_recommended)
    print(
        json_dumps(
            {
                "query": query,
                "source_checkpoint": str(checkpoint_path or ""),
                "count": visible_count,
                "total_count": len(items),
                "first_level_target": first_level_target,
                "second_level_target": second_level_target,
                "sort_by": sort_by,
                "batch_size": batch_size,
                "batch_no": batch_no,
                "outputs": [str(path) for path in output_paths],
            }
        )
    )


def workflow_plan(
    keywords_file: str,
    *,
    output: Optional[str] = None,
    pages: int = 1,
    max_notes_total: int = 5,
    search_delay_min: float = 6.0,
    search_delay_max: float = 9.0,
    detail_delay_min: float = 10.0,
    detail_delay_max: float = 15.0,
    detail_timeout: float = 20.0,
    detail_render_wait: float = 8.0,
    detail_empty_retries: int = MAX_DETAIL_EMPTY_RETRIES,
    detail_empty_retry_wait: float = 10.0,
    comment_delay_min: float = 10.0,
    comment_delay_max: float = 15.0,
    max_comments_per_note: int = 5,
    with_comments: bool = False,
    include_replies: bool = False,
    headed: bool = True,
    save_raw_json: bool = True,
    debug: bool = True,
    history_limit: int = 20,
) -> None:
    """Create an offline safe workflow plan for a keyword file."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    result = create_safe_workflow_plan(
        paths=paths,
        keywords_file=Path(keywords_file),
        output=Path(output) if output else None,
        options=WorkflowPlanOptions(
            pages=pages,
            max_notes_total=max_notes_total,
            search_delay_min=search_delay_min,
            search_delay_max=search_delay_max,
            detail_delay_min=detail_delay_min,
            detail_delay_max=detail_delay_max,
            detail_timeout=detail_timeout,
            detail_render_wait=detail_render_wait,
            detail_empty_retries=detail_empty_retries,
            detail_empty_retry_wait=detail_empty_retry_wait,
            comment_delay_min=comment_delay_min,
            comment_delay_max=comment_delay_max,
            max_comments_per_note=max_comments_per_note,
            with_comments=with_comments,
            include_replies=include_replies,
            headed=headed,
            save_raw_json=save_raw_json,
            debug=debug,
            history_limit=history_limit,
        ),
    )
    print(
        json_dumps(
            {
                "keyword_count": result.keyword_count,
                "json": str(result.json_path),
                "csv": str(result.csv_path),
                "commands": str(result.commands_path),
            }
        )
    )


def reparse_detail_dom(
    *,
    checkpoint: str,
    detail_dom: str,
    output: str,
    export_format: str = "csv",
    checkpoint_output: Optional[str] = None,
) -> None:
    """Recompute detail fields from saved detail_dom snapshots."""
    paths = AppPaths.from_root(Path(__file__).resolve().parent)
    paths.ensure()
    output_base = Path(output)
    checkpoint_path = (
        Path(checkpoint_output)
        if checkpoint_output
        else paths.checkpoints_dir / f"{output_base.with_suffix('').name}_checkpoint.json"
    )
    result = reparse_detail_dom_checkpoint(
        checkpoint_path=Path(checkpoint),
        detail_dom_path=Path(detail_dom),
        output_base=output_base,
        export_format=export_format,
        checkpoint_output_path=checkpoint_path,
    )
    print(
        json_dumps(
            {
                "notes_count": result.notes_count,
                "reparsed_count": result.reparsed_count,
                "checkpoint": str(result.checkpoint_path),
                "outputs": [str(path) for path in result.output_paths],
            }
        )
    )


def _dedupe_notes_with_log(notes: list, logger: object, *, stage: str) -> list:
    deduped = dedupe_notes(notes)
    if len(deduped) != len(notes):
        logger.info("[%s] Deduped notes %s -> %s", stage, len(notes), len(deduped))
    return deduped


def _dedupe_comments_with_log(comments: list, logger: object, *, stage: str) -> list:
    deduped = dedupe_comments(comments)
    if len(deduped) != len(comments):
        logger.info("[%s] Deduped comments %s -> %s", stage, len(comments), len(deduped))
    return deduped


def _merge_reusable_comment_history(
    comments: list[CommentRecord],
    historical_comments: list[CommentRecord],
    notes: list[NoteRecord],
    logger: object,
    options: CrawlOptions,
) -> list[CommentRecord]:
    """Reuse checkpointed comments for selected notes and cap them to the current run limit."""
    selected_note_ids = {note.note_id for note in notes if note.note_id}
    scoped_comments = [
        comment
        for comment in [*comments, *historical_comments]
        if comment.note_id in selected_note_ids
    ]
    deduped = _dedupe_comments_with_log(scoped_comments, logger, stage="comment-history")
    filtered, filter_stats = filter_comments_for_options(
        deduped,
        root_comment_ids=getattr(options, "root_comment_ids", ()),
        root_comment_id_filter_active=getattr(options, "root_comment_id_filter_active", False),
        max_replies_per_comment=getattr(options, "max_replies_per_comment", None),
        max_first_level_comments_per_note=getattr(options, "max_first_level_comments_per_note", None),
        max_second_level_comments_per_note=getattr(options, "max_second_level_comments_per_note", None),
    )
    if filter_stats.root_filter_skipped:
        logger.info(
            "[resume] Applied root_comment_ids filter to reusable comments; skipped=%s",
            filter_stats.root_filter_skipped,
        )
    if filter_stats.reply_cap_filtered:
        logger.info(
            "[resume] Applied max_replies_per_comment=%s to reusable comments; skipped_replies=%s",
            options.max_replies_per_comment,
            filter_stats.reply_cap_filtered,
        )
    if filter_stats.first_level_cap_filtered or filter_stats.second_level_cap_filtered:
        logger.info(
            "[resume] Applied per-level comment quotas to reusable comments; skipped_first=%s skipped_second=%s",
            filter_stats.first_level_cap_filtered,
            filter_stats.second_level_cap_filtered,
        )
    deduped = filtered
    if (
        getattr(options, "max_first_level_comments_per_note", None) is not None
        or getattr(options, "max_second_level_comments_per_note", None) is not None
    ):
        capped = deduped
    else:
        capped = _cap_comments_per_note(deduped, options.max_comments_per_note)
    reused = len(capped) - len(comments)
    if reused > 0:
        logger.info("[resume] Reused %s comment(s) from historical checkpoints", reused)
    if len(capped) != len(deduped):
        logger.info(
            "[resume] Applied max_comments_per_note=%s to reusable comments %s -> %s",
            options.max_comments_per_note,
            len(deduped),
            len(capped),
        )
    return capped


def _cap_comments_per_note(comments: list[CommentRecord], max_comments_per_note: int) -> list[CommentRecord]:
    if max_comments_per_note < 1:
        return []
    counts: dict[str, int] = {}
    capped: list[CommentRecord] = []
    for comment in comments:
        note_id = comment.note_id
        count = counts.get(note_id, 0)
        if count >= max_comments_per_note:
            continue
        capped.append(comment)
        counts[note_id] = count + 1
    return capped


def _resolve_resume_comment_after(
    resume_comment_after: str,
    notes: list[NoteRecord],
    comments: list[CommentRecord],
    options: CrawlOptions,
    logger: object,
) -> str:
    marker = str(resume_comment_after or "").strip()
    if not marker:
        return ""
    if not _has_note_id(notes, marker):
        logger.info("[resume] Ignoring stale last_comment_note_id=%s", marker)
        return ""
    existing_count = sum(1 for comment in comments if comment.note_id == marker)
    note = next((note for note in notes if note.note_id == marker), None)
    if note is None or not should_reuse_existing_comments(
        note=note,
        options=options,
        existing_count=existing_count,
        level_counts=level_counts_by_note(comments),
    ):
        logger.info(
            "[resume] Reprocessing last_comment_note_id=%s because existing comments=%s do not meet requested quota",
            marker,
            existing_count,
        )
        return ""
    return marker


def _prepare_notes_for_run(notes: list, logger: object, options: CrawlOptions, *, stage: str) -> list:
    prepared = _dedupe_notes_with_log(notes, logger, stage=stage)
    before_filter = len(prepared)
    prepared = [note for note in prepared if _note_can_open_detail(note)]
    if len(prepared) != before_filter:
        logger.warning("[%s] Dropped non-navigable notes %s -> %s", stage, before_filter, len(prepared))

    selected_note_ids = set(getattr(options, "note_ids", ()) or ())
    if getattr(options, "note_id_filter_active", False):
        before_note_filter = len(prepared)
        prepared = [note for note in prepared if getattr(note, "note_id", "") in selected_note_ids]
        logger.info(
            "[%s] Applying note_ids filter=%s to notes %s -> %s",
            stage,
            len(selected_note_ids),
            before_note_filter,
            len(prepared),
        )

    if options.max_notes_total is not None and len(prepared) > options.max_notes_total:
        logger.info(
            "[%s] Applying max_notes_total=%s to notes %s -> %s",
            stage,
            options.max_notes_total,
            len(prepared),
            options.max_notes_total,
        )
        prepared = prepared[: options.max_notes_total]
    return prepared


def _note_can_open_detail(note: object) -> bool:
    note_id = getattr(note, "note_id", "")
    note_url = getattr(note, "note_url", "")
    return looks_like_web_note_id(note_id) or looks_like_web_note_url(note_url)


def _has_note_id(notes: list, note_id: str) -> bool:
    return any(getattr(note, "note_id", "") == note_id for note in notes)


def _note_has_detail_enrichment(notes: list, note_id: str) -> bool:
    for note in notes:
        if getattr(note, "note_id", "") != note_id:
            continue
        return note_has_detail_enrichment(note)
    return False


def _looks_like_tag_only_content(content: str) -> bool:
    return note_content_is_tag_only(content)


_REUSABLE_DETAIL_FIELDS = (
    "title",
    "content",
    "note_type",
    "publish_time",
    "location",
    "ip_location",
    "tags",
    "images",
    "cover_image",
    "like_count",
    "collect_count",
    "comment_count",
    "share_count",
    "view_count",
    "raw_detail_json",
)


def _merge_reusable_detail_history(
    notes: list[NoteRecord],
    detail_history: dict[str, NoteRecord],
    logger: object,
) -> int:
    merged = 0
    for note in notes:
        source = detail_history.get(note.note_id)
        if source is None or not note_has_reusable_detail(source):
            continue
        if _note_has_incomplete_detail_attempt(note):
            continue
        had_reusable_detail = note_has_reusable_detail(note)
        updates = {
            field_name: getattr(source, field_name)
            for field_name in _REUSABLE_DETAIL_FIELDS
            if hasattr(source, field_name)
        }
        note.merge(updates)
        if note_has_reusable_detail(source):
            note.detail_processed = True
        if not had_reusable_detail and note_has_reusable_detail(note):
            merged += 1
    if merged:
        logger.info("[resume] Reused detail fields for %s note(s) from historical checkpoints", merged)
    return merged


def _note_has_incomplete_detail_attempt(note: NoteRecord) -> bool:
    attempted = bool(getattr(note, "detail_processed", False)) or bool(
        str(getattr(note, "raw_detail_json", "") or "").strip()
    )
    return attempted and not note_has_reusable_detail(note)


def _clear_detail_fields(notes: list) -> None:
    for note in notes:
        for field_name, empty_value in (
            ("content", ""),
            ("location", ""),
            ("ip_location", ""),
            ("tags", []),
            ("raw_detail_json", ""),
            ("detail_processed", False),
        ):
            if hasattr(note, field_name):
                setattr(note, field_name, list(empty_value) if isinstance(empty_value, list) else empty_value)


def _search_kwargs_from_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "pages": args.pages,
        "export_format": args.export_format,
        "export_merged_comments": getattr(args, "export_merged_comments", False),
        "output": args.output,
        "detail": args.detail,
        "search_delay_min": args.search_delay_min,
        "search_delay_max": args.search_delay_max,
        "detail_delay_min": args.detail_delay_min,
        "detail_delay_max": args.detail_delay_max,
        "detail_wait_timeout_ms": _seconds_to_ms(args.detail_timeout),
        "detail_render_wait_ms": _seconds_to_ms(args.detail_render_wait),
        "detail_empty_retries": args.detail_empty_retries,
        "detail_empty_retry_wait_ms": _seconds_to_ms(args.detail_empty_retry_wait),
        "comment_delay_min": args.comment_delay_min,
        "comment_delay_max": args.comment_delay_max,
        "headed": args.headed,
        "use_persistent_context": args.use_persistent_context,
        "debug": args.debug,
        "save_raw_json": args.save_raw_json,
        "max_items_per_page": args.max_items_per_page,
        "max_notes_total": args.max_notes_total,
        "with_comments": args.with_comments,
        "comments_only": getattr(args, "comments_only", False),
        "max_comments_per_note": args.max_comments_per_note,
        "include_replies": args.include_replies,
        "expand_replies": getattr(args, "expand_replies", False),
        "max_reply_expansions_per_note": getattr(args, "max_reply_expansions_per_note", 3),
        "max_replies_per_comment": getattr(args, "max_replies_per_comment", None),
        "max_first_level_comments_per_note": getattr(args, "max_first_level_comments_per_note", None),
        "max_second_level_comments_per_note": getattr(args, "max_second_level_comments_per_note", None),
        "root_comment_ids": getattr(args, "root_comment_ids", None),
        "root_comment_ids_file": getattr(args, "root_comment_ids_file", None),
        "resume": args.resume,
        "force_detail": args.force_detail,
        "skip_enriched_detail": args.skip_enriched_detail,
        "persist_history": args.persist_history,
        "manual_verification": getattr(args, "manual_verification", True),
        "verification_wait_seconds": getattr(args, "verification_wait_seconds", 180),
        "note_ids": getattr(args, "note_ids", None),
        "note_ids_file": getattr(args, "note_ids_file", None),
    }


def _comments_only_kwargs_from_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "export_format": args.export_format,
        "export_merged_comments": getattr(args, "export_merged_comments", False),
        "output": args.output,
        "comment_delay_min": args.comment_delay_min,
        "comment_delay_max": args.comment_delay_max,
        "headed": args.headed,
        "use_persistent_context": args.use_persistent_context,
        "debug": args.debug,
        "save_raw_json": args.save_raw_json,
        "max_notes_total": args.max_notes_total,
        "max_comments_per_note": args.max_comments_per_note,
        "include_replies": args.include_replies,
        "expand_replies": args.expand_replies,
        "max_reply_expansions_per_note": args.max_reply_expansions_per_note,
        "max_replies_per_comment": args.max_replies_per_comment,
        "max_first_level_comments_per_note": args.max_first_level_comments_per_note,
        "max_second_level_comments_per_note": args.max_second_level_comments_per_note,
        "root_comment_ids": getattr(args, "root_comment_ids", None),
        "root_comment_ids_file": getattr(args, "root_comment_ids_file", None),
        "persist_history": args.persist_history,
        "manual_verification": getattr(args, "manual_verification", True),
        "verification_wait_seconds": getattr(args, "verification_wait_seconds", 180),
        "note_ids": getattr(args, "note_ids", None),
        "note_ids_file": getattr(args, "note_ids_file", None),
    }


def _seconds_to_ms(value: float) -> int:
    return int(round(value * 1000))


def _record_search_runtime_stage(
    storage: RunStorage,
    *,
    duration_seconds: float,
    status: str,
    success_count: int = 0,
    failure_count: int = 0,
    skipped_count: int = 0,
    stop_reason: str = "",
) -> None:
    duration = max(0.0, float(duration_seconds))
    storage.runtime_profile.search_duration_seconds += duration
    storage.record_runtime_stage(
        RuntimeStageProfile(
            stage="search",
            duration_seconds=duration,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=skipped_count,
            stop_reason=stop_reason,
        )
    )


def _record_detail_runtime_stage(
    storage: RunStorage,
    *,
    duration_seconds: float,
    status: str,
    success_count: int = 0,
    failure_count: int = 0,
    skipped_count: int = 0,
    stop_reason: str = "",
) -> None:
    duration = max(0.0, float(duration_seconds))
    storage.runtime_profile.detail_duration_seconds += duration
    storage.record_runtime_stage(
        RuntimeStageProfile(
            stage="detail",
            duration_seconds=duration,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=skipped_count,
            stop_reason=stop_reason,
        )
    )


def _record_comments_runtime_stage(
    storage: RunStorage,
    *,
    duration_seconds: float,
    status: str,
    success_count: int = 0,
    failure_count: int = 0,
    skipped_count: int = 0,
    stop_reason: str = "",
) -> None:
    duration = max(0.0, float(duration_seconds))
    storage.runtime_profile.comments_duration_seconds += duration
    storage.record_runtime_stage(
        RuntimeStageProfile(
            stage="comments",
            duration_seconds=duration,
            status=status,
            success_count=success_count,
            failure_count=failure_count,
            skipped_count=skipped_count,
            stop_reason=stop_reason,
        )
    )


def _positive_int_arg(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _non_negative_int_arg(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def _add_detail_stability_arguments(
    parser: argparse.ArgumentParser,
    *,
    detail_timeout: float = DEFAULT_DETAIL_WAIT_TIMEOUT_MS / 1000,
    detail_render_wait: float = DEFAULT_DETAIL_RENDER_WAIT_MS / 1000,
    detail_empty_retries: int = MAX_DETAIL_EMPTY_RETRIES,
    detail_empty_retry_wait: float = DEFAULT_DETAIL_EMPTY_RETRY_WAIT_MS / 1000,
) -> None:
    parser.add_argument(
        "--detail-timeout",
        type=float,
        default=detail_timeout,
        help="Seconds to wait for detail network responses after opening and scrolling a note",
    )
    parser.add_argument(
        "--detail-render-wait",
        type=float,
        default=detail_render_wait,
        help="Seconds to wait for visible detail/comment DOM before fallback parsing",
    )
    parser.add_argument(
        "--detail-empty-retries",
        type=int,
        default=detail_empty_retries,
        help="Retry count for detail pages that expose no network, HTML, or DOM evidence",
    )
    parser.add_argument(
        "--detail-empty-retry-wait",
        type=float,
        default=detail_empty_retry_wait,
        help="Seconds to wait before retrying an empty detail snapshot",
    )


def _add_manual_verification_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--verification-wait",
        dest="verification_wait_seconds",
        type=int,
        default=180,
        help="Seconds to keep the browser open while waiting for manual verification to clear",
    )
    _add_boolean_pair(
        parser,
        "--manual-verification",
        "--no-manual-verification",
        dest="manual_verification",
        positive_help="Pause for manual verification when a recoverable verification page appears",
        negative_help="Treat verification pages as immediate failures",
    )


def _add_rate_profile_argument(
    parser: argparse.ArgumentParser,
    *,
    default: str = RUN_DEFAULT_RATE_PROFILE,
) -> None:
    parser.add_argument(
        "--rate-profile",
        choices=RATE_PROFILE_NAMES,
        default=default,
        help="Named safe delay profile for high-level run workflows",
    )


def _resolve_note_id_filter(*, note_ids: Optional[str], note_ids_file: Optional[str]) -> tuple[str, ...]:
    resolved = []
    resolved.extend(parse_note_ids(note_ids))
    if note_ids_file:
        resolved.extend(load_note_ids_file(Path(note_ids_file)))
    return tuple(dict.fromkeys(note_id for note_id in resolved if note_id))


def _resolve_comment_id_filter(
    *,
    comment_ids: Optional[str],
    comment_ids_file: Optional[str],
) -> tuple[str, ...]:
    resolved: list[str] = []
    resolved.extend(parse_note_ids(comment_ids))
    if comment_ids_file:
        resolved.extend(_load_comment_ids_file(Path(comment_ids_file)))
    return normalize_comment_ids(resolved)


def _load_comment_ids_file(path: Path) -> list[str]:
    """Load first-level comment ids from a text file or exported comments CSV."""
    if path.suffix.lower() != ".csv":
        return parse_note_ids(path.read_text(encoding="utf-8"))
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        rows = csv.DictReader(file)
        return list(
            normalize_comment_ids(
                _comment_root_id_from_csv_row(row)
                for row in rows
            )
        )


def _comment_root_id_from_csv_row(row: dict[str, str]) -> str:
    explicit_root = str(row.get("root_comment_id", "") or "").strip()
    if explicit_root:
        return explicit_root
    level = str(row.get("comment_level", "") or "1").strip()
    if level == "1":
        return str(row.get("comment_id", "") or "").strip()
    return str(row.get("parent_comment_id", "") or "").strip()


def _add_boolean_pair(
    parser: argparse.ArgumentParser,
    positive: str,
    negative: str,
    *,
    dest: str,
    positive_help: str,
    negative_help: str,
) -> None:
    """Add mutually exclusive positive/negative flags without misleading default text."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        positive,
        dest=dest,
        action="store_true",
        default=argparse.SUPPRESS,
        help=positive_help,
    )
    group.add_argument(
        negative,
        dest=dest,
        action="store_false",
        default=argparse.SUPPRESS,
        help=negative_help,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Xiaohongshu browser-based scraper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser(
        "login",
        help="Open a visible browser for the first manual login",
        description="Open a visible browser for the first manual login and save storage_state.",
    )
    login_parser.set_defaults(
        use_persistent_context=True,
        handler=lambda args: login(use_persistent_context=args.use_persistent_context),
    )
    _add_boolean_pair(
        login_parser,
        "--persistent-context",
        "--ephemeral-context",
        dest="use_persistent_context",
        positive_help="Reuse a persistent browser profile directory",
        negative_help="Use storage_state only instead of a persistent browser profile",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Preview the high-level one-command workflow configuration",
        description=(
            "Preview the high-level one-command workflow configuration. "
            "This shell command does not visit Xiaohongshu yet."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    run_parser.add_argument("query", help="Search keyword")
    run_parser.add_argument("--dry-run", action="store_true", help="Print the planned search command without running it")
    run_parser.add_argument(
        "--notes",
        type=_positive_int_arg,
        default=RUN_DEFAULT_NOTES,
        help="Number of notes to collect",
    )
    run_parser.add_argument(
        "--first-comments",
        type=_non_negative_int_arg,
        default=RUN_DEFAULT_FIRST_COMMENTS,
        help="First-level comments to collect per note",
    )
    run_parser.add_argument(
        "--second-comments",
        type=_non_negative_int_arg,
        default=RUN_DEFAULT_SECOND_COMMENTS,
        help="Second-level comments to collect per note",
    )
    run_parser.add_argument(
        "--output",
        "-o",
        help="Output file base path, passed through to the underlying search command",
    )
    run_parser.add_argument(
        "--auto-best-export",
        action="store_true",
        default=RUN_DEFAULT_AUTO_BEST_EXPORT,
        help="Run the offline best-export step after the preview shell when not using --dry-run",
    )
    _add_rate_profile_argument(run_parser)
    run_parser.set_defaults(with_comments=True)
    run_parser.set_defaults(export_merged_comments=RUN_DEFAULT_MERGED_COMMENTS)
    _add_boolean_pair(
        run_parser,
        "--comments",
        "--no-comments",
        dest="with_comments",
        positive_help="Collect public comments in the planned workflow",
        negative_help="Skip comment collection in the planned workflow",
    )
    _add_boolean_pair(
        run_parser,
        "--merged-comments",
        "--no-merged-comments",
        dest="export_merged_comments",
        positive_help="Also export one comment-analysis table joined with note fields",
        negative_help="Do not export the joined comment-analysis table",
    )
    run_parser.set_defaults(
        handler=lambda args: run_workflow(
            args.query,
            rate_profile=args.rate_profile,
            dry_run=args.dry_run,
            notes=args.notes,
            first_comments=args.first_comments,
            second_comments=args.second_comments,
            with_comments=args.with_comments,
            export_merged_comments=args.export_merged_comments,
            auto_best_export=args.auto_best_export,
            output=args.output,
        )
    )

    history_parser = subparsers.add_parser(
        "history",
        help="Show a compact summary of data/history.sqlite3",
        description="Show a compact summary of data/history.sqlite3.",
    )
    history_parser.set_defaults(handler=lambda args: history_summary())

    history_export_parser = subparsers.add_parser(
        "history-export",
        help="Export filtered rows from data/history.sqlite3",
        description="Export filtered rows from data/history.sqlite3 to CSV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    history_export_parser.add_argument(
        "--record-type",
        choices=("runs", "notes", "comments", "failures"),
        default="notes",
        help="History table to export",
    )
    history_export_parser.add_argument("--keyword", default="", help="Filter by query/keyword substring")
    history_export_parser.add_argument("--note-id", default="", help="Filter notes/comments by note_id or failures by target_id")
    history_export_parser.add_argument("--failure-type", default="", help="Filter failures by error_type")
    history_export_parser.add_argument("--stage", default="", help="Filter failures by stage")
    history_export_parser.add_argument("--limit", type=int, default=None, help="Maximum rows to export")
    history_export_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="CSV output path",
    )
    history_export_parser.set_defaults(
        handler=lambda args: history_export(
            record_type=args.record_type,
            output=args.output,
            keyword=args.keyword,
            note_id=args.note_id,
            failure_type=args.failure_type,
            stage=args.stage,
            limit=args.limit,
        )
    )

    history_quality_parser = subparsers.add_parser(
        "history-quality",
        help="Export a per-run data-quality dashboard from data/history.sqlite3",
        description="Export a per-run data-quality dashboard from data/history.sqlite3.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    history_quality_parser.add_argument("--keyword", default="", help="Filter by query substring")
    history_quality_parser.add_argument("--limit", type=int, default=None, help="Maximum runs to export")
    history_quality_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="CSV output path",
    )
    history_quality_parser.set_defaults(
        handler=lambda args: history_quality(
            output=args.output,
            keyword=args.keyword,
            limit=args.limit,
        )
    )

    best_export_parser = subparsers.add_parser(
        "best-export",
        help="Export best merged local notes/comments for a query",
        description="Merge local history and checkpoints into the cleanest notes/comments CSVs without live access.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    best_export_parser.add_argument("query", help="Search keyword")
    best_export_parser.add_argument("--output", "-o", help="Output file base path")
    best_export_parser.add_argument("--max-notes", type=int, default=None, help="Maximum notes to export")
    best_export_parser.add_argument(
        "--format",
        dest="export_format",
        choices=("csv", "excel"),
        default="csv",
        help="Export format",
    )
    best_export_parser.set_defaults(include_comments=True, include_merged_comments=False)
    _add_boolean_pair(
        best_export_parser,
        "--comments",
        "--no-comments",
        dest="include_comments",
        positive_help="Include merged comments in the export",
        negative_help="Do not export comments",
    )
    _add_boolean_pair(
        best_export_parser,
        "--merged-comments",
        "--no-merged-comments",
        dest="include_merged_comments",
        positive_help="Also export one comment-analysis table joined with note fields",
        negative_help="Do not export the joined comment-analysis table",
    )
    best_export_parser.set_defaults(
        handler=lambda args: best_export(
            args.query,
            output=args.output,
            max_notes=args.max_notes,
            include_comments=args.include_comments,
            include_merged_comments=args.include_merged_comments,
            export_format=args.export_format,
        )
    )

    detail_queue_parser = subparsers.add_parser(
        "detail-queue",
        help="Build a local retry queue for notes with incomplete detail fields",
        description="Build a local retry queue for notes with incomplete detail fields.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    detail_queue_parser.add_argument("query", help="Search keyword")
    detail_queue_parser.add_argument(
        "--max-notes-total",
        type=int,
        default=None,
        help="Inspect at most this many notes from the selected checkpoint",
    )
    detail_queue_parser.add_argument(
        "--output",
        "-o",
        help="Output file base path for the queue",
    )
    detail_queue_parser.add_argument(
        "--only-recommended",
        action="store_true",
        help="Write only retry_recommended=True rows to CSV/JSON outputs",
    )
    detail_queue_parser.add_argument(
        "--include-blocked-note-ids",
        action="store_true",
        help="Also write blocked rows to _note_ids.txt; use only for explicit manual retries",
    )
    detail_queue_parser.set_defaults(
        handler=lambda args: detail_queue(
            args.query,
            max_notes_total=args.max_notes_total,
            output=args.output,
            only_recommended=args.only_recommended,
            include_blocked_note_ids=args.include_blocked_note_ids,
        )
    )

    comment_queue_parser = subparsers.add_parser(
        "comment-queue",
        help="Build a local retry queue for notes with incomplete comment quotas",
        description="Build a local retry queue for notes with incomplete comment quotas without visiting Xiaohongshu.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    comment_queue_parser.add_argument("query", help="Search keyword")
    comment_queue_parser.add_argument(
        "--first-level-target",
        type=int,
        required=True,
        help="Target first-level comments per note",
    )
    comment_queue_parser.add_argument(
        "--second-level-target",
        type=int,
        required=True,
        help="Target second-level replies per note",
    )
    comment_queue_parser.add_argument(
        "--max-notes-total",
        type=int,
        default=None,
        help="Inspect at most this many notes from the selected checkpoint",
    )
    comment_queue_parser.add_argument(
        "--output",
        "-o",
        help="Output file base path for the queue",
    )
    comment_queue_parser.add_argument(
        "--only-recommended",
        action="store_true",
        help="Write only retry_recommended=True rows to CSV/JSON outputs",
    )
    comment_queue_parser.add_argument(
        "--include-blocked-note-ids",
        action="store_true",
        help="Also write blocked rows to _note_ids.txt; use only for explicit manual retries",
    )
    comment_queue_parser.add_argument(
        "--sort-by",
        choices=COMMENT_QUEUE_SORT_OPTIONS,
        default="input-order",
        help="Queue ordering strategy",
    )
    comment_queue_parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Assign recommended_batch_no using this many visible queue rows per batch",
    )
    comment_queue_parser.add_argument(
        "--batch-no",
        type=int,
        default=None,
        help="Write only this recommended batch to _note_ids.txt; defaults to 1 when --batch-size is used",
    )
    comment_queue_parser.set_defaults(
        handler=lambda args: comment_queue(
            args.query,
            first_level_target=args.first_level_target,
            second_level_target=args.second_level_target,
            max_notes_total=args.max_notes_total,
            output=args.output,
            only_recommended=args.only_recommended,
            include_blocked_note_ids=args.include_blocked_note_ids,
            sort_by=args.sort_by,
            batch_size=args.batch_size,
            batch_no=args.batch_no,
        )
    )

    workflow_parser = subparsers.add_parser(
        "workflow-plan",
        help="Create an offline safe workflow plan for a keyword file",
        description="Create local queue, quality, and live-command plans without visiting Xiaohongshu.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    workflow_parser.add_argument("keywords_file", help="UTF-8 text file with one keyword per line")
    workflow_parser.add_argument("--output", "-o", help="Output file base path for the workflow plan")
    workflow_parser.add_argument("--pages", type=int, default=1, help="Pages for the planned fresh search command")
    workflow_parser.add_argument("--max-notes-total", type=int, default=5, help="Max notes for planned search/detail commands")
    workflow_parser.add_argument("--search-delay-min", type=float, default=6.0, help="Min delay for planned search batches")
    workflow_parser.add_argument("--search-delay-max", type=float, default=9.0, help="Max delay for planned search batches")
    workflow_parser.add_argument("--detail-delay-min", type=float, default=10.0, help="Min delay for planned detail retries")
    workflow_parser.add_argument("--detail-delay-max", type=float, default=15.0, help="Max delay for planned detail retries")
    _add_detail_stability_arguments(
        workflow_parser,
        detail_timeout=20.0,
        detail_render_wait=8.0,
        detail_empty_retries=MAX_DETAIL_EMPTY_RETRIES,
        detail_empty_retry_wait=10.0,
    )
    workflow_parser.add_argument("--comment-delay-min", type=float, default=10.0, help="Min delay for planned comment collection")
    workflow_parser.add_argument("--comment-delay-max", type=float, default=15.0, help="Max delay for planned comment collection")
    workflow_parser.add_argument("--max-comments-per-note", type=int, default=5, help="Max comments for planned comment collection")
    workflow_parser.add_argument("--history-limit", type=int, default=20, help="Max history rows for planned quality reports")
    workflow_parser.set_defaults(
        headed=True,
        save_raw_json=True,
        debug=True,
        with_comments=False,
        include_replies=False,
    )
    _add_boolean_pair(
        workflow_parser,
        "--headed",
        "--headless",
        dest="headed",
        positive_help="Show the browser window in planned live commands",
        negative_help="Run planned live commands without showing the browser",
    )
    _add_boolean_pair(
        workflow_parser,
        "--save-raw-json",
        "--no-save-raw-json",
        dest="save_raw_json",
        positive_help="Save raw responses in planned live commands",
        negative_help="Do not save raw responses in planned live commands",
    )
    _add_boolean_pair(
        workflow_parser,
        "--debug",
        "--no-debug",
        dest="debug",
        positive_help="Enable debug logging in planned live commands",
        negative_help="Disable debug logging in planned live commands",
    )
    _add_boolean_pair(
        workflow_parser,
        "--with-comments",
        "--no-comments",
        dest="with_comments",
        positive_help="Include comment collection in planned detail reruns",
        negative_help="Do not include comment collection in planned detail reruns",
    )
    _add_boolean_pair(
        workflow_parser,
        "--include-replies",
        "--no-replies",
        dest="include_replies",
        positive_help="Include second-level replies in planned comment collection",
        negative_help="Do not include second-level replies in planned comment collection",
    )
    workflow_parser.set_defaults(
        handler=lambda args: workflow_plan(
            args.keywords_file,
            output=args.output,
            pages=args.pages,
            max_notes_total=args.max_notes_total,
            search_delay_min=args.search_delay_min,
            search_delay_max=args.search_delay_max,
            detail_delay_min=args.detail_delay_min,
            detail_delay_max=args.detail_delay_max,
            detail_timeout=args.detail_timeout,
            detail_render_wait=args.detail_render_wait,
            detail_empty_retries=args.detail_empty_retries,
            detail_empty_retry_wait=args.detail_empty_retry_wait,
            comment_delay_min=args.comment_delay_min,
            comment_delay_max=args.comment_delay_max,
            max_comments_per_note=args.max_comments_per_note,
            with_comments=args.with_comments,
            include_replies=args.include_replies,
            headed=args.headed,
            save_raw_json=args.save_raw_json,
            debug=args.debug,
            history_limit=args.history_limit,
        )
    )

    reparse_parser = subparsers.add_parser(
        "reparse-detail-dom",
        help="Recompute detail fields from saved detail_dom JSONL without live access",
        description="Recompute detail fields from a checkpoint and saved detail_dom JSONL without visiting Xiaohongshu.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    reparse_parser.add_argument("--checkpoint", required=True, help="Checkpoint JSON path")
    reparse_parser.add_argument("--detail-dom", required=True, help="Saved detail_dom JSONL path")
    reparse_parser.add_argument("--output", "-o", required=True, help="Output file base path")
    reparse_parser.add_argument(
        "--checkpoint-output",
        help="Clean checkpoint output path; defaults to data/checkpoints/<output_name>_checkpoint.json",
    )
    reparse_parser.add_argument(
        "--format",
        dest="export_format",
        default="csv",
        choices=("csv", "excel"),
        help="Export format",
    )
    reparse_parser.set_defaults(
        handler=lambda args: reparse_detail_dom(
            checkpoint=args.checkpoint,
            detail_dom=args.detail_dom,
            output=args.output,
            export_format=args.export_format,
            checkpoint_output=args.checkpoint_output,
        )
    )

    comments_only_parser = subparsers.add_parser(
        "comments-only",
        help="Collect additional public comments for checkpointed notes",
        description=(
            "Collect additional public comments for existing checkpointed notes without replaying search "
            "or detail stages."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    comments_only_parser.add_argument("query", help="Search keyword used by the checkpoint")
    comments_only_parser.add_argument(
        "--format",
        dest="export_format",
        default="csv",
        help="csv or excel",
    )
    comments_only_parser.add_argument(
        "--output",
        "-o",
        help="Output file base path",
    )
    comments_only_parser.add_argument(
        "--comment-delay-min",
        type=float,
        default=4.0,
        help="Min delay between comment requests",
    )
    comments_only_parser.add_argument(
        "--comment-delay-max",
        type=float,
        default=6.0,
        help="Max delay between comment requests",
    )
    comments_only_parser.add_argument(
        "--max-notes-total",
        type=int,
        default=10,
        help="Limit checkpointed notes selected for comment collection",
    )
    comments_only_parser.add_argument(
        "--max-comments-per-note",
        type=int,
        default=50,
        help="Max comments to keep for each selected note",
    )
    comments_only_parser.add_argument(
        "--max-reply-expansions-per-note",
        type=int,
        default=3,
        help="Max visible reply expansion clicks per selected note when --expand-replies is enabled",
    )
    comments_only_parser.add_argument(
        "--max-replies-per-comment",
        type=int,
        help="Max second-level replies to keep for each first-level comment; 0 keeps first-level comments only",
    )
    comments_only_parser.add_argument(
        "--max-first-level-comments-per-note",
        type=int,
        help="Precise first-level comment quota per note; when set, it is independent from reply quotas",
    )
    comments_only_parser.add_argument(
        "--max-second-level-comments-per-note",
        type=int,
        help="Precise second-level reply quota per note; when set, it is independent from first-level quotas",
    )
    comments_only_parser.add_argument(
        "--root-comment-ids",
        help="Comma or whitespace separated first-level comment ids to keep or retry",
    )
    comments_only_parser.add_argument(
        "--root-comment-ids-file",
        help="Text file or comments CSV containing first-level comment ids to keep or retry",
    )
    comments_only_parser.add_argument(
        "--note-ids",
        help="Comma or whitespace separated note ids to keep from the selected checkpoint",
    )
    comments_only_parser.add_argument(
        "--note-ids-file",
        help="Text file or retry-queue CSV/JSON containing note ids to keep",
    )
    comments_only_parser.set_defaults(
        headed=True,
        use_persistent_context=True,
        debug=False,
        save_raw_json=False,
        export_merged_comments=False,
        include_replies=False,
        expand_replies=False,
        persist_history=True,
        manual_verification=True,
    )
    _add_boolean_pair(
        comments_only_parser,
        "--headed",
        "--headless",
        dest="headed",
        positive_help="Show the browser window",
        negative_help="Run without showing the browser",
    )
    _add_boolean_pair(
        comments_only_parser,
        "--persistent-context",
        "--ephemeral-context",
        dest="use_persistent_context",
        positive_help="Reuse a persistent browser profile directory",
        negative_help="Use storage_state only instead of a persistent browser profile",
    )
    _add_boolean_pair(
        comments_only_parser,
        "--debug",
        "--no-debug",
        dest="debug",
        positive_help="Enable debug logging",
        negative_help="Disable debug logging",
    )
    _add_boolean_pair(
        comments_only_parser,
        "--save-raw-json",
        "--no-save-raw-json",
        dest="save_raw_json",
        positive_help="Save captured raw responses as JSONL files",
        negative_help="Do not save captured raw responses as JSONL files",
    )
    _add_boolean_pair(
        comments_only_parser,
        "--merged-comments",
        "--no-merged-comments",
        dest="export_merged_comments",
        positive_help="Also export one comment-analysis table joined with note fields",
        negative_help="Do not export the joined comment-analysis table",
    )
    _add_boolean_pair(
        comments_only_parser,
        "--include-replies",
        "--no-replies",
        dest="include_replies",
        positive_help="Include second-level replies if they appear in public responses",
        negative_help="Do not include second-level replies",
    )
    _add_boolean_pair(
        comments_only_parser,
        "--expand-replies",
        "--no-expand-replies",
        dest="expand_replies",
        positive_help="Click bounded visible reply expansion controls before continuing comment pagination",
        negative_help="Do not click reply expansion controls",
    )
    _add_manual_verification_arguments(comments_only_parser)
    comments_only_parser.add_argument(
        "--history",
        dest="persist_history",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist final records into data/history.sqlite3",
    )
    comments_only_parser.set_defaults(
        handler=lambda args: comments_only(args.query, **_comments_only_kwargs_from_args(args))
    )

    search_parser = subparsers.add_parser(
        "search",
        help="Search Xiaohongshu and export normalized note data",
        description="Search Xiaohongshu and export normalized note data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    search_parser.add_argument("query", help="Search keyword")
    search_parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of scroll batches to collect",
    )
    search_parser.add_argument(
        "--format",
        dest="export_format",
        default="csv",
        help="csv or excel",
    )
    search_parser.add_argument(
        "--output",
        "-o",
        help="Output file base path",
    )
    search_parser.add_argument(
        "--search-delay-min",
        type=float,
        default=4.0,
        help="Min delay between search batches",
    )
    search_parser.add_argument(
        "--search-delay-max",
        type=float,
        default=7.0,
        help="Max delay between search batches",
    )
    search_parser.add_argument(
        "--detail-delay-min",
        type=float,
        default=3.0,
        help="Min delay between detail requests",
    )
    search_parser.add_argument(
        "--detail-delay-max",
        type=float,
        default=5.0,
        help="Max delay between detail requests",
    )
    _add_detail_stability_arguments(search_parser)
    search_parser.add_argument(
        "--comment-delay-min",
        type=float,
        default=4.0,
        help="Min delay between comment requests",
    )
    search_parser.add_argument(
        "--comment-delay-max",
        type=float,
        default=6.0,
        help="Max delay between comment requests",
    )
    search_parser.add_argument(
        "--max-items-per-page",
        type=int,
        help="Limit unique notes parsed from each scroll batch",
    )
    search_parser.add_argument(
        "--max-notes-total",
        type=int,
        default=10,
        help="Stop once this many unique notes have been collected",
    )
    search_parser.add_argument(
        "--max-comments-per-note",
        type=int,
        default=50,
        help="Max comments to keep for each note when comments are enabled",
    )
    search_parser.add_argument(
        "--max-reply-expansions-per-note",
        type=int,
        default=3,
        help="Max visible reply expansion clicks per note when --expand-replies is enabled",
    )
    search_parser.add_argument(
        "--max-replies-per-comment",
        type=int,
        help="Max second-level replies to keep for each first-level comment; 0 keeps first-level comments only",
    )
    search_parser.add_argument(
        "--max-first-level-comments-per-note",
        type=int,
        help="Precise first-level comment quota per note; when set, it is independent from reply quotas",
    )
    search_parser.add_argument(
        "--max-second-level-comments-per-note",
        type=int,
        help="Precise second-level reply quota per note; when set, it is independent from first-level quotas",
    )
    search_parser.add_argument(
        "--root-comment-ids",
        help="Comma or whitespace separated first-level comment ids to keep when comments are enabled",
    )
    search_parser.add_argument(
        "--root-comment-ids-file",
        help="Text file or comments CSV containing first-level comment ids to keep when comments are enabled",
    )
    search_parser.add_argument(
        "--note-ids",
        help="Comma or whitespace separated note ids to keep from the selected checkpoint/search result",
    )
    search_parser.add_argument(
        "--note-ids-file",
        help="Text file or retry-queue CSV/JSON containing note ids to keep",
    )

    search_parser.set_defaults(
        detail=False,
        headed=True,
        use_persistent_context=True,
        debug=False,
        save_raw_json=False,
        export_merged_comments=False,
        with_comments=False,
        include_replies=False,
        expand_replies=False,
        resume=True,
        force_detail=False,
        skip_enriched_detail=True,
        manual_verification=True,
    )
    _add_boolean_pair(
        search_parser,
        "--detail",
        "--no-detail",
        dest="detail",
        positive_help="Enrich notes via detail pages",
        negative_help="Skip detail page enrichment",
    )
    _add_boolean_pair(
        search_parser,
        "--headed",
        "--headless",
        dest="headed",
        positive_help="Show the browser window",
        negative_help="Run without showing the browser",
    )
    _add_boolean_pair(
        search_parser,
        "--persistent-context",
        "--ephemeral-context",
        dest="use_persistent_context",
        positive_help="Reuse a persistent browser profile directory",
        negative_help="Use storage_state only instead of a persistent browser profile",
    )
    _add_boolean_pair(
        search_parser,
        "--resume",
        "--fresh-run",
        dest="resume",
        positive_help="Reuse the latest checkpoint for the same query instead of replaying search traffic",
        negative_help="Ignore previous checkpoints and start a brand-new run",
    )
    search_parser.add_argument(
        "--force-detail",
        dest="force_detail",
        action="store_true",
        help="Re-run detail enrichment for checkpointed notes without replaying search",
    )
    search_parser.add_argument(
        "--skip-enriched-detail",
        dest="skip_enriched_detail",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip notes that already have reusable detail fields during resume runs",
    )
    search_parser.add_argument(
        "--history",
        dest="persist_history",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist final records into data/history.sqlite3",
    )
    _add_boolean_pair(
        search_parser,
        "--debug",
        "--no-debug",
        dest="debug",
        positive_help="Enable debug logging",
        negative_help="Disable debug logging",
    )
    _add_boolean_pair(
        search_parser,
        "--save-raw-json",
        "--no-save-raw-json",
        dest="save_raw_json",
        positive_help="Save captured raw responses as JSONL files",
        negative_help="Do not save captured raw responses as JSONL files",
    )
    _add_boolean_pair(
        search_parser,
        "--merged-comments",
        "--no-merged-comments",
        dest="export_merged_comments",
        positive_help="Also export one comment-analysis table joined with note fields",
        negative_help="Do not export the joined comment-analysis table",
    )
    _add_boolean_pair(
        search_parser,
        "--with-comments",
        "--no-comments",
        dest="with_comments",
        positive_help="Collect public comments",
        negative_help="Do not collect comments",
    )
    _add_boolean_pair(
        search_parser,
        "--include-replies",
        "--no-replies",
        dest="include_replies",
        positive_help="Include second-level replies if they appear in public responses",
        negative_help="Do not include second-level replies",
    )
    _add_boolean_pair(
        search_parser,
        "--expand-replies",
        "--no-expand-replies",
        dest="expand_replies",
        positive_help="Click bounded visible reply expansion controls before continuing comment pagination",
        negative_help="Do not click reply expansion controls",
    )
    _add_manual_verification_arguments(search_parser)
    search_parser.set_defaults(
        handler=lambda args: search(args.query, **_search_kwargs_from_args(args))
    )

    batch_parser = subparsers.add_parser(
        "batch",
        help="Run the search workflow for newline-separated keywords",
        description="Run the search workflow for newline-separated keywords.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    batch_parser.add_argument("keywords_file", help="UTF-8 text file with one keyword per line")
    batch_parser.add_argument("--keyword-delay-min", type=float, default=30.0, help="Min delay between keywords")
    batch_parser.add_argument("--keyword-delay-max", type=float, default=60.0, help="Max delay between keywords")
    batch_parser.add_argument("--stop-on-error", action="store_true", help="Stop the whole batch after one keyword fails")
    batch_parser.add_argument("--pages", type=int, default=1, help="Number of scroll batches to collect")
    batch_parser.add_argument("--format", dest="export_format", default="csv", help="csv or excel")
    batch_parser.add_argument("--output", "-o", help="Output file base path prefix")
    batch_parser.add_argument("--search-delay-min", type=float, default=4.0, help="Min delay between search batches")
    batch_parser.add_argument("--search-delay-max", type=float, default=7.0, help="Max delay between search batches")
    batch_parser.add_argument("--detail-delay-min", type=float, default=3.0, help="Min delay between detail requests")
    batch_parser.add_argument("--detail-delay-max", type=float, default=5.0, help="Max delay between detail requests")
    _add_detail_stability_arguments(batch_parser)
    batch_parser.add_argument("--comment-delay-min", type=float, default=4.0, help="Min delay between comment requests")
    batch_parser.add_argument("--comment-delay-max", type=float, default=6.0, help="Max delay between comment requests")
    batch_parser.add_argument("--max-items-per-page", type=int, help="Limit unique notes parsed from each scroll batch")
    batch_parser.add_argument("--max-notes-total", type=int, default=10, help="Stop once this many unique notes have been collected")
    batch_parser.add_argument("--max-comments-per-note", type=int, default=50, help="Max comments to keep for each note when comments are enabled")
    batch_parser.set_defaults(
        detail=False,
        headed=True,
        use_persistent_context=True,
        debug=False,
        save_raw_json=False,
        with_comments=False,
        include_replies=False,
        resume=True,
        force_detail=False,
        skip_enriched_detail=True,
        persist_history=True,
    )
    _add_boolean_pair(
        batch_parser,
        "--detail",
        "--no-detail",
        dest="detail",
        positive_help="Enrich notes via detail pages",
        negative_help="Skip detail page enrichment",
    )
    _add_boolean_pair(
        batch_parser,
        "--headed",
        "--headless",
        dest="headed",
        positive_help="Show the browser window",
        negative_help="Run without showing the browser",
    )
    _add_boolean_pair(
        batch_parser,
        "--persistent-context",
        "--ephemeral-context",
        dest="use_persistent_context",
        positive_help="Reuse a persistent browser profile directory",
        negative_help="Use storage_state only instead of a persistent browser profile",
    )
    _add_boolean_pair(
        batch_parser,
        "--resume",
        "--fresh-run",
        dest="resume",
        positive_help="Reuse checkpoints for each keyword",
        negative_help="Ignore previous checkpoints for each keyword",
    )
    batch_parser.add_argument("--force-detail", dest="force_detail", action="store_true", help="Re-run detail enrichment for checkpointed notes")
    batch_parser.add_argument("--skip-enriched-detail", dest="skip_enriched_detail", action=argparse.BooleanOptionalAction, default=True, help="Skip notes that already have reusable detail fields")
    batch_parser.add_argument("--history", dest="persist_history", action=argparse.BooleanOptionalAction, default=True, help="Persist final records into data/history.sqlite3")
    _add_boolean_pair(
        batch_parser,
        "--debug",
        "--no-debug",
        dest="debug",
        positive_help="Enable debug logging",
        negative_help="Disable debug logging",
    )
    _add_boolean_pair(
        batch_parser,
        "--save-raw-json",
        "--no-save-raw-json",
        dest="save_raw_json",
        positive_help="Save captured raw responses as JSONL files",
        negative_help="Do not save captured raw responses",
    )
    _add_boolean_pair(
        batch_parser,
        "--with-comments",
        "--no-comments",
        dest="with_comments",
        positive_help="Collect public comments",
        negative_help="Do not collect comments",
    )
    _add_boolean_pair(
        batch_parser,
        "--include-replies",
        "--no-replies",
        dest="include_replies",
        positive_help="Include second-level replies",
        negative_help="Do not include second-level replies",
    )
    batch_parser.set_defaults(
        handler=lambda args: batch_search(
            args.keywords_file,
            keyword_delay_min=args.keyword_delay_min,
            keyword_delay_max=args.keyword_delay_max,
            stop_on_error=args.stop_on_error,
            **_search_kwargs_from_args(args),
        )
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
