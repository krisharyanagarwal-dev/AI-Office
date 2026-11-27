#!/usr/bin/env python3
"""
Agent Factory - batch-generates agent specs from a role taxonomy.

1 LLM call -> 10 agent specs (max throughput batch generation).
Outputs JSON specs ready to merge into office.json agent_tiers.
"""

import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "office-os"))
from core.subs.cloud_orchestrator import CloudModelOrchestrator

CONFIG_PATH = str(Path(__file__).resolve().parents[3] / "office-os" / "config" / "office.json")
OUTPUT_PATH = str(Path(__file__).resolve().parents[3] / "office-os" / "config" / "generated_agents.json")

# Department taxonomy: (department, [roles])
DEPARTMENTS = {
    "engineering": [
        "backend-engineer", "frontend-engineer", "fullstack-engineer",
        "devops-engineer", "sre-engineer", "platform-engineer",
        "mobile-engineer", "data-engineer", "ml-engineer", "qa-engineer",
    ],
    "product": [
        "product-manager", "product-designer", "product-analyst",
        "technical-writer", "ux-researcher", "product-marketing-manager",
    ],
    "marketing": [
        "growth-marketer", "performance-marketer", "content-marketer",
        "brand-manager", "seo-manager", "sem-manager",
        "email-marketer", "social-media-manager", "affiliate-manager",
        "influencer-manager",
    ],
    "sales": [
        "sales-development-rep", "account-executive", "account-manager",
        "sales-operations", "solution-engineer", "customer-success-manager",
    ],
    "operations": [
        "operations-manager", "logistics-coordinator", "procurement-specialist",
        "warehouse-manager", "fulfillment-manager", "inventory-planner",
        "vendor-manager", "facilities-manager",
    ],
    "finance": [
        "financial-analyst", "accountant", "fp-and-a-manager",
        "payroll-specialist", "tax-accountant", "treasury-manager",
        "procurement-analyst", "expense-analyst",
    ],
    "legal": [
        "legal-counsel", "compliance-officer", "contract-manager",
        "privacy-officer", "intellectual-property-counsel", "risk-manager",
    ],
    "customer-success": [
        "customer-success-manager", "implementation-specialist",
        "support-team-lead", "customer-advocacy-manager", "renewals-manager",
    ],
    "data": [
        "data-analyst", "data-scientist", "analytics-engineer",
        "business-intelligence-analyst", "data-governance-manager",
        "machine-learning-engineer",
    ],
    "security": [
        "security-analyst", "security-engineer", "application-security-engineer",
        "cloud-security-engineer", "incident-responder", "compliance-analyst",
    ],
    "hr": [
        "hr-manager", "recruiter", "people-operations",
        "learning-and-development", "compensation-analyst", "hr-business-partner",
    ],
    "executive": [
        "chief-of-staff", "strategy-manager", "business-operations-manager",
        "program-manager", "chief-of-staff-assistant",
    ],
}

# Agents that should be "pro" tier (heavy reasoning) vs "lite" (general)
PRO_ROLE_KEYWORDS = [
    "architect", "engineer", "manager", "director", "lead", "chief",
    "analyst", "scientist", "counsel", "officer", "specialist",
    "strategist", "advisor",
]

LITE_ROLE_KEYWORDS = [
    "coordinator", "assistant", "rep", "exec", "curator", "scout",
    "injector", "collector", "distributor", "extractor",
]


def tier_for_role(role):
    """Decide pro vs lite based on role name keywords."""
    role_lower = role.lower()
    if any(kw in role_lower for kw in PRO_ROLE_KEYWORDS):
        return "pro"
    return "lite"


def batch_generation_prompt(batch_num, roles):
    """Build a prompt that asks for 10 agent specs in one call."""
    roles_list = "\n".join(f"- {r}" for r in roles)
    return f"""You are an agent-factory generator for an AI office operating system.

Generate exactly 10 AI agent specifications for these roles:

{roles_list}

Each agent must have:
- agent_id: kebab-case, unique, descriptive (e.g. "backend-engineer")
- tier: "pro" for roles needing heavy reasoning (engineers, analysts, managers, counsel), "lite" for general/operational roles
- description: one sentence of what this agent does

Respond with ONLY a JSON array of 10 objects, each with keys: agent_id, tier, description.
No markdown fences, no extra text, just the raw JSON array.

Batch {batch_num}."""


def call_factory(orchestrator, batch_num, roles):
    """One cloud call -> 10 agent specs."""
    result = orchestrator.plan_and_execute(
        {"agent_id": f"agent-factory-batch-{batch_num}", "tier": "pro"},
        batch_generation_prompt(batch_num, roles),
        f"Generate 10 agent specs for batch {batch_num}.",
        task_id=f"factory-batch-{batch_num}",
        priority="normal",
    )
    exec_text = result["exec"]["text"]
    exec_model = result["exec"]["model"]
    exec_pool = result["exec"]["pool"]
    return exec_text, exec_model, exec_pool


def parse_specs(text, batch_num):
    """Parse JSON array from factory output, stripping reasoning blocks."""
    # Strip markdown fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(
            line for line in cleaned.split("\n") if not line.startswith("```")
        )
    # Try to find JSON array
    start = cleaned.find("[")
    end = cleaned.rfind("]") + 1
    if start == -1 or end == 0:
        print(f"  [factory] Batch {batch_num}: no JSON array found, skipping")
        return []
    try:
        specs = json.loads(cleaned[start:end])
    except json.JSONDecodeError as e:
        print(f"  [factory] Batch {batch_num}: JSON parse error: {e}")
        return []
    if not isinstance(specs, list):
        print(f"  [factory] Batch {batch_num}: not a list, skipping")
        return []
    return specs


def main():
    print("=" * 60)
    print("Agent Factory - batch agent spec generation")
    print("=" * 60)

    orchestrator = CloudModelOrchestrator()
    orch_status = orchestrator.status()
    print(f"Default timeout: {orch_status['default_timeout_sec']}s")
    print(f"Pools available: {len(orch_status['provider_pools'])}")

    all_specs = []
    seen_ids = set()

    # Flatten departments into a role list with batch grouping
    all_roles = []
    for dept, roles in DEPARTMENTS.items():
        for role in roles:
            all_roles.append((dept, role))

    # Group into batches of 10
    batches = []
    for i in range(0, len(all_roles), 10):
        batch_roles = [r for _, r in all_roles[i : i + 10]]
        batches.append((i // 10 + 1, batch_roles))

    print(f"\nGenerating {len(all_roles)} agents in {len(batches)} batches (1 call each)...\n")

    for batch_num, roles in batches:
        text, model, pool = call_factory(orchestrator, batch_num, roles)
        specs = parse_specs(text, batch_num)
        print(f"  Batch {batch_num}: {len(specs)} specs (model={model}@{pool})")

        for spec in specs:
            agent_id = spec.get("agent_id", "").strip()
            if not agent_id or agent_id in seen_ids:
                continue
            seen_ids.add(agent_id)
            tier = spec.get("tier", "lite")
            if tier not in ("pro", "lite"):
                tier = tier_for_role(agent_id)
            all_specs.append(
                {
                    "agent_id": agent_id,
                    "tier": tier,
                    "description": spec.get("description", ""),
                }
            )

    print(f"\nTotal unique agents generated: {len(all_specs)}")

    # Write output
    output = {"pro": [], "lite": [], "generated_count": len(all_specs)}
    for spec in all_specs:
        output[spec["tier"]].append(spec["agent_id"])

    # Also write detailed specs
    detailed = {"agents": all_specs, "count": len(all_specs)}

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nAgent tier lists written to {OUTPUT_PATH}")

    detailed_path = OUTPUT_PATH.replace(".json", "_detailed.json")
    with open(detailed_path, "w") as f:
        json.dump(detailed, f, indent=2)
    print(f"Detailed specs written to {detailed_path}")

    # Print summary for copy-paste into office.json
    print("\n--- Copy these into office.json agent_tiers ---")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
