"""
Billing routes — Stripe Checkout Sessions + Webhook sync.
Handles: subscribe, upgrade/downgrade, cancel, billing portal.

Requires:
    pip install stripe
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET in .env
    STRIPE_PRICE_IDS map matching your PLAN_CONFIG keys
"""
import os
import json
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models import User, Organization, Business
from app.rag import PLAN_CONFIG

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:3000")

router = APIRouter(prefix="/billing", tags=["billing"])

# ── Stripe Price ID map ────────────────────────────────────────────────────────
# Set these in your .env or replace with your actual Stripe price IDs.
# Each key must match a key in PLAN_CONFIG.
STRIPE_PRICE_IDS: dict[str, str] = {
    "starter":  os.getenv("STRIPE_PRICE_STARTER",  "price_xxxxx_starter"),
}

PAID_PLANS = set(STRIPE_PRICE_IDS.keys())


# ── Request models ─────────────────────────────────────────────────────────────
class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "pro" | "business"

class ChangePlanRequest(BaseModel):
    new_plan: str


# ── Helpers ────────────────────────────────────────────────────────────────────
def _get_or_create_stripe_customer(user: User) -> str:
    """Return existing Stripe customer ID or create a new one."""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.name,
        metadata={"user_id": str(user.id)},
    )
    return customer.id


def _get_active_subscription(customer_id: str) -> stripe.Subscription | None:
    subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
    return subs.data[0] if subs.data else None


def _sync_user_from_subscription(
    db: Session,
    user: User,
    subscription: stripe.Subscription,
    plan: str,
) -> None:
    items = subscription.get("items", {}).get("data", [])
    raw_timestamp = items[0].get("current_period_start") if items else None
    if raw_timestamp:
        period_start = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc).replace(tzinfo=None)
    else:
        period_start = datetime.utcnow()

    user.plan                        = plan
    user.stripe_subscription_id      = subscription["id"]
    user.stripe_current_period_start = period_start

    db.add(user)
    db.commit()


# ── POST /billing/checkout ─────────────────────────────────────────────────────
@router.post("/checkout")
async def create_checkout_session(
    body:        CheckoutRequest,
    db:          Session = Depends(get_db),
    current_auth         = Depends(get_current_user),
):
    """
    Creates a Stripe Checkout Session for a new subscription.
    Returns a redirect URL — the frontend should navigate the user there.
    """
    user, _ = current_auth

    if body.plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: '{body.plan}'. Choose from {list(PAID_PLANS)}.")

    if user.plan == body.plan:
        raise HTTPException(status_code=400, detail="You are already on this plan.")

    # If the user already has an active subscription, they should use /change-plan instead.
    if user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="You already have an active subscription. Use /billing/change-plan to switch plans.",
        )

    customer_id = _get_or_create_stripe_customer(user)

    # Persist the customer ID immediately so we can match on webhook.
    if not user.stripe_customer_id:
        user.stripe_customer_id = customer_id
        db.add(user)
        db.commit()

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_IDS[body.plan], "quantity": 1}],
        success_url=f"{FRONTEND_URL}/dashboard?checkout=success&plan={body.plan}",
        cancel_url=f"{FRONTEND_URL}/pricing?checkout=cancelled",
        metadata={"user_id": str(user.id), "plan": body.plan},
        subscription_data={
            "metadata": {"user_id": str(user.id), "plan": body.plan},
        },
        allow_promotion_codes=True,
    )

    return {"checkout_url": session.url}


# ── POST /billing/change-plan ──────────────────────────────────────────────────
@router.post("/change-plan")
async def change_plan(
    body:        ChangePlanRequest,
    db:          Session = Depends(get_db),
    current_auth         = Depends(get_current_user),
):
    """
    Upgrades or downgrades an existing subscription inline (no redirect needed).
    Stripe prorates the difference automatically.
    """
    user, _ = current_auth

    if body.new_plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: '{body.new_plan}'.")

    if user.plan == body.new_plan:
        raise HTTPException(status_code=400, detail="You are already on this plan.")

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription found. Please subscribe first via /billing/checkout.",
        )

    subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)
    if subscription.status not in ("active", "trialing"):
        raise HTTPException(status_code=400, detail="Subscription is not active.")

    # Stripe requires the subscription item ID to modify the price.
    item_id = subscription["items"]["data"][0]["id"]

    updated = stripe.Subscription.modify(
        user.stripe_subscription_id,
        items=[{"id": item_id, "price": STRIPE_PRICE_IDS[body.new_plan]}],
        proration_behavior="create_prorations",  # Charge/credit immediately
        metadata={"plan": body.new_plan},
    )

    _sync_user_from_subscription(db, user, updated, body.new_plan)

    new_config = PLAN_CONFIG.get(body.new_plan, PLAN_CONFIG["free"])
    return {
        "message":         f"Plan updated to '{body.new_plan}' successfully.",
        "plan":            body.new_plan,
        "monthly_searches": new_config["monthly_searches"],
        "max_businesses":  new_config["max_businesses"],
    }


# ── POST /billing/cancel ───────────────────────────────────────────────────────
@router.post("/cancel")
async def cancel_subscription(
    db:          Session = Depends(get_db),
    current_auth         = Depends(get_current_user),
):
    """
    Cancels at period end (user keeps access until billing cycle closes).
    Does NOT immediately revoke access — the webhook handles that on period end.
    """
    user, _ = current_auth

    if not user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription to cancel.")

    subscription = stripe.Subscription.modify(
        user.stripe_subscription_id,
        cancel_at_period_end=True,
    )

    sub_item = subscription["items"]["data"][0]
    period_end = datetime.fromtimestamp(
        sub_item["current_period_end"],
        tz=timezone.utc,
    )

    return {
        "message": "Subscription will cancel at the end of the current billing period.",
        "access_until": period_end.isoformat(),
    }


# ── POST /billing/portal ───────────────────────────────────────────────────────
@router.post("/portal")
async def billing_portal(
    current_auth = Depends(get_current_user),
):
    """
    Returns a Stripe Customer Portal URL where the user can manage their
    payment method, view invoices, and update billing details.
    """
    user, _ = current_auth

    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{FRONTEND_URL}/dashboard/settings",
    )

    return {"portal_url": session.url}


# ── GET /billing/status ────────────────────────────────────────────────────────
@router.get("/status")
async def billing_status(
    current_auth = Depends(get_current_user),
):
    """
    Returns the user's current plan, limits, and live Stripe subscription state.
    Frontend can poll this after checkout redirect to confirm activation.
    """
    user, _ = current_auth

    plan       = user.plan or "free"
    config     = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])
    sub_status = None
    cancel_at  = None

    if user.stripe_subscription_id:
        try:
            sub        = stripe.Subscription.retrieve(user.stripe_subscription_id)
            sub_status = sub.status
            if sub.cancel_at_period_end:
                items = sub.get("items", {}).get("data", [])
                if items:
                    cancel_at = datetime.fromtimestamp(
                        items[0]["current_period_end"], tz=timezone.utc
                    ).isoformat()
        except stripe.error.StripeError:
            pass  # Stripe unreachable — return DB state only

    return {
        "plan":               plan,
        "monthly_searches":   config["monthly_searches"],
        "max_businesses":     config["max_businesses"],
        "max_organizations":  config["max_organizations"],
        "stripe_status":      sub_status,      # "active" | "past_due" | "canceled" | None
        "cancels_at":         cancel_at,        # ISO string if cancel_at_period_end is set
        "has_billing_account": bool(user.stripe_customer_id),
    }


# ── POST /billing/webhook ──────────────────────────────────────────────────────
@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload   = await request.body()
    sig       = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    event_type = event["type"]
    
    # Parse raw JSON once — plain Python dicts, no StripeObject anywhere
    raw = json.loads(payload)
    data_obj = raw["data"]["object"]

    if event_type == "checkout.session.completed":
        metadata = data_obj.get("metadata") or {}
        user_id  = metadata.get("user_id")
        plan     = metadata.get("plan")
        sub_id   = data_obj.get("subscription")

        print(f"[Webhook] checkout.session.completed — user_id={user_id}, plan={plan}, sub_id={sub_id}")

        if not all([user_id, plan, sub_id]):
            return {"received": True}

        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user:
            return {"received": True}

        subscription = stripe.Subscription.retrieve(sub_id)

        # current_period_start/end live on the subscription ITEM, not the
        # subscription itself, as of newer Stripe API versions.
        sub_item = subscription["items"]["data"][0]
        period_start = datetime.fromtimestamp(
            sub_item["current_period_start"], tz=timezone.utc
        )
        user.plan                        = plan
        user.stripe_customer_id          = data_obj.get("customer") or user.stripe_customer_id
        user.stripe_subscription_id      = sub_id
        user.stripe_current_period_start = period_start
        db.add(user)
        db.commit()

    elif event_type == "customer.subscription.updated":
            metadata = data_obj.get("metadata") or {}
            plan     = metadata.get("plan")
            sub_id   = data_obj.get("id")
            user     = db.query(User).filter(User.stripe_subscription_id == sub_id).first()

            if user and plan and plan in PLAN_CONFIG:
                items = data_obj.get("items", {}).get("data", [])
                raw_ts = items[0]["current_period_start"] if items else None
                period_start = (
                    datetime.fromtimestamp(raw_ts, tz=timezone.utc)
                    if raw_ts else user.stripe_current_period_start
                )
                user.plan                        = plan
                user.stripe_current_period_start = period_start
                db.add(user)
                db.commit()

    elif event_type == "customer.subscription.deleted":
        sub_id = data_obj.get("id")
        user   = db.query(User).filter(User.stripe_subscription_id == sub_id).first()

        if user:
            user.plan                        = "free"
            user.stripe_subscription_id      = None
            user.stripe_current_period_start = None
            db.add(user)
            db.commit()
            print(f"[Webhook] ✓ User {user.id} downgraded to free")

    elif event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            print(f"[Webhook] Payment failed for user {user.id} ({user.email})")

    return {"received": True}