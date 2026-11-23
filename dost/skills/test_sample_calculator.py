"""Tests for sample_calculator skill."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import sample_calculator


class TestSampleCalculator:
    """Tests for sample_calculator skill."""

    def test_manifest_exists(self):
        """Skill has valid manifest."""
        assert hasattr(sample_calculator, "SKILL_MANIFEST")
        manifest = sample_calculator.SKILL_MANIFEST
        assert manifest["name"] == "sample_calculator"
        assert manifest["version"] == "1.0.0"
        assert "entry_point" in manifest
        assert manifest["entry_point"] == "main"

    def test_main_entry_point(self):
        """Main entry point exists and returns valid result."""
        result = sample_calculator.main()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_add_operation(self):
        """Test addition."""
        result = sample_calculator.main(operation="add", a=10, b=5)
        assert result["ok"] is True
        assert result["data"]["result"] == 15

    def test_subtract_operation(self):
        """Test subtraction."""
        result = sample_calculator.main(operation="subtract", a=10, b=5)
        assert result["ok"] is True
        assert result["data"]["result"] == 5

    def test_multiply_operation(self):
        """Test multiplication."""
        result = sample_calculator.main(operation="multiply", a=10, b=5)
        assert result["ok"] is True
        assert result["data"]["result"] == 50

    def test_divide_operation(self):
        """Test division."""
        result = sample_calculator.main(operation="divide", a=10, b=5)
        assert result["ok"] is True
        assert result["data"]["result"] == 2.0

    def test_divide_by_zero(self):
        """Test division by zero handling."""
        result = sample_calculator.main(operation="divide", a=10, b=0)
        assert result["ok"] is False
        assert "Division by zero" in result["error"]

    def test_unknown_operation(self):
        """Test unknown operation handling."""
        result = sample_calculator.main(operation="modulo", a=10, b=5)
        assert result["ok"] is False
        assert "Unknown operation" in result["error"]

    def test_missing_arguments(self):
        """Test missing arguments handling."""
        result = sample_calculator.main(operation="add", a=10)
        assert result["ok"] is False
        assert "Missing required arguments" in result["error"]

    def test_negative_numbers_allowed(self):
        """Test negative numbers allowed by default."""
        result = sample_calculator.main(operation="add", a=-10, b=5)
        assert result["ok"] is True
        assert result["data"]["result"] == -5

    def test_negative_numbers_disallowed(self):
        """Test negative numbers disallowed via config."""
        result = sample_calculator.main(
            operation="add",
            a=-10,
            b=5,
            config=sample_calculator.SkillConfig(allow_negative=False),
        )
        assert result["ok"] is False
        assert "Negative numbers not allowed" in result["error"]

    def test_precision_config(self):
        """Test precision configuration."""
        result = sample_calculator.main(
            operation="divide",
            a=10,
            b=3,
            config=sample_calculator.SkillConfig(precision=4),
        )
        assert result["ok"] is True
        assert result["data"]["result"] == 3.3333

    def test_skill_validation(self):
        """Skill passes validation."""
        from skills.registry import get_registry
        registry = get_registry()
        validation = registry.validate_skill("sample_calculator")
        assert validation["valid"] is True
        assert len(validation["issues"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])