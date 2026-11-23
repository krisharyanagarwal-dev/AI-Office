"""
Base repository class for common database operations.
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, fields
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic
import sqlite3
import json

from .connection import DatabaseConnection, transaction


T = TypeVar('T')


@dataclass
class BaseRecord:
    """Base class for database records."""
    id: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, handling JSON fields."""
        result = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, (dict, list)):
                result[field.name] = json.dumps(value)
            else:
                result[field.name] = value
        return result
    
    @classmethod
    def from_row(cls: Type[T], row: sqlite3.Row) -> T:
        """Create instance from database row."""
        data = dict(row)
        # Parse JSON fields
        for field in fields(cls):
            if field.name in data and isinstance(data[field.name], str):
                try:
                    data[field.name] = json.loads(data[field.name])
                except (json.JSONDecodeError, TypeError):
                    pass
        return cls(**data)


class BaseRepository(Generic[T], ABC):
    """Base repository with common CRUD operations."""
    
    def __init__(self, db: DatabaseConnection, table_name: str, record_class: Type[T]):
        self.db = db
        self.table_name = table_name
        self.record_class = record_class
    
    @abstractmethod
    def _get_columns(self) -> List[str]:
        """Return list of column names for this table."""
        pass
    
    @abstractmethod
    def _get_create_sql(self) -> str:
        """Return SQL for creating the table."""
        pass
    
    def create_table(self):
        """Create the table if it doesn't exist."""
        with self.db.transaction() as conn:
            conn.execute(self._get_create_sql())
    
    def create(self, record: T) -> T:
        """Insert a new record."""
        data = record.to_dict()
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" * len(data))
        values = tuple(data.values())
        
        with self.db.transaction() as conn:
            conn.execute(
                f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders})",
                values
            )
        return record
    
    def get(self, id: str) -> Optional[T]:
        """Get record by ID."""
        row = self.db.fetchone(
            f"SELECT * FROM {self.table_name} WHERE id = ?",
            (id,)
        )
        if row:
            return self.record_class.from_row(row)
        return None
    
    def update(self, id: str, **kwargs) -> bool:
        """Update record fields."""
        # Filter out None values and id
        updates = {k: v for k, v in kwargs.items() if v is not None and k != 'id'}
        if not updates:
            return False
        
        # Convert complex types to JSON
        for key, value in updates.items():
            if isinstance(value, (dict, list)):
                updates[key] = json.dumps(value)
        
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = tuple(updates.values()) + (id,)
        
        with self.db.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE {self.table_name} SET {set_clause} WHERE id = ?",
                values
            )
            return cursor.rowcount > 0
    
    def delete(self, id: str) -> bool:
        """Delete a record."""
        with self.db.transaction() as conn:
            cursor = conn.execute(
                f"DELETE FROM {self.table_name} WHERE id = ?",
                (id,)
            )
            return cursor.rowcount > 0
    
    def list(self, 
             where: Optional[str] = None,
             params: tuple = (),
             order_by: Optional[str] = None,
             limit: int = 100,
             offset: int = 0) -> List[T]:
        """List records with optional filtering."""
        query = f"SELECT * FROM {self.table_name}"
        if where:
            query += f" WHERE {where}"
        if order_by:
            query += f" ORDER BY {order_by}"
        query += f" LIMIT ? OFFSET ?"
        
        params = params + (limit, offset)
        rows = self.db.fetchall(query, params)
        return [self.record_class.from_row(row) for row in rows]
    
    def count(self, where: Optional[str] = None, params: tuple = ()) -> int:
        """Count records matching criteria."""
        query = f"SELECT COUNT(*) FROM {self.table_name}"
        if where:
            query += f" WHERE {where}"
        row = self.db.fetchone(query, params)
        return row[0] if row else 0
    
    def exists(self, id: str) -> bool:
        """Check if record exists."""
        row = self.db.fetchone(
            f"SELECT 1 FROM {self.table_name} WHERE id = ?",
            (id,)
        )
        return row is not None