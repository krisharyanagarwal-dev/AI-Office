#!/usr/bin/env python3
"""THE CLAUDE COMPANY — Dost State Backup.

Copies ~/.openclaw/office_pnl.json, ~/.openclaw/jev-dispatcher.log, and the
findings store to ~/.openclaw/backups/YYYY-MM-DD/ with rotation (keep last 7
days).

Paper-only, read-only. No live orders ever.
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

OPENCLAW_DIR = Path.home() / ".openclaw"
BACKUP_DIR = OPENCLAW_DIR / "backups"
RETENTION_DAYS = 7

# Sources to back up: office P&L ledger, dispatcher log, findings store.
SOURCES = [
    OPENCLAW_DIR / "office_pnl.json",
    OPENCLAW_DIR / "jev-dispatcher.log",
    Path("/Users/aryanagarwal/Documents/polymarket/research/findings.json"),
]


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts}: {msg}", flush=True)


def _rotate() -> None:
    """Remove backup directories older than RETENTION_DAYS."""
    if not BACKUP_DIR.exists():
        return
    today = datetime.now(timezone.utc).date()
    for day_dir in sorted(BACKUP_DIR.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - day).days >= RETENTION_DAYS:
            shutil.rmtree(day_dir, ignore_errors=True)
            log(f"Rotated out old backup: {day_dir.name}")


def backup() -> int:
    """Copy the state files into a dated backup dir. Returns files copied."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = BACKUP_DIR / today
    dest.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in SOURCES:
        if not src.exists():
            log(f"SKIP (missing): {src}")
            continue
        try:
            shutil.copy2(src, dest / src.name)
            copied += 1
            log(f"Backed up {src} -> {dest / src.name}")
        except OSError as e:
            log(f"ERROR copying {src}: {e}")

    _rotate()
    log(f"Backup complete: {copied} file(s) copied to {dest}")
    return copied


def main() -> None:
    backup()


if __name__ == "__main__":
    main()
