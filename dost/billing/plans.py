"""
Plan and pricing for THE CLAUDE COMPANY workspaces.

Defines the available subscription tiers and computes projected monthly
cost from current usage plus the plan's unit ceiling.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from billing.meter import get_current_month_cost

WORKSPACE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))

PLANS: Dict[str, dict] = {
    "starter": {
        "name": "Starter",
        "monthly_cost_units": 500,
        "features": [
            "Basic task dispatch",
            "Community support",
            "Up to 3 concurrent tasks",
        ],
    },
    "professional": {
        "name": "Professional",
        "monthly_cost_units": 2000,
        "features": [
            "Priority dispatch",
            "Email support",
            "Up to 10 concurrent tasks",
            "Custom metrics",
        ],
    },
    "pro": {
        "name": "Pro",
        "monthly_cost_units": 2000,
        "features": [
            "Priority dispatch",
            "Email support",
            "Up to 10 concurrent tasks",
            "Custom metrics",
        ],
    },
    "enterprise": {
        "name": "Enterprise",
        "monthly_cost_units": 10000,
        "features": [
            "Unlimited tasks",
            "Dedicated support",
            "SLA guarantees",
            "Custom integrations",
            "Advanced analytics",
        ],
    },
}

DEFAULT_PLAN = "starter"


def _workspace_plan_name(workspace_id: str) -> str:
    """Read the plan name from workspace metadata."""
    meta_path = WORKSPACE_DIR / workspace_id / "workspace.json"
    if not meta_path.exists():
        return DEFAULT_PLAN
    try:
        meta = json.loads(meta_path.read_text())
        return meta.get("plan", DEFAULT_PLAN)
    except Exception:
        return DEFAULT_PLAN


def get_plan(workspace_id: str) -> dict:
    """Return plan details for a workspace.

    Returns:
        {
            "workspace_id": ...,
            "plan": {<plan details>},
            "features": [...],
        }
    """
    plan_name = _workspace_plan_name(workspace_id)
    plan = PLANS.get(plan_name, PLANS[DEFAULT_PLAN]).copy()
    return {
        "workspace_id": workspace_id,
        "plan": plan,
        "features": plan.get("features", []),
    }


def calculate_monthly_cost(workspace_id: str) -> dict:
    """Return current month cost and projection for a workspace.

    Returns:
        {
            "workspace_id": ...,
            "current_month_cost": ...,
            "plan": {...},
            "headroom": ...,
            "projected_monthly": ...,
        }
    """
    plan = get_plan(workspace_id)
    plan_details = plan["plan"]
    plan_limit = int(plan_details.get("monthly_cost_units", 0))

    current = get_current_month_cost(workspace_id)
    current_month_cost = int(current.get("cost_units", 0))

    # Simple linear projection based on days elapsed in the month.
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month = now.replace(year=now.year + 1, month=1, day=1)
    else:
        next_month = now.replace(month=now.month + 1, day=1)
    days_in_month = (next_month - now.replace(day=1)).days
    days_elapsed = max(now.day, 1)
    daily_run_rate = current_month_cost / days_elapsed
    projected_monthly = daily_run_rate * days_in_month

    headroom = max(plan_limit - projected_monthly, 0)

    return {
        "workspace_id": workspace_id,
        "current_month_cost": current_month_cost,
        "plan": plan_details,
        "headroom": round(headroom, 2),
        "projected_monthly": round(projected_monthly, 2),
    }
