"""
Shared utility functions for AI-Office packages.
"""
from .helpers import (
    generate_id,
    slugify,
    parse_duration,
    format_duration,
    deep_merge,
    flatten_dict,
    retry,
    async_retry,
)
from .datetime import utc_now, iso_now, parse_iso_datetime
from .files import ensure_dir, read_json, write_json, read_yaml, write_yaml

__all__ = [
    "generate_id",
    "slugify", 
    "parse_duration",
    "format_duration",
    "deep_merge",
    "flatten_dict",
    "retry",
    "async_retry",
    "utc_now",
    "iso_now",
    "parse_iso_datetime",
    "ensure_dir",
    "read_json",
    "write_json",
    "read_yaml",
    "write_yaml",
]