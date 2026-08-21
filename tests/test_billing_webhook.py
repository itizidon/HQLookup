"""Stripe webhook entitlement and idempotency regression tests."""

import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import StripeWebhookEvent
from app.routes import billing


class _Request:
    headers = {"stripe-signature": "test-signature"}

    async def body(self) -> bytes:
        # The verified Event returned by construct_event must be authoritative.
        return b'{"metadata":{"plan":"attacker-controlled"}}'


class _Query:
    def __init__(self, answers: list[object]) -> None:
        self.answers = answers

    def filter(self, *_args):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self.answers.pop(0) if self.answers else None


class _Session:
    def __init__(
        self,
        *,
        query_answers=(),
        receipts=(),
        concurrent_duplicate: bool = False,
    ) -> None:
        self.query_answers = list(query_answers)
        self.receipts = set(receipts)
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.concurrent_duplicate = concurrent_duplicate

    def get(self, model, event_id):
        assert model is StripeWebhookEvent
        if event_id in self.receipts:
            return SimpleNamespace(event_id=event_id)
        return None

    def query(self, _model):
        return _Query(self.query_answers)

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1
        receipt = next(
            (item for item in self.added if isinstance(item, StripeWebhookEvent)),
            None,
        )
        if receipt is None:
            return
        if self.concurrent_duplicate:
            self.receipts.add(receipt.event_id)
            raise IntegrityError("INSERT", {}, Exception("duplicate event_id"))
        self.receipts.add(receipt.event_id)

    def rollback(self) -> None:
        self.rollbacks += 1


def _user(*, plan="free", subscription_id=None):
    return SimpleNamespace(
        plan=plan,
        stripe_customer_id="cus_1",
        stripe_subscription_id=subscription_id,
        stripe_current_period_start=None,
    )


def _subscription(*, status="active", price_id="price_starter", sub_id="sub_1"):
    return {
        "id": sub_id,
        "customer": "cus_1",
        "livemode": billing.settings.stripe_live_mode,
        "status": status,
        "items": {
            "data": [
                {
                    "price": {"id": price_id},
                    "current_period_start": 1_720_000_000,
                }
            ]
        },
    }


def _event(event_id, event_type, data_object, *, livemode=None):
    if livemode is None:
        livemode = billing.settings.stripe_live_mode
    return {
        "id": event_id,
        "type": event_type,
        "livemode": livemode,
        "data": {"object": data_object},
    }


@pytest.fixture(autouse=True)
def _configured_stripe(monkeypatch):
    monkeypatch.setattr(billing.stripe, "api_key", "sk_test_local")
    monkeypatch.setattr(billing, "WEBHOOK_SECRET", "whsec_local")
    monkeypatch.setattr(
        billing,
        "STRIPE_PRICE_IDS",
        {"starter": "price_starter"},
    )


def _deliver(monkeypatch, event, session, *, subscription=None):
    monkeypatch.setattr(
        billing.stripe.Webhook,
        "construct_event",
        lambda *_args: event,
    )
    if subscription is not None:
        monkeypatch.setattr(
            billing.stripe.Subscription,
            "retrieve",
            lambda _subscription_id: subscription,
        )
    return asyncio.run(billing.stripe_webhook(_Request(), session))


def test_checkout_grants_only_from_retrieved_known_active_subscription(
    monkeypatch,
) -> None:
    user = _user()
    session = _Session(query_answers=[None, user])
    event = _event(
        "evt_checkout",
        "checkout.session.completed",
        {
            "mode": "subscription",
            "customer": "cus_1",
            "subscription": "sub_1",
            "metadata": {"plan": "not-a-real-plan"},
        },
    )

    result = _deliver(
        monkeypatch,
        event,
        session,
        subscription=_subscription(),
    )

    assert result == {"received": True}
    assert user.plan == "starter"
    assert user.stripe_subscription_id == "sub_1"
    assert user.stripe_current_period_start.tzinfo is not None
    assert session.commits == 1
    assert "evt_checkout" in session.receipts


@pytest.mark.parametrize("status", ["past_due", "unpaid"])
def test_non_entitled_subscription_status_revokes_access(monkeypatch, status) -> None:
    user = _user(plan="starter", subscription_id="sub_1")
    user.stripe_current_period_start = object()
    session = _Session(query_answers=[user])
    event = _event(
        f"evt_{status}",
        "customer.subscription.updated",
        _subscription(status=status),
    )

    _deliver(
        monkeypatch,
        event,
        session,
        subscription=_subscription(status=status),
    )

    assert user.plan == "free"
    assert user.stripe_current_period_start is None


def test_active_subscription_with_unknown_price_fails_closed(monkeypatch) -> None:
    user = _user(plan="starter", subscription_id="sub_1")
    session = _Session(query_answers=[user])
    event = _event(
        "evt_unknown_price",
        "customer.subscription.updated",
        _subscription(price_id="price_unknown"),
    )

    _deliver(
        monkeypatch,
        event,
        session,
        subscription=_subscription(price_id="price_unknown"),
    )

    assert user.plan == "free"


def test_deleted_subscription_revokes_and_detaches(monkeypatch) -> None:
    user = _user(plan="starter", subscription_id="sub_1")
    session = _Session(query_answers=[user])
    event = _event(
        "evt_deleted",
        "customer.subscription.deleted",
        _subscription(status="canceled"),
    )

    _deliver(monkeypatch, event, session)

    assert user.plan == "free"
    assert user.stripe_subscription_id is None
    assert user.stripe_current_period_start is None


def test_duplicate_receipt_short_circuits_processing(monkeypatch) -> None:
    session = _Session(receipts={"evt_duplicate"})
    event = _event(
        "evt_duplicate",
        "customer.subscription.updated",
        _subscription(),
    )
    monkeypatch.setattr(
        billing.stripe.Subscription,
        "retrieve",
        lambda *_args: pytest.fail("duplicate event was processed"),
    )

    result = _deliver(monkeypatch, event, session)

    assert result == {"received": True}
    assert session.commits == 0
    assert session.added == []


def test_concurrent_duplicate_rolls_back_and_returns_success(monkeypatch) -> None:
    session = _Session(concurrent_duplicate=True)
    event = _event("evt_race", "unhandled.event", {})

    result = _deliver(monkeypatch, event, session)

    assert result == {"received": True}
    assert session.rollbacks == 1


def test_livemode_mismatch_is_rejected_before_recording(monkeypatch) -> None:
    session = _Session()
    event = _event(
        "evt_wrong_mode",
        "unhandled.event",
        {},
        livemode=not billing.settings.stripe_live_mode,
    )

    with pytest.raises(HTTPException) as exc_info:
        _deliver(monkeypatch, event, session)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid webhook request."
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.added == []
