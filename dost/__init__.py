"""
THE CLAUDE COMPANY — Dost Interface package.

Re-exports the main dost module for convenient importing.
"""

from dost.dost_main import (
    dost_respond,
    dost_greeting,
    generate_daily_briefing,
    provider_health,
    build_context,
    doctor,
    MEMORY,
    dispatch_prompt_to_fleet,
    dispatch_debate_to_fleet,
    list_recent_dost_tasks,
    search_history,
    search_history_regex,
    synthesis_detail,
    export_results,
    weekly_findings_digest,
    load_template,
    review_findings,
    dispatch_prompt_to_fleet as dispatch,
    companion_respond,
    build_context as build_context_builder,
)

__all__ = [
    "dost_respond",
    "dost_greeting",
    "generate_daily_briefing",
    "provider_health",
    "build_context",
    "doctor",
    "MEMORY",
    "dispatch_prompt_to_fleet",
    "dispatch_debate_to_fleet",
    "list_recent_dost_tasks",
    "search_history",
    "search_history_regex",
    "synthesis_detail",
    "export_results",
    "auto_archive_findings",
    "weekly_findings_digest",
    "load_template",
    "review_findings",
    "dispatch",
    "companion_respond",
    "build_context_builder",
]