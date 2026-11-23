"""
Shared database connection management with thread-local connections,
transaction support, and connection pooling.
"""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json


class DatabaseConnection:
    """Manages SQLite database connections with thread-local storage."""
    
    def __init__(self, db_path: Union[str, Path], migrations_dir: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path)
        self.migrations_dir = Path(migrations_dir) if migrations_dir else None
        self._local = threading.local()
        self._initialized = False
    
    def get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn.execute("PRAGMA journal_mode = WAL")
            
            if not self._initialized and self.migrations_dir:
                self._run_migrations()
                self._initialized = True
        
        return self._local.conn
    
    def _run_migrations(self):
        """Run database migrations from migrations directory."""
        if not self.migrations_dir or not self.migrations_dir.exists():
            return
        
        conn = self._local.conn
        for migration_file in sorted(self.migrations_dir.glob("*.sql")):
            with open(migration_file) as f:
                sql = f.read()
            conn.executescript(sql)
        conn.commit()
    
    @contextmanager
    def transaction(self):
        """Transaction context manager."""
        conn = self.get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def close(self):
        """Close the thread-local connection."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
    
    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query and return cursor."""
        return self.get_conn().execute(query, params)
    
    def fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Execute query and fetch one row."""
        return self.get_conn().execute(query, params).fetchone()
    
    def fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Execute query and fetch all rows."""
        return self.get_conn().execute(query, params).fetchall()


# Default database instance (can be overridden per package)
_default_db: Optional[DatabaseConnection] = None


def get_database(db_path: Optional[Union[str, Path]] = None,
                 migrations_dir: Optional[Union[str, Path]] = None) -> DatabaseConnection:
    """Get or create the default database connection."""
    global _default_db
    if _default_db is None:
        if db_path is None:
            db_path = Path.home() / "AI-Office" / "data" / "office.db"
        if migrations_dir is None:
            migrations_dir = Path(__file__).parent.parent.parent / "migrations"
        _default_db = DatabaseConnection(db_path, migrations_dir)
    return _default_db


def get_connection() -> sqlite3.Connection:
    """Get the default database connection."""
    return get_database().get_conn()


@contextmanager
def transaction():
    """Transaction context manager using default database."""
    with get_database().transaction() as conn:
        yield conn


def execute(query: str, params: tuple = ()) -> sqlite3.Cursor:
    """Execute a query using default database."""
    return get_database().execute(query, params)


def fetchone(query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    """Fetch one row using default database."""
    return get_database().fetchone(query, params)


def fetchall(query: str, params: tuple = ()) -> List[sqlite3.Row]:
    """Fetch all rows using default database."""
    return get_database().fetchall(query, params)


def init_database(db_path: Union[str, Path], migrations_dir: Optional[Union[str, Path]] = None) -> DatabaseConnection:
    """Initialize a new database connection (for testing or alternate DBs)."""
    return DatabaseConnection(db_path, migrations_dir)