"""
Billing routes — Stripe Checkout Sessions + Webhook sync.
Handles: subscribe, upgrade/downgrade, cancel, billing portal.

Requires:
    pip install stripe
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET in .env
    STRIPE_PRICE_IDS map matching your PLAN_CONFIG keys
"""
import logging
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_current_user
from app.models import User
from app.rag import PLAN_CONFIG
from app.settings import settings

logger = logging.getLogger(__name__)

stripe.api_key = (
    settings.stripe_secret_key.get_secret_value()
    if settings.stripe_secret_key
    else None
)
WEBHOOK_SECRET = (
    settings.stripe_webhook_secret.get_secret_value()
    if settings.stripe_webhook_secret
    else None
)

router = APIRouter(prefix="/billing", tags=["billing"])

# ── Stripe Price ID map ────────────────────────────────────────────────────────
# Set these in your .env or replace with your actual Stripe price IDs.
# Each key must match a key in PLAN_CONFIG.
STRIPE_PRICE_IDS: dict[str, str] = {}
if settings.stripe_price_starter:
    STRIPE_PRICE_IDS["starter"] = settings.stripe_price_starter

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

    customer = _stripe_call(
        stripe.Customer.create,
        email=user.email,
        name=user.name,
        metadata={"user_id": str(user.id)},
    )
    return customer.id


def _require_stripe(*, webhook: bool = False) -> None:
    if not stripe.api_key or (webhook and not WEBHOOK_SECRET):
        raise HTTPException(status_code=503, detail="Billing is not configured.")


def _stripe_call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except stripe.error.StripeError as exc:
        logger.warning("Stripe API operation failed: %s", exc.__class__.__name__)
        raise HTTPException(status_code=502, detail="Billing provider is temporarily unavailable.") from exc


def _subscription_plan(subscription) -> str | None:
    items = subscription.get("items", {}).get("data", [])
    if len(items) != 1:
        return None
    price = items[0].get("price")
    price_id = price.get("id") if hasattr(price, "get") else price
    return next((plan for plan, configured_id in STRIPE_PRICE_IDS.items() if configured_id == price_id), None)


def _subscription_is_entitled(subscription) -> bool:
    return subscription.get("status") in {"active", "trialing"}


def _sync_user_from_subscription(
    db: Session,
    user: User,
    subscription: stripe.Subscription,
) -> None:
    plan = _subscription_plan(subscription)
    if not plan or not _subscription_is_entitled(subscription):
        raise ValueError("Subscription does not provide a configured active entitlement")
    items = subscription.get("items", {}).get("data", [])
    raw_timestamp = items[0].get("current_period_start") if items else None
    if raw_timestamp:
        period_start = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
    else:
        period_start = datetime.now(timezone.utc)

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
    _require_stripe()

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

    session = _stripe_call(
        stripe.checkout.Session.create,
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_IDS[body.plan], "quantity": 1}],
        success_url=f"{settings.frontend_url}/dashboard?checkout=success&plan={body.plan}",
        cancel_url=f"{settings.frontend_url}/billing?checkout=cancelled",
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
    _require_stripe()

    if body.new_plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: '{body.new_plan}'.")

    if user.plan == body.new_plan:
        raise HTTPException(status_code=400, detail="You are already on this plan.")

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription found. Please subscribe first via /billing/checkout.",
        )

    subscription = _stripe_call(stripe.Subscription.retrieve, user.stripe_subscription_id)
    if subscription.status not in ("active", "trialing"):
        raise HTTPException(status_code=400, detail="Subscription is not active.")

    # Stripe requires the subscription item ID to modify the price.
    item_id = subscription["items"]["data"][0]["id"]

    updated = _stripe_call(
        stripe.Subscription.modify,
        user.stripe_subscription_id,
        items=[{"id": item_id, "price": STRIPE_PRICE_IDS[body.new_plan]}],
        proration_behavior="create_prorations",  # Charge/credit immediately
        payment_behavior="error_if_incomplete",
        metadata={"plan": body.new_plan},
    )

    if _subscription_plan(updated) != body.new_plan:
        raise HTTPException(status_code=502, detail="Stripe did not apply the requested price.")
    try:
        _sync_user_from_subscription(db, user, updated)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Stripe returned an invalid subscription entitlement.") from exc

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
    _require_stripe()

    if not user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription to cancel.")

    subscription = _stripe_call(
        stripe.Subscription.modify,
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
    _require_stripe()

    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")

    session = _stripe_call(
        stripe.billing_portal.Session.create,
        customer=user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/billing",
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
    _require_stripe()

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
            logger.warning("Stripe status lookup failed; returning persisted billing state")

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
    _require_stripe(webhook=True)
    payload   = await request.body()
    sig       = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    event_type = event["type"]
    data_obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        metadata = data_obj.get("metadata") or {}
        user_id  = metadata.get("user_id")
        sub_id   = data_obj.get("subscription")
        customer_id = data_obj.get("customer")

        if not all([user_id, sub_id, customer_id]) or not str(user_id).isdigit():
            return {"received": True}

        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or (user.stripe_customer_id and user.stripe_customer_id != customer_id):
            return {"received": True}

        subscription = _stripe_call(stripe.Subscription.retrieve, sub_id)
        if subscription.get("customer") != customer_id:
            return {"received": True}
        try:
            user.stripe_customer_id = customer_id
            _sync_user_from_subscription(db, user, subscription)
        except ValueError:
            logger.warning("Checkout webhook contained no valid entitlement")

    elif event_type == "customer.subscription.updated":
        sub_id = data_obj.get("id")
        user = db.query(User).filter(User.stripe_subscription_id == sub_id).first()
        if user:
            try:
                _sync_user_from_subscription(db, user, data_obj)
            except ValueError:
                user.plan = "free"
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

    elif event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer")
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            user.plan = "free"
            db.add(user)
            db.commit()
            logger.warning("Stripe payment failure revoked an entitlement")

    return {"received": True}
