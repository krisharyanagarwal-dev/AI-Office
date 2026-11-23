"""
File I/O utilities for JSON, YAML, and directory management.
"""

import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, Union


def ensure_dir(path: Union[str, Path]) -> Path:
    """Ensure directory exists, create if needed."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Union[str, Path], default: Any = None) -> Any:
    """Read JSON file, return default if not found or invalid."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def write_json(path: Union[str, Path], data: Any, indent: int = 2) -> bool:
    """Write data to JSON file."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=indent, default=str)
        return True
    except (IOError, TypeError):
        return False


def read_yaml(path: Union[str, Path], default: Any = None) -> Any:
    """Read YAML file, return default if not found or invalid."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, IOError):
        return default


def write_yaml(path: Union[str, Path], data: Any) -> bool:
    """Write data to YAML file."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return True
    except (IOError, TypeError):
        return False


def read_text(path: Union[str, Path], default: str = "") -> str:
    """Read text file."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return path.read_text()
    except IOError:
        return default


def write_text(path: Union[str, Path], content: str) -> bool:
    """Write text to file."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return True
    except IOError:
        return False


def list_files(directory: Union[str, Path], pattern: str = "*", recursive: bool = False) -> list:
    """List files matching pattern."""
    directory = Path(directory)
    if not directory.exists():
        return []
    if recursive:
        return list(directory.rglob(pattern))
    return list(directory.glob(pattern))


def get_file_size(path: Union[str, Path]) -> int:
    """Get file size in bytes."""
    path = Path(path)
    if path.exists() and path.is_file():
        return path.stat().st_size
    return 0


def copy_file(src: Union[str, Path], dst: Union[str, Path]) -> bool:
    """Copy file from src to dst."""
    import shutil
    try:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except (IOError, OSError):
        return False