"""Dost Skill: Sample Calculator

Simple calculator skill demonstrating the skill system.
Auto-generated template with full manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SkillConfig:
    """Configuration for sample_calculator skill."""
    precision: int = 2
    allow_negative: bool = True


SKILL_MANIFEST = {
    "name": "sample_calculator",
    "version": "1.0.0",
    "description": "Simple calculator skill for basic arithmetic operations",
    "author": "dost-generator",
    "dependencies": [],
    "entry_point": "main",
    "module_file": "sample_calculator.py",
    "test_file": "test_sample_calculator.py",
    "config_schema": {
        "type": "object",
        "properties": {
            "precision": {"type": "integer", "minimum": 0, "maximum": 10},
            "allow_negative": {"type": "boolean"},
        },
    },
    "default_config": {
        "precision": 2,
        "allow_negative": True,
    },
    "tags": ["math", "utility", "demo"],
    "enabled": True,
}


def main(config: Optional[SkillConfig] = None, **kwargs) -> dict:
    """Main entry point for sample_calculator skill.

    Args:
        config: Skill configuration
        **kwargs: Operation arguments:
            - operation: "add", "subtract", "multiply", "divide"
            - a: first number
            - b: second number

    Returns:
        Result dictionary with 'ok', 'data', or 'error'
    """
    try:
        if config is None:
            config = SkillConfig()

        operation = kwargs.get("operation")
        a = kwargs.get("a")
        b = kwargs.get("b")

        if operation is None or a is None or b is None:
            return {
                "ok": False,
                "error": "Missing required arguments: operation, a, b",
            }

        if not config.allow_negative and (a < 0 or b < 0):
            return {
                "ok": False,
                "error": "Negative numbers not allowed",
            }

        result = None
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            if b == 0:
                return {"ok": False, "error": "Division by zero"}
            result = a / b
        else:
            return {"ok": False, "error": f"Unknown operation: {operation}"}

        # Apply precision
        if isinstance(result, float):
            result = round(result, config.precision)

        return {
            "ok": True,
            "data": {
                "operation": operation,
                "a": a,
                "b": b,
                "result": result,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    # Allow running directly for testing
    import sys
    result = main(operation="add", a=10, b=5)
    print(json.dumps(result, indent=2))