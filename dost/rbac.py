"""
RBAC (Role-Based Access Control) for THE CLAUDE COMPANY.

Roles:
- admin: Full access to all resources and actions
- editor: Read/write/delete own tasks, view costs
- viewer: Read-only access to all resources
- viewer_lite: Read-limited access (basic status only)

Resource types: task, finding, dashboard, settings, cost_report
"""

ROLES = {
    "admin": ["read", "write", "delete", "manage_users", "manage_workspace", "view_costs", "manage_settings"],
    "pro": ["read", "write", "delete", "view_costs"],
    "lite": ["read", "write"],
    "viewer": ["read"],
    "viewer_lite": ["read_limited"],
}

RESOURCE_TYPES = ["task", "finding", "dashboard", "settings", "cost_report"]

ROLE_LEVELS = {
    "admin": 4,
    "pro": 3,
    "lite": 2,
    "viewer": 1,
    "viewer_lite": 0,
}

OWNER_ACTIONS = ["manage_users", "manage_workspace", "manage_settings"]


def can_access(agent_role: str, resource_type: str, action: str, is_owner: bool = False) -> bool:
    """Check if an agent_role can perform action on resource_type.

    Admins can do everything. Editors can read/write/delete their own tasks.
    Viewers can read everything. Viewer_lite can only read limited data.
    """
    if agent_role not in ROLES:
        return False

    if resource_type not in RESOURCE_TYPES:
        return False

    permissions = ROLES[agent_role]

    # Admins can do everything
    if agent_role == "admin":
        return True

    # Editors: read/write/delete own tasks, view costs
    if agent_role == "pro":
        if action in ("read", "write", "view_costs"):
            return True
        if action == "delete" and is_owner:
            return True
        return False

    # Lite: read/write
    if agent_role == "lite":
        if action in ("read", "write"):
            return True
        return False

    # Viewer: read everything
    if agent_role == "viewer":
        return action == "read"

    # Viewer_lite: read_limited only
    if agent_role == "viewer_lite":
        return action == "read_limited"

    return False


def get_allowed_actions(role: str, resource_type: str) -> list:
    """List all allowed actions for a role on a resource type."""
    if role not in ROLES or resource_type not in RESOURCE_TYPES:
        return []

    permissions = ROLES[role]

    if role == "admin":
        return list(permissions)

    if role == "pro":
        allowed = ["read", "write", "view_costs"]
        if resource_type == "task":
            allowed.append("delete")  # editors can delete their own
        return allowed

    if role == "lite":
        return ["read", "write"]

    if role == "viewer":
        return ["read"]

    if role == "viewer_lite":
        return ["read_limited"]

    return []


def check_workspace_access(user_role: str, workspace_id: str, user_email: str,
                           workspace_owner_email: str) -> bool:
    """Check if a user can access a workspace.

    Admins can access all workspaces. Other users need to be the workspace
    owner or a member (handled elsewhere).
    """
    if user_role == "admin":
        return True
    # Non-admins must be the workspace owner
    return user_email == workspace_owner_email


def get_role_hierarchy() -> dict:
    """Return role hierarchy levels."""
    return dict(ROLE_LEVELS)


def can_access_workspace(workspace_id: str, email: str) -> bool:
    """Check if a user has access to a workspace."""
    from dost.workspace import get_user_role
    role = get_user_role(workspace_id, email)
    return role is not None


def can_edit_workspace(workspace_id: str, email: str) -> bool:
    """Check if a user can edit in a workspace (admin or editor)."""
    from dost.workspace import get_user_role
    role = get_user_role(workspace_id, email)
    return role in ("admin", "pro")


def can_admin_workspace(workspace_id: str, email: str) -> bool:
    """Check if a user is admin of a workspace."""
    from dost.workspace import get_user_role
    role = get_user_role(workspace_id, email)
    return role == "admin"