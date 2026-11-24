#!/usr/bin/env python3
"""
Inbox Classifier — Classifies _office/inbox items per Section 2 of master prompt

Classification Types:
- INFORMATIONAL: Status updates, documentation, reading only
- ACTIONABLE: Tasks requiring execution
- AWAITING_APPROVAL: Pending human review/decision
- IN_PROGRESS: Active work items with partial completion
- RESOLVED: Completed items
- DUPLICATE: Redundant tasks
- BLOCKED: Cannot proceed without external inputs

Usage:
    python classify_inbox.py --sample 5
    python classify_inbox.py --all
    python classify_inbox.py --output classified-inbox-items.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

INBOX_DIR = Path.home() / "_office" / "inbox"
CLASSIFICATIONS: Dict[str, str] = {}


def get_file_list(limit: Optional[int] = None) -> List[Path]:
    """Get sorted list of inbox files, most recently modified first."""
    if not INBOX_DIR.exists():
        print(f"ERROR: Inbox directory not found: {INBOX_DIR}")
        sys.exit(1)

    files = sorted(
        [f for f in INBOX_DIR.iterdir() if f.is_file() and f.suffix in [".md", ".txt"]],
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )
    return files[:limit] if limit else files


def classify_content(content: str, filename: str) -> str:
    """Classify inbox item based on content analysis."""
    content_lower = content.lower()
    filename_lower = filename.lower()

    # Check for resolved/checked items
    if re.search(r'\[x\]|resolved|completed|done', content_lower):
        return "RESOLVED"

    # Check for blocked items
    if re.search(r'blocked|cannot proceed|waiting on|need.*input', content_lower):
        return "BLOCKED"

    # Check for awaiting approval
    if re.search(r'awaiting|pending approval|need.*review|approval', content_lower):
        return "AWAITING_APPROVAL"

    # Check for duplicate indicators
    if re.search(r'duplicate|repeat.*task|same.*as.*previous', content_lower):
        return "DUPLICATE"

    # Check for in-progress items
    if re.search(r'\[ \]|in progress|working on|actively.*doing', content_lower):
        return "IN_PROGRESS"

    # Check for actionable items (standing duty, task, work)
    if re.search(r'standing duty|task|work on|implement|fix|analyze|review', content_lower):
        return "ACTIONABLE"

    # Check for informational content (status update, alert, report)
    if re.search(r'alert|status|update|report|monitoring|observing', content_lower):
        return "INFORMATIONAL"

    # Default to informational for documentation/README-like files
    if re.search(r'readme|readme|docs?/|doc/', filename_lower):
        return "INFORMATIONAL"

    # Default classification based on file patterns
    if re.search(r'verifier|quality|check|audit|review', filename_lower):
        return "ACTIONABLE"

    if re.search(r'dispatcher|rout|dispatch', filename_lower):
        return "ACTIONABLE"

    if re.search(r'assistant|writer|draft|create', filename_lower):
        return "INFORMATIONAL"

    return "INFORMATIONAL"


def classify_file(filepath: Path) -> Dict:
    """Classify a single inbox file."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "file": filepath.name,
            "classification": "ERROR",
            "error": str(e)
        }

    classification = classify_content(content, filepath.name)

    return {
        "file": filepath.name,
        "classification": classification,
        "department": _extract_department(content),
        "tags": _extract_tags(content),
        "status": _extract_status(content),
        "timestamp": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()
    }


def _extract_department(content: str) -> str:
    """Extract department from content (if mentioned)."""
    match = re.search(r'\((\w+)\)', content.split('\n')[0] if '\n' in content else content[:100])
    return match.group(1).lower() if match else "unknown"


def _extract_tags(content: str) -> List[str]:
    """Extract tags from content."""
    tags = []

    # Extract from filename patterns
    filename_lower = content[:100].lower() if len(content) < 100 else content[:100].lower()

    if "standing duty" in content.lower():
        tags.append("standing-duty")
    if "alert" in content.lower():
        tags.append("alert")
    if "swap" in content.lower():
        tags.append("system")
    if "report" in content.lower():
        tags.append("report")
    if "review" in content.lower():
        tags.append("review")

    return tags


def _extract_status(content: str) -> str:
    """Extract status from checkbox if present."""
    # Check first line for checkbox
    first_line = content.split('\n')[0] if content else ""

    if '[x]' in first_line:
        return "completed"
    elif '[ ]' in first_line:
        return "pending"

    # Check for status patterns
    if re.search(r'\[(.*?)\]', first_line):
        match = re.search(r'\[(.*?)\]', first_line)
        if match:
            return match.group(1).lower().replace(" ", "_") or "pending"

    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify _office/inbox items for OPENALICE integration"
    )
    parser.add_argument(
        "--sample", "-s",
        type=int,
        help="Number of most recent files to classify"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Classify all inbox files"
    )
    parser.add_argument(
        "--output", "-o",
        default="classified-inbox-items.json",
        help="Output JSON file (default: classified-inbox-items.json)"
    )
    parser.add_argument(
        "--department", "-d",
        help="Filter by department"
    )
    parser.add_argument(
        "--classification", "-c",
        help="Filter by classification type"
    )

    args = parser.parse_args()

    # Get file list
    if args.all:
        files = get_file_list()
    elif args.sample:
        files = get_file_list(args.sample)
    else:
        files = get_file_list(5)  # Default to 5 samples

    if not files:
        print("No inbox files found.")
        return

    print(f"Classifying {len(files)} inbox items...\n")

    # Classify each file
    results = []
    for filepath in files:
        result = classify_file(filepath)
        results.append(result)

        # Display result
        print(f"File: {result['file']}")
        print(f"  Classification: {result['classification']}")
        print(f"  Department: {result['department']}")
        print(f"  Status: {result['status']}")
        if result.get('tags'):
            print(f"  Tags: {', '.join(result['tags'])}")
        print()

    # Apply filters if specified
    if args.department:
        results = [r for r in results if r.get('department') == args.department.lower()]
    if args.classification:
        results = [r for r in results if r.get('classification') == args.classification.upper()]

    # Write output
    output_path = Path(args.output)
    output_data = {
        "generated_at": datetime.now().isoformat(),
        "total_classified": len(results),
        "classifications": results,
        "summary": {}
    }

    # Build summary by classification
    for r in results:
        cls = r['classification']
        output_data['summary'][cls] = output_data['summary'].get(cls, 0) + 1

    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"\nResults written to: {output_path}")
    print(f"\nSummary:")
    for cls, count in output_data['summary'].items():
        print(f"  {cls}: {count}")


if __name__ == "__main__":
    main()