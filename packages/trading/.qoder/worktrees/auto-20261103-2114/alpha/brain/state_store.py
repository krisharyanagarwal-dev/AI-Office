"""
State Store - Persistence layer for system state
"""
import asyncio
import json
import sqlite3
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass, asdict
import time

logger = logging.getLogger(__name__)


@dataclass
class StateRecord:
    key: str
    value: str
    timestamp: float
    category: str


class StateStore:
    """Persistent state storage using SQLite"""
    
    def __init__(self, config: dict):
        self.config = config
        self.db_path = config.get('path', './data/state.db')
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
    
    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                timestamp REAL NOT NULL,
                category TEXT DEFAULT 'general'
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_category ON state(category)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp ON state(timestamp)
        """)
        self._conn.commit()
    
    async def initialize(self):
        pass
    
    def set(self, key: str, value: any, category: str = 'general'):
        """Set a value"""
        value_str = json.dumps(value) if not isinstance(value, str) else value
        timestamp = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO state (key, value, timestamp, category) VALUES (?, ?, ?, ?)",
            (key, value_str, timestamp, category)
        )
        self._conn.commit()
    
    def get(self, key: str, default: Any = None, category: str = 'general') -> Any:
        """Get a value"""
        cursor = self._conn.execute(
            "SELECT value FROM state WHERE key = ? AND category = ?",
            (key, category)
        )
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row[0])
            except:
                return row[0]
        return None
    
    def delete(self, key: str, category: str = 'general'):
        self._conn.execute("DELETE FROM state WHERE key = ? AND category = ?", (key, category))
        self._conn.commit()
    
    def get_all(self, category: Optional[str] = None) -> Dict:
        if category:
            cursor = self._conn.execute("SELECT key, value FROM state WHERE category = ?", (category,))
        else:
            cursor = self._conn.execute("SELECT key, value FROM state")
        result = {}
        for row in cursor.fetchall():
            try:
                result[row[0]] = json.loads(row[1])
            except:
                result[row[0]] = row[1]
        return result
    
    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
    
    async def close(self):
        self.close()
