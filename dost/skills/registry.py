"""Skill Registry for Dost.

Manages self-improving skills with JSON manifests:
- Auto-discovers skills in dost/skills/*.py
- Validates: interface, test, config, deploy
- Version tracking and dependency resolution
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_pkg.unified import get_unified_memory


SKILLS_DIR = Path(__file__).resolve().parent
MANIFEST_FILE = SKILLS_DIR / "registry.json"


@dataclass
class SkillManifest:
    """Skill manifest with metadata."""
    name: str
    version: str
    description: str
    author: str = "dost"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    dependencies: list[str] = field(default_factory=list)
    entry_point: str = "main"  # function name
    module_file: str = ""
    test_file: str = ""
    config_schema: dict = field(default_factory=dict)
    default_config: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    # Runtime state
    last_test_run: Optional[str] = None
    last_test_passed: Optional[bool] = None
    deploy_status: str = "pending"  # pending, deployed, failed
    deploy_ts: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillManifest":
        return cls(**data)


class SkillRegistry:
    """Registry for managing Dost skills."""

    def __init__(self):
        self.skills: dict[str, SkillManifest] = {}
        self.memory = get_unified_memory()
        self._load_registry()

    def _load_registry(self) -> None:
        """Load registry from disk."""
        if MANIFEST_FILE.exists():
            try:
                data = json.loads(MANIFEST_FILE.read_text())
                for name, skill_data in data.items():
                    self.skills[name] = SkillManifest.from_dict(skill_data)
            except (json.JSONDecodeError, TypeError):
                self.skills = {}

    def _save_registry(self) -> None:
        """Save registry to disk."""
        data = {name: skill.to_dict() for name, skill in self.skills.items()}
        MANIFEST_FILE.write_text(json.dumps(data, indent=2))

    def discover_skills(self) -> list[str]:
        """Auto-discover skills in skills directory."""
        discovered = []
        for py_file in SKILLS_DIR.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            if py_file.name in ("registry.py", "generator.py", "tester.py", "deployer.py", "test_registry.py"):
                continue

            # Try to load module and extract manifest
            module_name = py_file.stem
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    # Add to sys.modules BEFORE exec to allow dataclass to find module
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    # Check for SKILL_MANIFEST attribute
                    if hasattr(module, "SKILL_MANIFEST"):
                        manifest = module.SKILL_MANIFEST
                        if isinstance(manifest, dict):
                            manifest = SkillManifest(**manifest)
                        manifest.module_file = py_file.name
                        # Look for test file
                        test_file = SKILLS_DIR / f"test_{module_name}.py"
                        if test_file.exists():
                            manifest.test_file = test_file.name
                        self.register(manifest)
                        discovered.append(manifest.name)
            except Exception as e:
                print(f"[registry] Failed to load {py_file.name}: {e}")
            finally:
                # Clean up sys.modules
                sys.modules.pop(module_name, None)

        return discovered

    def register(self, manifest: SkillManifest | dict) -> None:
        """Register or update a skill."""
        if isinstance(manifest, dict):
            manifest = SkillManifest(**manifest)
        manifest.updated_at = datetime.now(timezone.utc).isoformat()
        self.skills[manifest.name] = manifest
        self._save_registry()

    def unregister(self, name: str) -> bool:
        """Unregister a skill."""
        if name in self.skills:
            del self.skills[name]
            self._save_registry()
            return True
        return False

    def get(self, name: str) -> Optional[SkillManifest]:
        """Get skill manifest by name."""
        return self.skills.get(name)

    def list_skills(self, enabled_only: bool = False) -> list[SkillManifest]:
        """List all registered skills."""
        skills = list(self.skills.values())
        if enabled_only:
            skills = [s for s in skills if s.enabled]
        return sorted(skills, key=lambda s: s.name)

    def enable(self, name: str) -> bool:
        """Enable a skill."""
        if name in self.skills:
            self.skills[name].enabled = True
            self._save_registry()
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a skill."""
        if name in self.skills:
            self.skills[name].enabled = False
            self._save_registry()
            return True
        return False

    def update_test_result(self, name: str, passed: bool) -> None:
        """Update test result for a skill."""
        if name in self.skills:
            self.skills[name].last_test_run = datetime.now(timezone.utc).isoformat()
            self.skills[name].last_test_passed = passed
            self._save_registry()

    def update_deploy_status(self, name: str, status: str) -> None:
        """Update deploy status for a skill."""
        if name in self.skills:
            self.skills[name].deploy_status = status
            self.skills[name].deploy_ts = datetime.now(timezone.utc).isoformat()
            self._save_registry()

    def get_skill_module(self, name: str) -> Optional[Any]:
        """Load and return skill module."""
        skill = self.get(name)
        if not skill:
            return None
        try:
            module_path = SKILLS_DIR / skill.module_file
            spec = importlib.util.spec_from_file_location(name, module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                # Add to sys.modules BEFORE exec to allow dataclass to find module
                sys.modules[name] = module
                module.__module__ = name
                spec.loader.exec_module(module)
                return module
        except Exception as e:
            print(f"[registry] Failed to load module for {name}: {e}")
        finally:
            # Clean up sys.modules
            sys.modules.pop(name, None)
        return None

    def run_skill(self, name: str, *args, **kwargs) -> Any:
        """Run a skill's entry point."""
        module = self.get_skill_module(name)
        if not module:
            raise ValueError(f"Skill {name} not found or failed to load")

        skill = self.get(name)
        entry_point = skill.entry_point if skill else "main"

        if not hasattr(module, entry_point):
            raise ValueError(f"Skill {name} has no entry point '{entry_point}'")

        func = getattr(module, entry_point)
        return func(*args, **kwargs)

    def validate_skill(self, name: str) -> dict[str, Any]:
        """Validate a skill has required components."""
        skill = self.get(name)
        if not skill:
            return {"valid": False, "error": "Skill not registered"}

        issues = []

        # Check module file
        module_path = SKILLS_DIR / skill.module_file
        if not module_path.exists():
            issues.append(f"Module file not found: {skill.module_file}")

        # Check test file
        if skill.test_file:
            test_path = SKILLS_DIR / skill.test_file
            if not test_path.exists():
                issues.append(f"Test file not found: {skill.test_file}")
        else:
            issues.append("No test file specified")

        # Check entry point exists
        module = self.get_skill_module(name)
        if module and not hasattr(module, skill.entry_point):
            issues.append(f"Entry point '{skill.entry_point}' not found in module")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
        }


# Global instance
_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """Get global skill registry instance."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry