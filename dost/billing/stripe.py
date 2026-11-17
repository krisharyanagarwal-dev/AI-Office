"""Stripe integration for THE CLAUDE COMPANY.

Handles customer creation, subscriptions, checkout sessions, cancellations,
subscription lookup, and Stripe webhook event processing.

Note: These are function stubs. No actual Stripe API calls are made.
"""

import os

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Plan name -> Stripe price ID mapping
PRICE_IDS = {
    "starter": "price_starter",
    "professional": "price_professional",
    "enterprise": "price_enterprise",
}


def create_customer(email: str, name: str, workspace_id: str) -> dict:
    """Create a Stripe customer.

    Returns:
        {"customer_id": ..., "status": "created"}
    """
    customer_id = f"cus_{workspace_id}_{email.replace('@', '_at_')}"
    return {"customer_id": customer_id, "status": "created"}


def create_subscription(customer_id: str, plan_name: str) -> dict:
    """Create a subscription for a customer.

    Maps plan_name to a Stripe price ID.

    Returns:
        {"subscription_id": ..., "status": ..., "client_secret": ...}
    """
    price_id = PRICE_IDS.get(plan_name, "price_default")
    subscription_id = f"sub_{customer_id}_{plan_name}"
    return {
        "subscription_id": subscription_id,
        "status": "active",
        "client_secret": f"pi_{subscription_id}_secret",
    }


def create_checkout_session(
    customer_id: str, plan_name: str, success_url: str, cancel_url: str
) -> dict:
    """Create a Stripe checkout session.

    Returns:
        {"checkout_url": ..., "session_id": ...}
    """
    session_id = f"cs_{customer_id}_{plan_name}"
    checkout_url = f"https://checkout.stripe.com/sessions/{session_id}"
    return {"checkout_url": checkout_url, "session_id": session_id}


def cancel_subscription(subscription_id: str) -> dict:
    """Cancel a Stripe subscription.

    Returns:
        {"subscription_id": ..., "status": "canceled"}
    """
    return {"subscription_id": subscription_id, "status": "canceled"}


def get_subscription(subscription_id: str) -> dict:
    """Get Stripe subscription details.

    Returns:
        {"subscription_id": ..., "status": ..., "plan": ..., "current_period_end": ...}
    """
    return {
        "subscription_id": subscription_id,
        "status": "active",
        "plan": "professional",
        "current_period_end": None,
    }


def handle_webhook(payload: str, sig_header: str) -> dict:
    """Handle Stripe webhook events.

    Handles: checkout.session.completed, invoice.payment_succeeded,
    invoice.payment_failed, customer.subscription.deleted

    Returns:
        {"status": "processed", "event_type": ...}
    """
    event_type = "unknown"
    return {"status": "processed", "event_type": event_type}
