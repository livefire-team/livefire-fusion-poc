from loadgen.backlog import Backlog, PendingOrder


def make(max_size=3):
    return Backlog(max_size=max_size, base_delay=2.0, max_delay=10.0)


def test_new_entry_is_due_after_the_base_delay():
    backlog = make()
    assert backlog.add("SKU-001", now=100.0) is True
    assert len(backlog) == 1
    assert backlog.pop_due(now=101.9) is None
    assert backlog.pop_due(now=102.0) == PendingOrder(sku="SKU-001", attempts=1, next_attempt_at=102.0)
    assert len(backlog) == 0


def test_pop_due_returns_the_earliest_entry_first():
    backlog = make()
    backlog.add("SKU-002", now=5.0)
    backlog.add("SKU-001", now=1.0)
    assert backlog.pop_due(now=50.0).sku == "SKU-001"
    assert backlog.pop_due(now=50.0).sku == "SKU-002"
    assert backlog.pop_due(now=50.0) is None


def test_full_backlog_drops_new_entries():
    backlog = make(max_size=2)
    assert backlog.add("SKU-001", now=0.0)
    assert backlog.add("SKU-001", now=0.0)
    assert backlog.add("SKU-001", now=0.0) is False
    assert len(backlog) == 2
    assert backlog.dropped == 1


def test_retry_backs_off_exponentially_up_to_the_cap():
    backlog = make()
    order = PendingOrder(sku="SKU-001", attempts=1, next_attempt_at=0.0)
    due_times = []
    for _ in range(4):
        assert backlog.retry_later(order, now=0.0) is True
        order = backlog.pop_due(now=1000.0)
        due_times.append(order.next_attempt_at)
    assert due_times == [4.0, 8.0, 10.0, 10.0]
    assert order.attempts == 5


def test_retry_later_respects_the_size_limit():
    backlog = make(max_size=1)
    backlog.add("SKU-001", now=0.0)
    assert backlog.retry_later(PendingOrder("SKU-002", 1, 0.0), now=0.0) is False
    assert backlog.dropped == 1
