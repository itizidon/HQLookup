import pytest
import redis

from app import rag


class _RedisResult:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def eval(self, *args):
        self.calls.append(args)
        return self.result


def test_reserve_search_is_atomic_and_returns_limit(monkeypatch):
    client = _RedisResult([1, 7])
    monkeypatch.setattr(rag, "redis_client", client)

    allowed, current, limit = rag.reserve_search(42, "free")

    assert allowed is True
    assert current == 7
    assert limit == rag.PLAN_CONFIG["free"]["monthly_searches"]
    assert client.calls[0][0] == rag._RESERVE_SEARCH_SCRIPT


def test_reserve_search_fails_closed_when_redis_is_unavailable(monkeypatch):
    class FailingRedis:
        def eval(self, *_args):
            raise redis.ConnectionError("unavailable")

    monkeypatch.setattr(rag, "redis_client", FailingRedis())

    with pytest.raises(rag.QuotaBackendUnavailable):
        rag.reserve_search(42, "free")


def test_reserve_search_can_enforce_business_allocation(monkeypatch):
    client = _RedisResult([0, 25, 25, 2])
    monkeypatch.setattr(rag, "redis_client", client)

    result = rag.reserve_search(42, "free", business_id=7, business_limit=25)

    assert result == (False, 25, 50, 25, 25, 2)
    assert client.calls[0][0] == rag._RESERVE_SEARCH_WITH_BUSINESS_SCRIPT
