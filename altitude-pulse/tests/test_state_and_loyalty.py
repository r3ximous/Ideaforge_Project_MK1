import pytest


STATUSES = ('pending', 'preparing', 'ready', 'completed', 'cancelled')
PATHS = {
    'pending': (), 'preparing': ('preparing',), 'ready': ('preparing', 'ready'),
    'completed': ('preparing', 'ready', 'completed'), 'cancelled': ('cancelled',),
}
ALLOWED = {
    'pending': {'preparing', 'cancelled'}, 'preparing': {'ready', 'cancelled'},
    'ready': {'completed'}, 'completed': set(), 'cancelled': set(),
}


@pytest.mark.parametrize('initial', STATUSES)
@pytest.mark.parametrize('target', STATUSES)
def test_complete_state_machine_matrix_is_atomic_and_idempotent(cafe, user, initial, target):
    order = cafe.order(user)
    cafe.advance(order, *PATHS[initial])
    before_order = cafe.snapshot(order)
    before_profile = cafe.profile(user)
    before_logs = cafe.logs(order)
    before_counts = cafe.counts()
    response = cafe.status(order, target)
    # "pending" is not an accepted mutation target, even when already pending.
    expected = 422 if target == 'pending' else 200 if target == initial or target in ALLOWED[initial] else 409
    assert response.status_code == expected, response.text
    if expected != 200 or target == initial:
        assert cafe.snapshot(order) == before_order
        assert cafe.profile(user) == before_profile
        assert cafe.logs(order) == before_logs
        assert cafe.counts() == before_counts
    else:
        assert response.json()['status'] == target
        assert len(cafe.logs(order)) == len(before_logs) + 1
        assert cafe.logs(order)[-1]['old_status'] == initial
        assert cafe.logs(order)[-1]['new_status'] == target
        assert cafe.logs(order)[-1]['source'] == 'kds'
        expected_points = before_profile['loyalty_points'] + (order['points_earned'] if target == 'completed' else 0)
        assert cafe.profile(user)['loyalty_points'] == expected_points


def test_queue_uses_order_count_and_stable_id_tiebreaker(cafe, user):
    first = cafe.order(user, [cafe.line() for _ in range(3)])
    second = cafe.order(user)
    third = cafe.order(user)
    with cafe.db.connect(write=True) as connection:
        connection.execute("UPDATE orders SET created_at='2030-01-01T00:00:00Z' WHERE user_id=?", (user['user_id'],))
    for index, order in enumerate((first, second, third)):
        snapshot = cafe.snapshot(order)
        assert snapshot['orders_ahead'] == index
        assert snapshot['queue_position'] == index + 1
    assert [order['order_id'] for order in cafe.active()] == [first['order_id'], second['order_id'], third['order_id']]
    cafe.advance(first, 'preparing')
    assert cafe.snapshot(second)['orders_ahead'] == 1
    cafe.advance(first, 'ready')
    assert cafe.snapshot(first)['queue_position'] == cafe.snapshot(first)['orders_ahead'] == 0
    assert cafe.snapshot(second)['queue_position'] == 1
    assert cafe.snapshot(third)['orders_ahead'] == 1
    # Ready leaves the waiting queue, not the kitchen's handoff column.
    assert [order['status'] for order in cafe.active()] == ['ready', 'pending', 'pending']
    cafe.advance(second, 'cancelled')
    assert cafe.snapshot(second)['queue_position'] == cafe.snapshot(second)['orders_ahead'] == 0
    assert cafe.snapshot(third)['queue_position'] == 1
    cafe.advance(first, 'completed')
    assert [order['order_id'] for order in cafe.active()] == [third['order_id']]


def test_queue_is_global_across_customers_and_uses_created_at_before_id(cafe, user):
    first = cafe.order(user)
    other = cafe.register()
    second = cafe.order(other)
    with cafe.db.connect(write=True) as connection:
        connection.execute("UPDATE orders SET created_at='2020-01-01T00:00:00Z' WHERE order_id=?", (second['order_id'],))
    assert cafe.snapshot(second)['queue_position'] == 1
    assert cafe.snapshot(first)['orders_ahead'] == 1
    assert [order['order_id'] for order in cafe.active()] == [second['order_id'], first['order_id']]


def test_points_only_arrive_at_completion_and_exactly_once_across_webhook_and_kds(cafe, user):
    order = cafe.order(user)
    assert order['points_earned'] == 180
    for status in ('pending', 'preparing', 'ready'):
        if status != 'pending':
            cafe.advance(order, status)
        assert cafe.profile(user)['loyalty_points'] == 0
        snapshot = cafe.snapshot(order)
        assert snapshot['points_awarded'] is False
        assert snapshot['completed_at'] is None
    completed = cafe.advance(order, 'completed')
    assert completed['points_awarded'] is True
    assert completed['completed_at']
    assert cafe.profile(user)['loyalty_points'] == 180
    for endpoint in ('/api/kds/status', '/api/mock/mobipos/webhook', '/api/mock/mobipos/webhook'):
        response = cafe.status(order, 'completed', endpoint)
        assert response.status_code == 200
        assert response.json() == completed
    assert cafe.profile(user)['loyalty_points'] == 180
    assert [(entry['old_status'], entry['new_status'], entry['source']) for entry in cafe.logs(order)] == [
        (None, 'pending', 'mock_checkout'), ('pending', 'preparing', 'kds'),
        ('preparing', 'ready', 'kds'), ('ready', 'completed', 'kds')]


@pytest.mark.parametrize('starting,tier,price,expected_points,expected_tier', [
    (399, 'Base', 10, 499, 'Base'), (400, 'Base', 10, 500, 'Gold'),
    (401, 'Base', 10, 501, 'Gold'),
    (1389, 'Gold', 10, 1499, 'Gold'), (1390, 'Gold', 10, 1500, 'Platinum'),
    (1391, 'Gold', 10, 1501, 'Platinum'),
])
def test_loyalty_thresholds_and_gold_bonus(cafe, user, starting, tier, price, expected_points, expected_tier):
    cafe.loyalty(user, starting, tier)
    order = cafe.order(user, [cafe.line('Chocolate Cookie')])
    assert order['total_amount'] == price
    assert order['points_earned'] == (110 if tier == 'Gold' else 100)
    assert cafe.profile(user)['tier'] == tier
    assert cafe.profile(user)['loyalty_points'] == starting
    cafe.complete(order)
    profile = cafe.profile(user)
    assert profile['loyalty_points'] == expected_points
    assert profile['tier'] == expected_tier
    assert profile['monthly_upgrade_available'] is (expected_tier == 'Platinum')


def test_gold_bonus_uses_discounted_total_and_truncates_fractional_points(cafe, user):
    cafe.loyalty(user, 500, 'Gold')
    reward = cafe.reward(user)
    order = cafe.order(user, promo_token=reward['token'])
    assert order['total_amount'] == 15.30
    assert order['points_earned'] == 168  # floor(15.30 * 10 * 1.10), not 169.
    cafe.complete(order)
    assert cafe.profile(user)['loyalty_points'] == 668


def test_crossing_gold_threshold_does_not_reprice_an_already_placed_order(cafe, user):
    cafe.loyalty(user, 400, 'Base')
    first = cafe.order(user, [cafe.line('Chocolate Cookie')])
    pending = cafe.order(user, [cafe.line('Chocolate Cookie')])
    cafe.complete(first)
    assert cafe.profile(user)['tier'] == 'Gold'
    cafe.complete(pending)
    assert cafe.profile(user)['loyalty_points'] == 600
    next_order = cafe.order(user, [cafe.line('Chocolate Cookie')])
    assert next_order['points_earned'] == 110


@pytest.mark.parametrize('initial', ['pending', 'preparing'])
def test_cancellation_removes_all_items_without_points_or_completion(cafe, user, initial):
    order = cafe.order(user, [cafe.line(), cafe.line(), cafe.line('Butter Croissant')])
    cafe.advance(order, *PATHS[initial])
    cancelled = cafe.advance(order, 'cancelled')
    assert cancelled['status'] == 'cancelled'
    assert cancelled['points_awarded'] is False
    assert cancelled['completed_at'] is None
    assert cancelled['queue_position'] == cancelled['orders_ahead'] == 0
    assert len(cancelled['items']) == 3  # Preserve receipt, remove the entire order from KDS.
    assert cafe.active() == []
    assert cafe.profile(user)['loyalty_points'] == 0
    assert cafe.history(user)[0] == cancelled
    assert cafe.advance(order, 'cancelled') == cancelled
    assert len(cafe.logs(order)) == (2 if initial == 'pending' else 3)


def test_platinum_upgrades_exactly_one_large_drink_and_reserves_until_completion(cafe, user, frozen_now):
    cafe.loyalty(user, 1500, 'Platinum')
    assert cafe.profile(user)['monthly_upgrade_available'] is True
    order = cafe.order(user, [cafe.line('Butter Croissant'), cafe.line(size='12oz'),
                              cafe.line('Cold Brew'), cafe.line()])
    assert [item['price'] for item in order['items']] == [12, 16, 18, 18]
    assert order['used_upgrade'] == 1
    assert order['subtotal_amount'] == order['total_amount'] == 64
    assert order['points_earned'] == 640  # Platinum does not also receive Gold's 10% bonus.
    assert cafe.profile(user)['monthly_upgrade_available'] is False
    assert cafe.profile(user)['upgrade_month'] is None
    concurrent = cafe.order(user)
    assert concurrent['used_upgrade'] == 0
    assert concurrent['total_amount'] == 18
    cafe.complete(order)
    profile = cafe.profile(user)
    assert profile['loyalty_points'] == 2140
    assert profile['upgrade_month'] == frozen_now.strftime('%Y-%m')
    assert profile['monthly_upgrade_available'] is False
    next_order = cafe.order(user)
    assert next_order['used_upgrade'] == 0
    assert next_order['total_amount'] == 18


@pytest.mark.parametrize('initial', ['pending', 'preparing'])
def test_cancelling_platinum_reservation_releases_it_without_consuming_month(cafe, user, frozen_now, initial):
    cafe.loyalty(user, 1500, 'Platinum')
    first = cafe.order(user)
    cafe.advance(first, *PATHS[initial])
    assert cafe.profile(user)['monthly_upgrade_available'] is False
    cafe.advance(first, 'cancelled')
    profile = cafe.profile(user)
    assert profile['monthly_upgrade_available'] is True
    assert profile['upgrade_month'] is None
    assert profile['loyalty_points'] == 1500
    replacement = cafe.order(user)
    assert replacement['used_upgrade'] == 1
    assert replacement['total_amount'] == 16


@pytest.mark.parametrize('period,available', [('current', False), ('previous', True), ('last_year', True), ('unused', True)])
def test_platinum_upgrade_month_boundaries(cafe, user, frozen_now, period, available):
    from datetime import timedelta

    months = {
        'current': frozen_now.strftime('%Y-%m'),
        'previous': (frozen_now.replace(day=1) - timedelta(days=1)).strftime('%Y-%m'),
        'last_year': f'{frozen_now.year - 1}-{frozen_now.month:02d}',
        'unused': None,
    }
    cafe.loyalty(user, 1500, 'Platinum', months[period])
    assert cafe.profile(user)['monthly_upgrade_available'] is available
    order = cafe.order(user)
    assert bool(order['used_upgrade']) is available
    assert order['total_amount'] == (16 if available else 18)


def test_small_drinks_and_pastries_do_not_reserve_or_consume_upgrade(cafe, user, frozen_now):
    cafe.loyalty(user, 1500, 'Platinum')
    order = cafe.order(user, [cafe.line(size='12oz'), cafe.line('Butter Croissant')])
    assert order['used_upgrade'] == 0
    assert order['total_amount'] == 28
    assert cafe.profile(user)['monthly_upgrade_available'] is True
    cafe.complete(order)
    assert cafe.profile(user)['upgrade_month'] is None
    assert cafe.profile(user)['monthly_upgrade_available'] is True


def test_failed_platinum_checkout_does_not_reserve_upgrade(cafe, user, frozen_now):
    cafe.loyalty(user, 1500, 'Platinum')
    before = cafe.counts()
    response = cafe.post(user, [cafe.line(), cafe.line(item_id=999999)])
    assert response.status_code == 422
    assert cafe.counts() == before
    assert cafe.profile(user)['monthly_upgrade_available'] is True
    assert cafe.order(user)['used_upgrade'] == 1
