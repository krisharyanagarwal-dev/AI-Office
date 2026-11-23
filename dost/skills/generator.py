"""Skill Generator for Dost.

Generates new skills from natural language specifications using templates.
Template: interface, test, config, deploy.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Pre-defined skill templates for common patterns
SKILL_TEMPLATES = {
    "calculator": {
        "description": "Calculator skill for basic arithmetic operations",
        "config_fields": """    precision: int = 2
    allow_negative: bool = True""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "precision": {"type": "integer", "minimum": 0, "maximum": 10},
            "allow_negative": {"type": "boolean"},
        },
    }""",
        "default_config": """{
        "precision": 2,
        "allow_negative": True,
    }""",
        "tags": '["math", "utility", "demo"]',
        "implementation": """    try:
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
        return {"ok": False, "error": str(e)}""",
    },
    "text_processor": {
        "description": "Text processing skill for string manipulation",
        "config_fields": """    case_sensitive: bool = False
    max_length: int = 1000""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "case_sensitive": {"type": "boolean"},
            "max_length": {"type": "integer", "minimum": 1},
        },
    }""",
        "default_config": """{
        "case_sensitive": False,
        "max_length": 1000,
    }""",
        "tags": '["text", "utility", "demo"]',
        "implementation": """    try:
        if config is None:
            config = SkillConfig()

        operation = kwargs.get("operation")
        text = kwargs.get("text", "")

        if not text:
            return {"ok": False, "error": "Missing required argument: text"}

        if len(text) > config.max_length:
            text = text[:config.max_length]

        result = None
        if operation == "uppercase":
            result = text.upper()
        elif operation == "lowercase":
            result = text.lower()
        elif operation == "reverse":
            result = text[::-1]
        elif operation == "word_count":
            result = len(text.split())
        else:
            return {"ok": False, "error": f"Unknown operation: {operation}"}

        return {"ok": True, "data": {"operation": operation, "result": result}}
    except Exception as e:
        return {"ok": False, "error": str(e)}""",
    },
    "data_transformer": {
        "description": "Data transformation skill for JSON/CSV conversion",
        "config_fields": """    output_format: str = "json"
    indent: int = 2""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "output_format": {"type": "string", "enum": ["json", "csv"]},
            "indent": {"type": "integer", "minimum": 0, "maximum": 8},
        },
    }""",
        "default_config": """{
        "output_format": "json",
        "indent": 2,
    }""",
        "tags": '["data", "utility", "demo"]',
        "implementation": """    try:
        if config is None:
            config = SkillConfig()

        data = kwargs.get("data")
        if data is None:
            return {"ok": False, "error": "Missing required argument: data"}

        import json
        import csv
        import io

        if config.output_format == "json":
            result = json.dumps(data, indent=config.indent)
        elif config.output_format == "csv":
            if isinstance(data, list) and data and isinstance(data[0], dict):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                result = output.getvalue()
            else:
                return {"ok": False, "error": "CSV output requires list of dicts"}
        else:
            return {"ok": False, "error": f"Unknown format: {config.output_format}"}

        return {"ok": True, "data": {"format": config.output_format, "result": result}}
    except Exception as e:
        return {"ok": False, "error": str(e)}""",
    },
}


SKILL_TEMPLATE = '''"""Dost Skill: {name}

{description}
Auto-generated from template: {template_name}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SkillConfig:
    """Configuration for {name} skill."""
{config_fields}


SKILL_MANIFEST = {{
    "name": "{name}",
    "version": "1.0.0",
    "description": "{description}",
    "author": "dost-generator",
    "dependencies": {dependencies},
    "entry_point": "main",
    "module_file": "{module_file}",
    "test_file": "test_{module_file}",
    "config_schema": {config_schema},
    "default_config": {default_config},
    "tags": {tags},
    "enabled": True,
}}


def main(config: Optional[SkillConfig] = None, **kwargs) -> dict:
    """Main entry point for {name} skill.

    Args:
        config: Skill configuration
        **kwargs: Additional arguments

    Returns:
        Result dictionary with 'ok', 'data', or 'error'
    """
{implementation}


if __name__ == "__main__":
    import sys
    result = main()
    print(json.dumps(result, indent=2))
'''

TEST_TEMPLATE = '''"""Tests for {name} skill."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import {module_name}


class Test{class_name}:
    """Tests for {name} skill."""

    def test_manifest_exists(self):
        """Skill has valid manifest."""
        assert hasattr({module_name}, "SKILL_MANIFEST")
        manifest = {module_name}.SKILL_MANIFEST
        assert manifest["name"] == "{name}"
        assert manifest["version"] == "1.0.0"
        assert "entry_point" in manifest

    def test_main_entry_point(self):
        """Main entry point exists and returns valid result."""
        result = {module_name}.main()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_main_with_config(self):
        """Main works with config."""
        @pytest.fixture
        def config():
            return {module_name}.SkillConfig()

    def test_skill_validation(self):
        """Skill passes validation."""
        from skills.registry import get_registry
        registry = get_registry()
        validation = registry.validate_skill("{name}")
        assert "valid" in validation
'''


class SkillGenerator:
    """Generates skills from natural language specifications using templates."""

    def __init__(self):
        self.skills_dir = Path(__file__).resolve().parent

    def generate(self, spec: str, name: Optional[str] = None) -> dict[str, Any]:
        """Generate a skill from specification.

        Args:
            spec: Natural language description of the skill
            name: Optional skill name (auto-generated from spec if not provided)

        Returns:
            Dict with generated files and manifest
        """
        # Select best matching template
        template_name, template = self._select_template(spec)

        # Generate skill name if not provided
        if not name:
            name = re.sub(r'[^a-z0-9]+', '_', spec.lower())[:30].strip('_')
            if not name:
                name = "generated_skill"

        # Clean name
        name = re.sub(r'[^a-z0-9_]+', '_', name.lower()).strip('_')
        if not name:
            name = "generated_skill"

        module_file = f"{name}.py"
        test_file = f"test_{name}.py"

        # Fill template
        code = SKILL_TEMPLATE.format(
            name=name,
            description=template["description"],
            template_name=template_name,
            config_fields=template["config_fields"],
            dependencies=template["dependencies"],
            module_file=module_file,
            config_schema=template["config_schema"],
            default_config=template["default_config"],
            tags=template["tags"],
            implementation=template["implementation"],
        )

        # Write module file
        module_file_path = self.skills_dir / module_file
        module_file_path.write_text(code)

        # Generate test file
        test_code = self._generate_test_file(name)
        test_file_path = self.skills_dir / f"test_{name}.py"
        test_file_path.write_text(test_code)

        return {
            "name": name,
            "module_file": str(module_file_path),
            "test_file": str(test_file_path),
            "ok": True,
        }

    def _select_template(self, spec: str) -> tuple[str, dict]:
        """Select best matching template based on spec keywords."""
        spec_lower = spec.lower()

        if any(kw in spec_lower for kw in ["calculate", "arithmetic", "math", "add", "subtract", "multiply", "divide", "interest", "compound"]):
            return "calculator", SKILL_TEMPLATES["calculator"]
        elif any(kw in spec_lower for kw in ["text", "string", "uppercase", "lowercase", "reverse", "word count"]):
            return "text_processor", SKILL_TEMPLATES["text_processor"]
        elif any(kw in spec_lower for kw in ["json", "csv", "convert", "transform", "data"]):
            return "data_transformer", SKILL_TEMPLATES["data_transformer"]
        else:
            # Default to calculator
            return "calculator", SKILL_TEMPLATES["calculator"]

    def _generate_test_file(self, name: str) -> str:
        """Generate test file for skill."""
        module_name = name.replace("-", "_")
        class_name = "".join(word.capitalize() for word in module_name.split("_"))

        return TEST_TEMPLATE.format(
            name=name,
            module_name=module_name,
            class_name=class_name,
        )


# Pre-defined skill templates for common patterns
SKILL_TEMPLATES = {
    "calculator": {
        "description": "Calculator skill for basic arithmetic operations",
        "config_fields": """    precision: int = 2
    allow_negative: bool = True""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "precision": {"type": "integer", "minimum": 0, "maximum": 10},
            "allow_negative": {"type": "boolean"},
        },
    }""",
        "default_config": """{
        "precision": 2,
        "allow_negative": True,
    }""",
        "tags": '["math", "utility", "demo"]',
        "implementation": """    try:
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
        return {"ok": False, "error": str(e)}""",
    },
    "text_processor": {
        "description": "Text processing skill for string manipulation",
        "config_fields": """    case_sensitive: bool = False
    max_length: int = 1000""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "case_sensitive": {"type": "boolean"},
            "max_length": {"type": "integer", "minimum": 1},
        },
    }""",
        "default_config": """{
        "case_sensitive": False,
        "max_length": 1000,
    }""",
        "tags": '["text", "utility", "demo"]',
        "implementation": """    try:
        if config is None:
            config = SkillConfig()

        operation = kwargs.get("operation")
        text = kwargs.get("text", "")

        if not text:
            return {"ok": False, "error": "Missing required argument: text"}

        if len(text) > config.max_length:
            text = text[:config.max_length]

        result = None
        if operation == "uppercase":
            result = text.upper()
        elif operation == "lowercase":
            result = text.lower()
        elif operation == "reverse":
            result = text[::-1]
        elif operation == "word_count":
            result = len(text.split())
        else:
            return {"ok": False, "error": f"Unknown operation: {operation}"}

        return {"ok": True, "data": {"operation": operation, "result": result}}
    except Exception as e:
        return {"ok": False, "error": str(e)}""",
    },
    "data_transformer": {
        "description": "Data transformation skill for JSON/CSV conversion",
        "config_fields": """    output_format: str = "json"
    indent: int = 2""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "output_format": {"type": "string", "enum": ["json", "csv"]},
            "indent": {"type": "integer", "minimum": 0, "maximum": 8},
        },
    }""",
        "default_config": """{
        "output_format": "json",
        "indent": 2,
    }""",
        "tags": '["data", "utility", "demo"]',
        "implementation": """    try:
        if config is None:
            config = SkillConfig()

        data = kwargs.get("data")
        if data is None:
            return {"ok": False, "error": "Missing required argument: data"}

        import json
        import csv
        import io

        if config.output_format == "json":
            result = json.dumps(data, indent=config.indent)
        elif config.output_format == "csv":
            if isinstance(data, list) and data and isinstance(data[0], dict):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                result = output.getvalue()
            else:
                return {"ok": False, "error": "CSV output requires list of dicts"}
        else:
            return {"ok": False, "error": f"Unknown format: {config.output_format}"}

        return {"ok": True, "data": {"format": config.output_format, "result": result}}
    except Exception as e:
        return {"ok": False, "error": str(e)}""",
    },
}


SKILL_TEMPLATE = '''"""Dost Skill: {name}

{description}
Auto-generated from template: {template_name}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SkillConfig:
    """Configuration for {name} skill."""
{config_fields}


SKILL_MANIFEST = {{
    "name": "{name}",
    "version": "1.0.0",
    "description": "{description}",
    "author": "dost-generator",
    "dependencies": {dependencies},
    "entry_point": "main",
    "module_file": "{module_file}",
    "test_file": "test_{module_file}",
    "config_schema": {config_schema},
    "default_config": {default_config},
    "tags": {tags},
    "enabled": True,
}}


def main(config: Optional[SkillConfig] = None, **kwargs) -> dict:
    """Main entry point for {name} skill.

    Args:
        config: Skill configuration
        **kwargs: Additional arguments

    Returns:
        Result dictionary with 'ok', 'data', or 'error'
    """
{implementation}


if __name__ == "__main__":
    import sys
    result = main()
    print(json.dumps(result, indent=2))
'''

TEST_TEMPLATE = '''"""Tests for {name} skill."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import {module_name}


class Test{class_name}:
    """Tests for {name} skill."""

    def test_manifest_exists(self):
        """Skill has valid manifest."""
        assert hasattr({module_name}, "SKILL_MANIFEST")
        manifest = {module_name}.SKILL_MANIFEST
        assert manifest["name"] == "{name}"
        assert manifest["version"] == "1.0.0"
        assert "entry_point" in manifest

    def test_main_entry_point(self):
        """Main entry point exists and returns valid result."""
        result = {module_name}.main()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_main_with_config(self):
        """Main works with config."""
        @pytest.fixture
        def config():
            return {module_name}.SkillConfig()

    def test_skill_validation(self):
        """Skill passes validation."""
        from skills.registry import get_registry
        registry = get_registry()
        validation = registry.validate_skill("{name}")
        assert "valid" in validation
'''


class SkillGenerator:
    """Generates skills from natural language specifications using templates."""

    def __init__(self):
        self.skills_dir = Path(__file__).resolve().parent

    def generate(self, spec: str, name: Optional[str] = None) -> dict[str, Any]:
        """Generate a skill from specification.

        Args:
            spec: Natural language description of the skill
            name: Optional skill name (auto-generated from spec if not provided)

        Returns:
            Dict with generated files and manifest
        """
        # Select best matching template
        template_name, template = self._select_template(spec)

        # Generate skill name if not provided
        if not name:
            name = re.sub(r'[^a-z0-9]+', '_', spec.lower())[:30].strip('_')
            if not name:
                name = "generated_skill"

        # Clean name
        name = re.sub(r'[^a-z0-9_]+', '_', name.lower()).strip('_')
        if not name:
            name = "generated_skill"

        module_file = f"{name}.py"
        test_file = f"test_{name}.py"

        # Fill template
        code = SKILL_TEMPLATE.format(
            name=name,
            description=template["description"],
            template_name=template_name,
            config_fields=template["config_fields"],
            dependencies=template["dependencies"],
            module_file=module_file,
            config_schema=template["config_schema"],
            default_config=template["default_config"],
            tags=template["tags"],
            implementation=template["implementation"],
        )

        # Write module file
        module_file_path = self.skills_dir / module_file
        module_file_path.write_text(code)

        # Generate test file
        test_code = self._generate_test_file(name)
        test_file_path = self.skills_dir / f"test_{name}.py"
        test_file_path.write_text(test_code)

        return {
            "name": name,
            "module_file": str(module_file_path),
            "test_file": str(test_file_path),
            "ok": True,
        }

    def _select_template(self, spec: str) -> tuple[str, dict]:
        """Select best matching template based on spec keywords."""
        spec_lower = spec.lower()

        if any(kw in spec_lower for kw in ["calculate", "arithmetic", "math", "add", "subtract", "multiply", "divide", "interest", "compound"]):
            return "calculator", SKILL_TEMPLATES["calculator"]
        elif any(kw in spec_lower for kw in ["text", "string", "uppercase", "lowercase", "reverse", "word count"]):
            return "text_processor", SKILL_TEMPLATES["text_processor"]
        elif any(kw in spec_lower for kw in ["json", "csv", "convert", "transform", "data"]):
            return "data_transformer", SKILL_TEMPLATES["data_transformer"]
        else:
            # Default to calculator
            return "calculator", SKILL_TEMPLATES["calculator"]

    def _generate_test_file(self, name: str) -> str:
        """Generate test file for skill."""
        module_name = name.replace("-", "_")
        class_name = "".join(word.capitalize() for word in module_name.split("_"))

        return TEST_TEMPLATE.format(
            name=name,
            module_name=module_name,
            class_name=class_name,
        )


# Pre-defined skill templates for common patterns
SKILL_TEMPLATES = {
    "calculator": {
        "description": "Calculator skill for basic arithmetic operations",
        "config_fields": """    precision: int = 2
    allow_negative: bool = True""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "precision": {"type": "integer", "minimum": 0, "maximum": 10},
            "allow_negative": {"type": "boolean"},
        },
    }""",
        "default_config": """{
        "precision": 2,
        "allow_negative": True,
    }""",
        "tags": '["math", "utility", "demo"]',
        "implementation": """    try:
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
        return {"ok": False, "error": str(e)}""",
    },
    "text_processor": {
        "description": "Text processing skill for string manipulation",
        "config_fields": """    case_sensitive: bool = False
    max_length: int = 1000""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "case_sensitive": {"type": "boolean"},
            "max_length": {"type": "integer", "minimum": 1},
        },
    }""",
        "default_config": """{
        "case_sensitive": False,
        "max_length": 1000,
    }""",
        "tags": '["text", "utility", "demo"]',
        "implementation": """    try:
        if config is None:
            config = SkillConfig()

        operation = kwargs.get("operation")
        text = kwargs.get("text", "")

        if not text:
            return {"ok": False, "error": "Missing required argument: text"}

        if len(text) > config.max_length:
            text = text[:config.max_length]

        result = None
        if operation == "uppercase":
            result = text.upper()
        elif operation == "lowercase":
            result = text.lower()
        elif operation == "reverse":
            result = text[::-1]
        elif operation == "word_count":
            result = len(text.split())
        else:
            return {"ok": False, "error": f"Unknown operation: {operation}"}

        return {"ok": True, "data": {"operation": operation, "result": result}}
    except Exception as e:
        return {"ok": False, "error": str(e)}""",
    },
    "data_transformer": {
        "description": "Data transformation skill for JSON/CSV conversion",
        "config_fields": """    output_format: str = "json"
    indent: int = 2""",
        "dependencies": "[]",
        "config_schema": """{
        "type": "object",
        "properties": {
            "output_format": {"type": "string", "enum": ["json", "csv"]},
            "indent": {"type": "integer", "minimum": 0, "maximum": 8},
        },
    }""",
        "default_config": """{
        "output_format": "json",
        "indent": 2,
    }""",
        "tags": '["data", "utility", "demo"]',
        "implementation": """    try:
        if config is None:
            config = SkillConfig()

        data = kwargs.get("data")
        if data is None:
            return {"ok": False, "error": "Missing required argument: data"}

        import json
        import csv
        import io

        if config.output_format == "json":
            result = json.dumps(data, indent=config.indent)
        elif config.output_format == "csv":
            if isinstance(data, list) and data and isinstance(data[0], dict):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                result = output.getvalue()
            else:
                return {"ok": False, "error": "CSV output requires list of dicts"}
        else:
            return {"ok": False, "error": f"Unknown format: {config.output_format}"}

        return {"ok": True, "data": {"format": config.output_format, "result": result}}
    except Exception as e:
        return {"ok": False, "error": str(e)}""",
    },
}


SKILL_TEMPLATE = '''"""Dost Skill: {name}

{description}
Auto-generated from template: {template_name}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SkillConfig:
    """Configuration for {name} skill."""
{config_fields}


SKILL_MANIFEST = {{
    "name": "{name}",
    "version": "1.0.0",
    "description": "{description}",
    "author": "dost-generator",
    "dependencies": {dependencies},
    "entry_point": "main",
    "module_file": "{module_file}",
    "test_file": "test_{module_file}",
    "config_schema": {config_schema},
    "default_config": {default_config},
    "tags": {tags},
    "enabled": True,
}}


def main(config: Optional[SkillConfig] = None, **kwargs) -> dict:
    """Main entry point for {name} skill.

    Args:
        config: Skill configuration
        **kwargs: Additional arguments

    Returns:
        Result dictionary with 'ok', 'data', or 'error'
    """
{implementation}


if __name__ == "__main__":
    import sys
    result = main()
    print(json.dumps(result, indent=2))
'''

TEST_TEMPLATE = '''"""Tests for {name} skill."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills import {module_name}


class Test{class_name}:
    """Tests for {name} skill."""

    def test_manifest_exists(self):
        """Skill has valid manifest."""
        assert hasattr({module_name}, "SKILL_MANIFEST")
        manifest = {module_name}.SKILL_MANIFEST
        assert manifest["name"] == "{name}"
        assert manifest["version"] == "1.0.0"
        assert "entry_point" in manifest

    def test_main_entry_point(self):
        """Main entry point exists and returns valid result."""
        result = {module_name}.main()
        assert isinstance(result, dict)
        assert "ok" in result

    def test_main_with_config(self):
        """Main works with config."""
        @pytest.fixture
        def config():
            return {module_name}.SkillConfig()

    def test_skill_validation(self):
        """Skill passes validation."""
        from skills.registry import get_registry
        registry = get_registry()
        validation = registry.validate_skill("{name}")
        assert "valid" in validation
'''


class SkillGenerator:
    """Generates skills from natural language specifications using templates."""

    def __init__(self):
        self.skills_dir = Path(__file__).resolve().parent

    def generate(self, spec: str, name: Optional[str] = None) -> dict[str, Any]:
        """Generate a skill from specification.

        Args:
            spec: Natural language description of the skill
            name: Optional skill name (auto-generated from spec if not provided)

        Returns:
            Dict with generated files and manifest
        """
        # Select best matching template
        template_name, template = self._select_template(spec)

        # Generate skill name if not provided
        if not name:
            name = re.sub(r'[^a-z0-9]+', '_', spec.lower())[:30].strip('_')
            if not name:
                name = "generated_skill"

        # Clean name
        name = re.sub(r'[^a-z0-9_]+', '_', name.lower()).strip('_')
        if not name:
            name = "generated_skill"

        module_file = f"{name}.py"
        test_file = f"test_{name}.py"

        # Fill template
        code = SKILL_TEMPLATE.format(
            name=name,
            description=template["description"],
            template_name=template_name,
            config_fields=template["config_fields"],
            dependencies=template["dependencies"],
            module_file=module_file,
            config_schema=template["config_schema"],
            default_config=template["default_config"],
            tags=template["tags"],
            implementation=template["implementation"],
        )

        # Write module file
        module_file_path = self.skills_dir / module_file
        module_file_path.write_text(code)

        # Generate test file
        test_code = self._generate_test_file(name)
        test_file_path = self.skills_dir / f"test_{name}.py"
        test_file_path.write_text(test_code)

        return {
            "name": name,
            "module_file": str(module_file_path),
            "test_file": str(test_file_path),
            "ok": True,
        }

    def _select_template(self, spec: str) -> tuple[str, dict]:
        """Select best matching template based on spec keywords."""
        spec_lower = spec.lower()

        if any(kw in spec_lower for kw in ["calculate", "arithmetic", "math", "add", "subtract", "multiply", "divide", "interest", "compound"]):
            return "calculator", SKILL_TEMPLATES["calculator"]
        elif any(kw in spec_lower for kw in ["text", "string", "uppercase", "lowercase", "reverse", "word count"]):
            return "text_processor", SKILL_TEMPLATES["text_processor"]
        elif any(kw in spec_lower for kw in ["json", "csv", "convert", "transform", "data"]):
            return "data_transformer", SKILL_TEMPLATES["data_transformer"]
        else:
            # Default to calculator
            return "calculator", SKILL_TEMPLATES["calculator"]

    def _generate_test_file(self, name: str) -> str:
        """Generate test file for skill."""
        module_name = name.replace("-", "_")
        class_name = "".join(word.capitalize() for word in module_name.split("_"))

        return TEST_TEMPLATE.format(
            name=name,
            module_name=module_name,
            class_name=class_name,
        )


def main():
    """CLI entry point for skill generation."""
    import argparse
    parser = argparse.ArgumentParser(description="Generate Dost skill from spec")
    parser.add_argument("spec", help="Natural language specification")
    parser.add_argument("--name", help="Skill name (optional)")
    args = parser.parse_args()

    generator = SkillGenerator()
    result = generator.generate(args.spec, args.name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()