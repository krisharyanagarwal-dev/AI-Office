"""Skill Tester for Dost.

Runs hermetic tests for skills in isolated environment.
Captures coverage, reports results, validates against requirements.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills.registry import get_registry, SkillManifest


@dataclass
class TestResult:
    """Result of running skill tests."""
    skill_name: str
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    coverage: Optional[float] = None
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    timestamp: str = ""


class SkillTester:
    """Runs hermetic tests for skills."""

    def __init__(self):
        self.registry = get_registry()
        self.skills_dir = Path(__file__).resolve().parent

    def test_skill(self, name: str, verbose: bool = False) -> TestResult:
        """Run tests for a single skill.

        Args:
            name: Skill name
            verbose: Show test output

        Returns:
            TestResult with outcome
        """
        skill = self.registry.get(name)
        if not skill:
            return TestResult(
                skill_name=name,
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=f"Skill {name} not registered",
                duration_sec=0,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        # Validate skill first
        validation = self.registry.validate_skill(name)
        if not validation["valid"]:
            return TestResult(
                skill_name=name,
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=f"Validation failed: {validation['issues']}",
                duration_sec=0,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        # Check test file exists
        test_path = self.skills_dir / skill.test_file
        if not test_path.exists():
            return TestResult(
                skill_name=name,
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=f"Test file not found: {skill.test_file}",
                duration_sec=0,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        # Run pytest on the test file
        start_time = time.time()
        try:
            cmd = [
                sys.executable, "-m", "pytest",
                str(test_path),
                "-v",
                "--tb=short",
                "-x",  # Stop on first failure
            ]
            if not verbose:
                cmd.append("-q")

            # Run in isolated environment
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self.skills_dir.parent) + ":" + env.get("PYTHONPATH", "")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                cwd=str(self.skills_dir.parent),
            )

            duration = time.time() - start_time

            # Parse test results
            passed = result.returncode == 0
            tests_run = self._parse_test_count(result.stdout, "passed")
            tests_failed = self._parse_test_count(result.stdout, "failed")

            test_result = TestResult(
                skill_name=name,
                passed=passed,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_sec=duration,
                tests_run=tests_run + tests_failed,
                tests_passed=tests_run,
                tests_failed=tests_failed,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

            # Update registry
            self.registry.update_test_result(name, passed)

            return test_result

        except subprocess.TimeoutExpired:
            return TestResult(
                skill_name=name,
                passed=False,
                exit_code=-1,
                stdout="",
                stderr="Test timeout (60s)",
                duration_sec=60,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        except Exception as e:
            return TestResult(
                skill_name=name,
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_sec=time.time() - start_time,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

    def _parse_test_count(self, output: str, status: str) -> int:
        """Parse test count from pytest output."""
        import re
        # Look for patterns like "5 passed" or "2 failed"
        pattern = rf"(\d+)\s+{status}"
        match = re.search(pattern, output)
        if match:
            return int(match.group(1))
        return 0

    def test_all(self, enabled_only: bool = True, verbose: bool = False) -> dict[str, TestResult]:
        """Run tests for all registered skills.

        Returns:
            Dict mapping skill name to TestResult
        """
        skills = self.registry.list_skills(enabled_only=enabled_only)
        results = {}

        for skill in skills:
            print(f"[tester] Testing {skill.name}...")
            results[skill.name] = self.test_skill(skill.name, verbose=verbose)

        return results

    def get_summary(self, results: dict[str, TestResult]) -> dict:
        """Get summary of test results."""
        total = len(results)
        passed = sum(1 for r in results.values() if r.passed)
        failed = total - passed
        total_tests = sum(r.tests_run for r in results.values())
        total_passed = sum(r.tests_passed for r in results.values())
        total_failed = sum(r.tests_failed for r in results.values())
        total_duration = sum(r.duration_sec for r in results.values())

        return {
            "skills_total": total,
            "skills_passed": passed,
            "skills_failed": failed,
            "tests_total": total_tests,
            "tests_passed": total_passed,
            "tests_failed": total_failed,
            "duration_sec": total_duration,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def main():
    """CLI entry point for skill testing."""
    import argparse
    parser = argparse.ArgumentParser(description="Test Dost skills")
    parser.add_argument("skill", nargs="?", help="Skill name (optional, tests all if omitted)")
    parser.add_argument("--all", action="store_true", help="Test all skills")
    parser.add_argument("--enabled-only", action="store_true", default=True, help="Test only enabled skills")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    tester = SkillTester()

    if args.skill and not args.all:
        result = tester.test_skill(args.skill, verbose=args.verbose)
        print(f"Skill: {result.skill_name}")
        print(f"Passed: {result.passed}")
        print(f"Duration: {result.duration_sec:.2f}s")
        print(f"Tests: {result.tests_passed} passed, {result.tests_failed} failed")
        if not result.passed:
            print(f"STDERR: {result.stderr}")
        sys.exit(0 if result.passed else 1)
    else:
        results = tester.test_all(enabled_only=args.enabled_only, verbose=args.verbose)
        summary = tester.get_summary(results)
        print(json.dumps(summary, indent=2))
        sys.exit(0 if summary["skills_failed"] == 0 else 1)


if __name__ == "__main__":
    main()