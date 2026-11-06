"""Concurrent HTTP requests exercise SQLite BEGIN IMMEDIATE invariants.

Barriers synchronize request submission; each TestClient request still runs
through FastAPI and opens its own database transaction.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier


def together(action):
    barrier = Barrier(2, timeout=10)

    def submit():
        barrier.wait()
        return action()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        return [future.result(timeout=20) for future in futures]


def test_concurrent_checkouts_can_redeem_event_token_only_once(cafe, user):
    reward = cafe.reward(user)
    before = cafe.counts()
    responses = together(lambda: cafe.post(user, promo_token=reward['token']))
    assert sorted(response.status_code for response in responses) == [201, 409]
    orders = cafe.history(user)
    assert len(orders) == 1
    assert orders[0]['discount_amount'] == 2.70
    after = cafe.counts()
    assert after['orders'] == before['orders'] + 1
    assert after['order_items'] == before['order_items'] + 1
    assert after['order_logs'] == before['order_logs'] + 1
    with cafe.db.connect() as connection:
        assert connection.execute('SELECT redeemed_order_id FROM event_rsvps WHERE token=?',
                                  (reward['token'],)).fetchone()[0] == orders[0]['order_id']


def test_concurrent_completions_award_points_and_log_exactly_once(cafe, user):
    order = cafe.order(user)
    cafe.advance(order, 'preparing', 'ready')
    responses = together(lambda: cafe.status(order, 'completed'))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert cafe.profile(user)['loyalty_points'] == order['points_earned']
    assert len([entry for entry in cafe.logs(order) if entry['new_status'] == 'completed']) == 1


def test_concurrent_platinum_checkouts_reserve_only_one_monthly_upgrade(cafe, user):
    cafe.loyalty(user, 1500, 'Platinum')
    responses = together(lambda: cafe.post(user))
    assert [response.status_code for response in responses] == [201, 201]
    orders = [response.json() for response in responses]
    assert sorted(order['used_upgrade'] for order in orders) == [0, 1]
    assert sorted(order['total_amount'] for order in orders) == [16, 18]
    assert cafe.profile(user)['monthly_upgrade_available'] is False
    assert cafe.profile(user)['loyalty_points'] == 1500


def test_concurrent_inactive_customer_checkouts_get_only_one_return_offer(cafe, user):
    previous = cafe.order(user)
    cafe.complete(previous)
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE orders SET created_at=? WHERE order_id=?',
                           ((datetime.now(timezone.utc) - timedelta(days=8)).isoformat(), previous['order_id']))
    responses = together(lambda: cafe.post(user))
    assert [response.status_code for response in responses] == [201, 201]
    orders = [response.json() for response in responses]
    assert sorted(order['discount_amount'] for order in orders) == [0, 3.60]
    assert sorted(order['total_amount'] for order in orders) == [14.40, 18]
    assert cafe.profile(user)['return_discount_eligible'] is False
