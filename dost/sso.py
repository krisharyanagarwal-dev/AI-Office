"""SSO / SAML integration for THE CLAUDE COMPANY.

Configures single sign-on for workspaces via SAML 2.0 identity providers.
Configuration is persisted per workspace under
``~/.openclaw/workspaces/{workspace_id}/sso_config.json``.
"""

import base64
import json
import os
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

BASE_DIR = Path(os.path.expanduser("~/.openclaw/workspaces"))
SSO_CONFIG_FILE = "sso_config.json"

# Service provider (this application) settings
SP_ENTITY_ID = "https://dost.claude.com/sso"
SP_ACS_PATH = "/sso/acs"
SP_METADATA_PATH = "/sso/metadata"


def _sso_config_path(workspace_id: str) -> Path:
    return BASE_DIR / workspace_id / SSO_CONFIG_FILE


def init_sso(
    workspace_id: str, idp_metadata_url: str, idp_entity_id: str
) -> dict:
    """Configure SSO for a workspace.

    Persists the SSO config to
    ``~/.openclaw/workspaces/{workspace_id}/sso_config.json``.
    """
    workspace_dir = BASE_DIR / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)

    acs_url = f"{SP_ENTITY_ID}{SP_ACS_PATH}/{workspace_id}"
    metadata_url = f"{SP_ENTITY_ID}{SP_METADATA_PATH}/{workspace_id}"

    config = {
        "workspace_id": workspace_id,
        "sso_enabled": True,
        "acs_url": acs_url,
        "metadata_url": metadata_url,
        "idp_metadata_url": idp_metadata_url,
        "idp_entity_id": idp_entity_id,
        "configured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    config_path = _sso_config_path(workspace_id)
    config_path.write_text(json.dumps(config, indent=2))

    return {
        "workspace_id": workspace_id,
        "sso_enabled": True,
        "acs_url": acs_url,
        "metadata_url": metadata_url,
    }


def get_sso_config(workspace_id: str) -> Optional[dict]:
    """Get SSO config for a workspace. Returns None if not configured."""
    config_path = _sso_config_path(workspace_id)
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def generate_saml_request(workspace_id: str, relay_state: str) -> str:
    """Generate a base64-encoded SAML AuthnRequest for the workspace's IdP."""
    config = get_sso_config(workspace_id)
    if config is None:
        raise ValueError(f"SSO is not configured for workspace {workspace_id}")

    request_id = f"_{uuid.uuid4().hex}"
    issue_instant = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    root = ET.Element(
        "samlp:AuthnRequest",
        attrib={
            "xmlns:samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
            "xmlns:saml": "urn:oasis:names:tc:SAML:2.0:assertion",
            "ID": request_id,
            "Version": "2.0",
            "IssueInstant": issue_instant,
            "Destination": config["idp_metadata_url"],
            "ProtocolBinding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            "AssertionConsumerServiceURL": config["acs_url"],
        },
    )

    issuer = ET.SubElement(root, "saml:Issuer")
    issuer.text = SP_ENTITY_ID

    name_id_policy = ET.SubElement(root, "samlp:NameIDPolicy")
    name_id_policy.set("AllowCreate", "true")

    ET.SubElement(
        root,
        "samlp:RequestedAuthnContext",
        attrib={"Comparison": "exact"},
    )

    xml_str = ET.tostring(root, encoding="unicode")
    return base64.b64encode(xml_str.encode("utf-8")).decode("utf-8")


def parse_saml_response(saml_response: str) -> dict:
    """Parse a SAML response (stub).

    No actual signature validation or SAML library calls are made here.
    Returns user info and auth status.
    """
    try:
        decoded = base64.b64decode(saml_response).decode("utf-8")
    except Exception:
        decoded = saml_response

    user_email = None
    user_name = None
    workspace_id = None
    authenticated = False

    try:
        root = ET.fromstring(decoded)
        # Stub extraction: real parsing would validate the signature and
        # read the Assertion/AttributeStatement here.
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "NameID" and user_email is None:
                user_email = elem.text
            if tag == "AttributeValue" and user_name is None:
                user_name = elem.text
        authenticated = root is not None
    except ET.ParseError:
        pass

    return {
        "user_email": user_email,
        "user_name": user_name,
        "workspace_id": workspace_id,
        "authenticated": authenticated,
    }


def is_sso_enabled(workspace_id: str) -> bool:
    """Check if SSO is enabled for a workspace."""
    config = get_sso_config(workspace_id)
    return config is not None and config.get("sso_enabled", False)
