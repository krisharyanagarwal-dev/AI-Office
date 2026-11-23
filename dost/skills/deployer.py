"""Skill Deployer for Dost.

Validates -> Registers -> Hot-reloads skills.
Rollback on test regression.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills.registry import get_registry, SkillManifest
from skills.tester import SkillTester, TestResult


BACKUP_DIR = Path(__file__).resolve().parent / ".backups"
BACKUP_DIR.mkdir(exist_ok=True)


@dataclass
class DeployResult:
    """Result of skill deployment."""
    skill_name: str
    success: bool
    message: str
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    test_result: Optional[TestResult] = None
    timestamp: str = ""


class SkillDeployer:
    """Deploys skills with validation and rollback."""

    def __init__(self):
        self.registry = get_registry()
        self.tester = SkillTester()
        self.skills_dir = Path(__file__).resolve().parent

    def deploy(self, name: str, run_tests: bool = True) -> DeployResult:
        """Deploy a skill: validate, test, register, hot-reload.

        Args:
            name: Skill name
            run_tests: Whether to run tests before deployment

        Returns:
            DeployResult with outcome
        """
        start_time = time.time()
        skill = self.registry.get(name)

        if not skill:
            return DeployResult(
                skill_name=name,
                success=False,
                message=f"Skill {name} not found in registry",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        # Validate
        validation = self.registry.validate_skill(name)
        if not validation["valid"]:
            return DeployResult(
                skill_name=name,
                success=False,
                message=f"Validation failed: {validation['issues']}",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        previous_version = skill.version

        # Run tests if requested
        test_result = None
        if run_tests:
            test_result = self.tester.test_skill(name)
            if not test_result.passed:
                return DeployResult(
                    skill_name=name,
                    success=False,
                    message=f"Tests failed: {test_result.stderr}",
                    test_result=test_result,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )

        # Backup current version
        self._backup_skill(name)

        # Update deploy status
        self.registry.update_deploy_status(name, "deployed")

        return DeployResult(
            skill_name=name,
            success=True,
            message=f"Skill {name} deployed successfully",
            previous_version=previous_version,
            new_version=skill.version,
            test_result=test_result,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def deploy_all(self, run_tests: bool = True, enabled_only: bool = True) -> list[DeployResult]:
        """Deploy all registered skills."""
        skills = self.registry.list_skills(enabled_only=enabled_only)
        results = []

        for skill in skills:
            print(f"[deployer] Deploying {skill.name}...")
            results.append(self.deploy(skill.name, run_tests=run_tests))

        return results

    def rollback(self, name: str) -> DeployResult:
        """Rollback skill to previous version."""
        skill = self.registry.get(name)
        if not skill:
            return DeployResult(
                skill_name=name,
                success=False,
                message=f"Skill {name} not found",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        # Find backup
        backups = sorted(BACKUP_DIR.glob(f"{name}_v*.py"))
        if not backups:
            return DeployResult(
                skill_name=name,
                success=False,
                message="No backup found for rollback",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        # Restore latest backup
        latest_backup = backups[-1]
        target = self.skills_dir / f"{name}.py"
        shutil.copy2(latest_backup, target)

        # Restore test file too
        test_backup = BACKUP_DIR / f"test_{name}_v*.py"
        test_backups = sorted(BACKUP_DIR.glob(f"test_{name}_v*.py"))
        if test_backups:
            shutil.copy2(test_backups[-1], self.skills_dir / f"test_{name}.py")

        self.registry.update_deploy_status(name, "rolled_back")

        return DeployResult(
            skill_name=name,
            success=True,
            message=f"Rolled back to {latest_backup.name}",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def _backup_skill(self, name: str) -> None:
        """Create backup of skill files."""
        timestamp = int(time.time())
        skill_file = self.skills_dir / f"{name}.py"
        test_file = self.skills_dir / f"test_{name}.py"

        if skill_file.exists():
            backup_name = f"{name}_v{timestamp}.py"
            shutil.copy2(skill_file, BACKUP_DIR / backup_name)

        if test_file.exists():
            backup_name = f"test_{name}_v{timestamp}.py"
            shutil.copy2(test_file, BACKUP_DIR / backup_name)

    def hot_reload(self, name: str) -> bool:
        """Hot-reload a skill module in registry."""
        skill = self.registry.get(name)
        if not skill:
            return False

        # The registry's get_skill_module will reload on next call
        # Invalidate any cached modules
        import sys
        module_name = f"skills.{name}"
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Also clear any submodules
        to_delete = [k for k in sys.modules if k.startswith(f"skills.{name}.")]
        for k in to_delete:
            del sys.modules[k]

        return True

    def get_deploy_status(self, name: str) -> dict[str, Any]:
        """Get deployment status for a skill."""
        skill = self.registry.get(name)
        if not skill:
            return {"error": "Skill not found"}

        backups = sorted(BACKUP_DIR.glob(f"{name}_v*.py"))
        test_backups = sorted(BACKUP_DIR.glob(f"test_{name}_v*.py"))

        return {
            "name": skill.name,
            "version": skill.version,
            "deploy_status": skill.deploy_status,
            "deploy_ts": skill.deploy_ts,
            "last_test_run": skill.last_test_run,
            "last_test_passed": skill.last_test_passed,
            "backups_available": len(backups),
            "test_backups_available": len(test_backups),
            "enabled": skill.enabled,
        }


def main():
    """CLI entry point for skill deployment."""
    import argparse
    parser = argparse.ArgumentParser(description="Deploy Dost skills")
    parser.add_argument("skill", nargs="?", help="Skill name (optional, deploys all if omitted)")
    parser.add_argument("--all", action="store_true", help="Deploy all skills")
    parser.add_argument("--no-tests", action="store_true", help="Skip tests before deploy")
    parser.add_argument("--rollback", action="store_true", help="Rollback skill")
    parser.add_argument("--status", action="store_true", help="Show deploy status")
    parser.add_argument("--enabled-only", action="store_true", default=True, help="Deploy only enabled skills")
    args = parser.parse_args()

    deployer = SkillDeployer()

    if args.status and args.skill:
        status = deployer.get_deploy_status(args.skill)
        print(json.dumps(status, indent=2))
        return

    if args.rollback and args.skill:
        result = deployer.rollback(args.skill)
        print(f"Rollback: {'Success' if result.success else 'Failed'}: {result.message}")
        sys.exit(0 if result.success else 1)

    if args.skill and not args.all:
        result = deployer.deploy(args.skill, run_tests=not args.no_tests)
        print(f"Deploy: {'Success' if result.success else 'Failed'}: {result.message}")
        if result.test_result:
            print(f"Tests: {'Passed' if result.test_result.passed else 'Failed'}")
        sys.exit(0 if result.success else 1)

    if args.all or not args.skill:
        results = deployer.deploy_all(run_tests=not args.no_tests, enabled_only=args.enabled_only)
        success_count = sum(1 for r in results if r.success)
        print(f"Deployed: {success_count}/{len(results)} skills")
        for r in results:
            print(f"  {r.skill_name}: {'OK' if r.success else 'FAIL'} - {r.message}")
        sys.exit(0 if success_count == len(results) else 1)


if __name__ == "__main__":
    main()