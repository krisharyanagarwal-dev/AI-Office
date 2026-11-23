"""Tests for compound_interest skill."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import compound_interest


class TestCompoundInterest:
    """Tests for compound_interest skill."""

    def test_manifest_exists(self):
        """Skill has valid manifest."""
        assert hasattr(compound_interest, "SKILL_MANIFEST")
        manifest = compound_interest.SKILL_MANIFEST
        assert manifest["name"] == "compound_interest"
        assert manifest["version"] == "1.0.0"
        assert "entry_point" in manifest

    def test_main_entry_point(self):
        """Main entry point exists and returns valid result."""
        result = compound_interest.main()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_main_with_config(self):
        """Main works with config."""
        @pytest.fixture
        def config():
            return compound_interest.SkillConfig()

    def test_skill_validation(self):
        """Skill passes validation."""
        from skills.registry import get_registry
        registry = get_registry()
        validation = registry.validate_skill("compound_interest")
        assert "valid" in validation
