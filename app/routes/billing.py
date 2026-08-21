"""
Billing routes — Stripe Checkout Sessions + Webhook sync.
Handles: subscribe, upgrade/downgrade, cancel, billing portal.

Requires:
    pip install stripe
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET in .env
    STRIPE_PRICE_IDS map matching your PLAN_CONFIG keys
"""
from datetime import datetime, timezone
import logging
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.models import StripeWebhookEvent, User
from app.rag import PLAN_CONFIG
from app.settings import settings
from app.rate_limit import limit_billing

logger = logging.getLogger(__name__)

stripe.api_key = settings.stripe_secret_key
WEBHOOK_SECRET = settings.stripe_webhook_secret
FRONTEND_URL = settings.frontend_url

router = APIRouter(prefix="/billing", tags=["billing"])

# ── Stripe Price ID map ────────────────────────────────────────────────────────
# Set these in your .env or replace with your actual Stripe price IDs.
# Each key must match a key in PLAN_CONFIG.
STRIPE_PRICE_IDS: dict[str, str] = {
    "starter": settings.stripe_price_starter or "",
}

PAID_PLANS = set(STRIPE_PRICE_IDS.keys())


def _require_billing_config(*, webhook: bool = False) -> None:
    if not stripe.api_key or not all(STRIPE_PRICE_IDS.values()):
        raise HTTPException(status_code=503, detail="Billing is not configured.")
    if webhook and not WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Billing webhook is not configured.")


ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})


class _InvalidWebhookEvent(ValueError):
    """Raised when a verified Stripe event has an unsafe or invalid shape."""


def _value(obj: Any, key: str, default: Any = None) -> Any:
    """Read a field from a StripeObject or mapping without serializing it."""
    getter = getattr(obj, "get", None)
    if callable(getter):
        return getter(key, default)
    return getattr(obj, key, default)


def _stripe_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    identifier = _value(value, "id") if value is not None else None
    return identifier if isinstance(identifier, str) and identifier else None


def _subscription_items(subscription: Any) -> list[Any]:
    items = _value(_value(subscription, "items", {}), "data", [])
    return list(items) if isinstance(items, (list, tuple)) else []


def _plan_from_subscription(subscription: Any) -> str | None:
    """Resolve exactly one paid tier from configured Stripe price IDs."""
    configured_prices = {
        price_id: plan
        for plan, price_id in STRIPE_PRICE_IDS.items()
        if price_id
    }
    matched_plans = {
        configured_prices[price_id]
        for item in _subscription_items(subscription)
        if (price_id := _stripe_id(_value(item, "price"))) in configured_prices
    }
    if len(matched_plans) != 1:
        return None
    return matched_plans.pop()


def _subscription_period_start(subscription: Any) -> datetime | None:
    raw_timestamp = _value(subscription, "current_period_start")
    if raw_timestamp is None:
        items = _subscription_items(subscription)
        raw_timestamp = _value(items[0], "current_period_start") if items else None
    if raw_timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def _subscription_customer_id(subscription: Any) -> str | None:
    return _stripe_id(_value(subscription, "customer"))


def _subscription_id(subscription: Any) -> str | None:
    return _stripe_id(subscription)


def _invoice_subscription_id(invoice: Any) -> str | None:
    subscription_id = _stripe_id(_value(invoice, "subscription"))
    if subscription_id:
        return subscription_id

    # Newer Stripe API versions nest the subscription under invoice.parent.
    parent = _value(invoice, "parent", {})
    details = _value(parent, "subscription_details", {})
    return _stripe_id(_value(details, "subscription"))


def _require_matching_livemode(obj: Any) -> None:
    livemode = _value(obj, "livemode")
    if not isinstance(livemode, bool) or livemode != settings.stripe_live_mode:
        raise _InvalidWebhookEvent("Stripe livemode mismatch")


def _retrieve_subscription(subscription_id: str) -> Any:
    subscription = stripe.Subscription.retrieve(subscription_id)
    _require_matching_livemode(subscription)
    return subscription


def _find_subscription_user(
    db: Session,
    *,
    subscription_id: str,
    customer_id: str | None,
    allow_customer_fallback: bool,
) -> User | None:
    user = (
        db.query(User)
        .filter(User.stripe_subscription_id == subscription_id)
        .with_for_update()
        .first()
    )
    if user or not allow_customer_fallback or not customer_id:
        return user

    candidate = (
        db.query(User)
        .filter(User.stripe_customer_id == customer_id)
        .with_for_update()
        .first()
    )
    if candidate and candidate.stripe_subscription_id not in (None, subscription_id):
        # Never let a delayed event replace a user's newer subscription.
        return None
    return candidate


def _stage_subscription_state(
    db: Session,
    user: User,
    subscription: Any,
    *,
    deleted: bool = False,
) -> None:
    subscription_id = _subscription_id(subscription)
    if not subscription_id:
        raise _InvalidWebhookEvent("Missing subscription ID")

    customer_id = _subscription_customer_id(subscription)
    if customer_id:
        user.stripe_customer_id = customer_id

    if deleted:
        user.plan = "free"
        user.stripe_subscription_id = None
        user.stripe_current_period_start = None
        db.add(user)
        return

    status = _value(subscription, "status")
    plan = _plan_from_subscription(subscription)
    user.stripe_subscription_id = subscription_id

    if status in ACTIVE_SUBSCRIPTION_STATUSES and plan is not None:
        user.plan = plan
        user.stripe_current_period_start = (
            _subscription_period_start(subscription) or datetime.now(timezone.utc)
        )
    else:
        # Fail closed for unknown prices and every non-entitled status, including
        # past_due, unpaid, incomplete, paused, and canceled subscriptions.
        user.plan = "free"
        user.stripe_current_period_start = None

    db.add(user)


def _sync_current_subscription(
    db: Session,
    subscription_id: str,
    *,
    expected_customer_id: str | None = None,
) -> None:
    subscription = _retrieve_subscription(subscription_id)
    customer_id = _subscription_customer_id(subscription)
    if expected_customer_id and customer_id != expected_customer_id:
        raise _InvalidWebhookEvent("Subscription customer mismatch")

    user = _find_subscription_user(
        db,
        subscription_id=subscription_id,
        customer_id=customer_id,
        allow_customer_fallback=True,
    )
    if user:
        _stage_subscription_state(db, user, subscription)


def _handle_verified_event(db: Session, event_type: str, data_obj: Any) -> None:
    if event_type in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
    }:
        if _value(data_obj, "mode") != "subscription":
            return
        subscription_id = _stripe_id(_value(data_obj, "subscription"))
        customer_id = _stripe_id(_value(data_obj, "customer"))
        if not subscription_id or not customer_id:
            raise _InvalidWebhookEvent("Missing checkout subscription data")
        _sync_current_subscription(
            db,
            subscription_id,
            expected_customer_id=customer_id,
        )
        return

    if event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }:
        subscription_id = _subscription_id(data_obj)
        if not subscription_id:
            raise _InvalidWebhookEvent("Missing subscription ID")
        # Retrieve canonical state so delayed events cannot restore stale access.
        _sync_current_subscription(db, subscription_id)
        return

    if event_type == "customer.subscription.deleted":
        subscription_id = _subscription_id(data_obj)
        if not subscription_id:
            raise _InvalidWebhookEvent("Missing subscription ID")
        user = _find_subscription_user(
            db,
            subscription_id=subscription_id,
            customer_id=None,
            allow_customer_fallback=False,
        )
        if user:
            _stage_subscription_state(db, user, data_obj, deleted=True)
        return

    if event_type in {
        "invoice.paid",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        "invoice.marked_uncollectible",
    }:
        subscription_id = _invoice_subscription_id(data_obj)
        if subscription_id:
            _sync_current_subscription(db, subscription_id)


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


# ── POST /billing/checkout ─────────────────────────────────────────────────────
@router.post("/checkout")
def create_checkout_session(
    body:        CheckoutRequest,
    db:          Session = Depends(get_db),
    current_auth         = Depends(get_current_user),
):
    """
    Creates a Stripe Checkout Session for a new subscription.
    Returns a redirect URL — the frontend should navigate the user there.
    """
    _require_billing_config()
    user, _ = current_auth
    limit_billing(user.id)

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

    try:
        customer_id = _get_or_create_stripe_customer(user)
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is temporarily unavailable.",
        ) from exc

    # Persist the customer ID immediately so we can match on webhook.
    if not user.stripe_customer_id:
        user.stripe_customer_id = customer_id
        db.add(user)
        db.commit()

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": STRIPE_PRICE_IDS[body.plan], "quantity": 1}],
            success_url=f"{FRONTEND_URL}/dashboard?checkout=success",
            cancel_url=f"{FRONTEND_URL}/billing?checkout=cancelled",
            allow_promotion_codes=True,
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is temporarily unavailable.",
        ) from exc

    return {"checkout_url": session.url}


# ── POST /billing/change-plan ──────────────────────────────────────────────────
@router.post("/change-plan")
def change_plan(
    body:        ChangePlanRequest,
    db:          Session = Depends(get_db),
    current_auth         = Depends(get_current_user),
):
    """
    Upgrades or downgrades an existing subscription inline (no redirect needed).
    Stripe prorates the difference automatically.
    """
    _require_billing_config()
    user, _ = current_auth
    limit_billing(user.id)

    if body.new_plan not in PAID_PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: '{body.new_plan}'.")

    if user.plan == body.new_plan:
        raise HTTPException(status_code=400, detail="You are already on this plan.")

    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No active subscription found. Please subscribe first via /billing/checkout.",
        )

    try:
        subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is temporarily unavailable.",
        ) from exc
    if subscription.status not in ("active", "trialing"):
        raise HTTPException(status_code=400, detail="Subscription is not active.")

    # Stripe requires the subscription item ID to modify the price.
    item_id = subscription["items"]["data"][0]["id"]

    try:
        updated = stripe.Subscription.modify(
            user.stripe_subscription_id,
            items=[{"id": item_id, "price": STRIPE_PRICE_IDS[body.new_plan]}],
            proration_behavior="always_invoice",
            payment_behavior="pending_if_incomplete",
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is temporarily unavailable.",
        ) from exc

    current_config = PLAN_CONFIG.get(user.plan or "free", PLAN_CONFIG["free"])
    return {
        "message":         "Plan change submitted. Access updates after payment confirmation.",
        "plan":            user.plan or "free",
        "requested_plan":  body.new_plan,
        "stripe_status":   updated.status,
        "monthly_searches": current_config["monthly_searches"],
        "max_businesses":  current_config["max_businesses"],
    }


# ── POST /billing/cancel ───────────────────────────────────────────────────────
@router.post("/cancel")
def cancel_subscription(
    current_auth         = Depends(get_current_user),
):
    """
    Cancels at period end (user keeps access until billing cycle closes).
    Does NOT immediately revoke access — the webhook handles that on period end.
    """
    _require_billing_config()
    user, _ = current_auth
    limit_billing(user.id)

    if not user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active subscription to cancel.")

    try:
        subscription = stripe.Subscription.modify(
            user.stripe_subscription_id,
            cancel_at_period_end=True,
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is temporarily unavailable.",
        ) from exc

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
def billing_portal(
    current_auth = Depends(get_current_user),
):
    """
    Returns a Stripe Customer Portal URL where the user can manage their
    payment method, view invoices, and update billing details.
    """
    _require_billing_config()
    user, _ = current_auth
    limit_billing(user.id)

    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")

    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{FRONTEND_URL}/dashboard",
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Billing provider is temporarily unavailable.",
        ) from exc

    return {"portal_url": session.url}


# ── GET /billing/status ────────────────────────────────────────────────────────
@router.get("/status")
def billing_status(
    current_auth = Depends(get_current_user),
):
    """
    Returns the user's current plan, limits, and live Stripe subscription state.
    Frontend can poll this after checkout redirect to confirm activation.
    """
    user, _ = current_auth
    limit_billing(user.id)

    plan       = user.plan or "free"
    config     = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])
    sub_status = None
    cancel_at  = None

    if user.stripe_subscription_id:
        _require_billing_config()
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
    _require_billing_config(webhook=True)
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, signature, WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        logger.warning("Rejected invalid Stripe webhook request")
        raise HTTPException(status_code=400, detail="Invalid webhook request.")

    event_id = _value(event, "id")
    event_type = _value(event, "type")
    event_data = _value(event, "data", {})
    data_obj = _value(event_data, "object")

    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(event_type, str)
        or not event_type
        or data_obj is None
    ):
        logger.warning("Rejected malformed verified Stripe webhook")
        raise HTTPException(status_code=400, detail="Invalid webhook request.")

    try:
        _require_matching_livemode(event)

        if db.get(StripeWebhookEvent, event_id) is not None:
            return {"received": True}

        _handle_verified_event(db, event_type, data_obj)

        # The receipt and any entitlement mutation commit atomically. Concurrent
        # delivery races are resolved by the primary key on event_id.
        db.add(StripeWebhookEvent(event_id=event_id))
        db.commit()
    except _InvalidWebhookEvent:
        db.rollback()
        logger.warning("Rejected unsafe Stripe webhook event of type %s", event_type)
        raise HTTPException(status_code=400, detail="Invalid webhook request.")
    except stripe.error.StripeError:
        db.rollback()
        logger.error("Stripe webhook dependency failed for event type %s", event_type)
        raise HTTPException(status_code=503, detail="Unable to process webhook.")
    except IntegrityError:
        db.rollback()
        try:
            duplicate = db.get(StripeWebhookEvent, event_id) is not None
        except Exception:
            duplicate = False
        if duplicate:
            return {"received": True}
        logger.error("Stripe webhook database constraint failure")
        raise HTTPException(status_code=500, detail="Unable to process webhook.")
    except Exception:
        db.rollback()
        logger.error("Unexpected Stripe webhook processing failure")
        raise HTTPException(status_code=500, detail="Unable to process webhook.")

    return {"received": True}
