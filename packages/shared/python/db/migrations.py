"""
Database migration utilities for schema versioning.
"""

import sqlite3
from pathlib import Path
from typing import List, Optional


class MigrationRunner:
    """Runs database migrations from a directory of SQL files."""
    
    def __init__(self, migrations_dir: Union[str, Path]):
        self.migrations_dir = Path(migrations_dir)
        self._applied: set = set()
    
    def run(self, conn: sqlite3.Connection) -> List[str]:
        """Run all pending migrations. Returns list of applied migration names."""
        if not self.migrations_dir.exists():
            return []
        
        # Create migrations tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Get already applied migrations
        cursor = conn.execute("SELECT name FROM schema_migrations")
        self._applied = {row[0] for row in cursor.fetchall()}
        
        applied = []
        for migration_file in sorted(self.migrations_dir.glob("*.sql")):
            name = migration_file.stem
            if name not in self._applied:
                with open(migration_file) as f:
                    sql = f.read()
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)",
                    (name,)
                )
                applied.append(name)
        
        conn.commit()
        return applied
    
    def get_applied(self) -> List[str]:
        """Get list of applied migration names."""
        return sorted(self._applied)
    
    def get_pending(self) -> List[str]:
        """Get list of pending migration names."""
        if not self.migrations_dir.exists():
            return []
        all_migrations = {f.stem for f in self.migrations_dir.glob("*.sql")}
        return sorted(all_migrations - self._applied)


def run_migrations(conn: sqlite3.Connection, migrations_dir: Union[str, Path]) -> List[str]:
    """Run migrations using a MigrationRunner instance."""
    runner = MigrationRunner(migrations_dir)
    return runner.run(conn)


# Example migration template
MIGRATION_TEMPLATE = """
-- Migration: {name}
-- Description: {description}

-- UP
{up_sql}

-- DOWN (for rollback)
-- {down_sql}
"""