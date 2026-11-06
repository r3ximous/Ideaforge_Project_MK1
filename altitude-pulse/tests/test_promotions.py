from datetime import timedelta
import sqlite3

import pytest


def test_event_feed_is_ordered_and_matches_frontend_contract(client):
    response = client.get('/api/events')
    assert response.status_code == 200
    events = response.json()['events']
    assert len(events) == 3
    assert [event['event_date'] for event in events] == sorted(event['event_date'] for event in events)
    assert [event['club_name'] for event in events] == ['AIRC', 'IEEE', 'Student Council']
    assert [event['discount_percent'] for event in events] == [15, 10, 10]
    for event in events:
        assert {'event_id', 'club_name', 'title', 'description', 'promo_code',
                'discount_percent', 'event_date'} <= event.keys()
        assert 'token' not in event


def test_rsvp_is_idempotent_until_reward_is_used_and_is_user_bound(cafe, user):
    reward = cafe.reward(user)
    assert set(reward) == {'token', 'discount_percent'}
    assert reward['discount_percent'] == 15
    assert len(reward['token']) >= 24
    assert cafe.reward(user) == reward
    other = cafe.register()
    other_reward = cafe.reward(other)
    assert other_reward['token'] != reward['token']
    before = cafe.counts()
    assert cafe.post(other, promo_token=reward['token']).status_code == 409
    assert cafe.counts() == before
    order = cafe.order(user, promo_token=reward['token'])
    assert order['subtotal_amount'] == 18
    assert order['discount_amount'] == 2.70
    assert order['total_amount'] == 15.30
    assert order['points_earned'] == 153
    assert order['promo_token'] == reward['token']
    assert cafe.post(user, promo_token=reward['token']).status_code == 409
    assert cafe.rsvp(user).status_code == 409
    with cafe.db.connect() as connection:
        row = connection.execute('SELECT * FROM event_rsvps WHERE token=?', (reward['token'],)).fetchone()
        assert row['redeemed_order_id'] == order['order_id']
    cafe.complete(order)
    assert cafe.post(user, promo_token=reward['token']).status_code == 409
    assert cafe.rsvp(user).status_code == 409
    assert cafe.profile(user)['loyalty_points'] == 153


@pytest.mark.parametrize('initial', ['pending', 'preparing'])
def test_cancellation_restores_exact_same_event_token(cafe, user, initial):
    reward = cafe.reward(user)
    order = cafe.order(user, promo_token=reward['token'])
    if initial == 'preparing':
        cafe.advance(order, 'preparing')
    cafe.advance(order, 'cancelled')
    assert cafe.reward(user) == reward
    assert cafe.profile(user)['loyalty_points'] == 0
    replacement = cafe.order(user, promo_token=reward['token'])
    assert replacement['discount_amount'] == 2.70
    # A late duplicate cancellation must not clear a replacement's reservation.
    cafe.advance(order, 'cancelled')
    assert cafe.post(user, promo_token=reward['token']).status_code == 409
    with cafe.db.connect() as connection:
        assert connection.execute('SELECT redeemed_order_id FROM event_rsvps WHERE token=?',
                                  (reward['token'],)).fetchone()[0] == replacement['order_id']


@pytest.mark.parametrize('failure', ['invalid_item', 'invalid_size', 'model_validation'])
def test_failed_checkout_rolls_back_event_reward_and_all_order_rows(cafe, user, failure):
    reward = cafe.reward(user)
    bad = {
        'invalid_item': cafe.line(item_id=999999),
        'invalid_size': cafe.line('Butter Croissant', '16oz'),
        'model_validation': cafe.line(customization='x' * 201),
    }[failure]
    before = cafe.counts()
    response = cafe.post(user, [cafe.line(), bad], promo_token=reward['token'])
    assert response.status_code == 422
    assert cafe.counts() == before
    assert cafe.reward(user) == reward
    with cafe.db.connect() as connection:
        assert connection.execute('SELECT redeemed_order_id FROM event_rsvps WHERE token=?',
                                  (reward['token'],)).fetchone()[0] is None
    assert cafe.order(user, promo_token=reward['token'])['discount_amount'] == 2.70


def test_database_failure_after_token_redemption_rolls_back_entire_transaction(cafe, user):
    reward = cafe.reward(user)
    before = cafe.counts()
    # Force a failure after orders, items, and RSVP redemption have been written.
    # This exercises Database.connect's rollback, not only early validation.
    with cafe.db.connect(write=True) as connection:
        connection.execute("""CREATE TRIGGER reject_checkout_log BEFORE INSERT ON order_logs
            WHEN NEW.source='mock_checkout' BEGIN
            SELECT RAISE(ABORT, 'test forced failure after reward redemption'); END""")
    try:
        with pytest.raises(sqlite3.IntegrityError, match='test forced failure after reward redemption'):
            cafe.post(user, promo_token=reward['token'])
    finally:
        with cafe.db.connect(write=True) as connection:
            connection.execute('DROP TRIGGER reject_checkout_log')
    assert cafe.counts() == before
    assert cafe.reward(user) == reward
    assert cafe.history(user) == []
    order = cafe.order(user, promo_token=reward['token'])
    assert order['discount_amount'] == 2.70


@pytest.mark.parametrize('token', ['made-up-token', 'AIRC'])
def test_public_club_code_is_not_a_discount_credential(cafe, user, token):
    before = cafe.counts()
    assert cafe.post(user, promo_token=token).status_code == 409
    assert cafe.counts() == before


@pytest.mark.parametrize('credential', ['missing', 'wrong', 'other_user', 'staff'])
def test_rsvp_requires_matching_customer_token(cafe, user, credential):
    other = cafe.register()
    headers = {'missing': {}, 'wrong': {'X-Customer-Token': 'wrong'},
               'other_user': cafe.headers(other), 'staff': {'X-Staff-Key': 'test-key'}}[credential]
    event = cafe.client.get('/api/events').json()['events'][0]
    before = cafe.counts()
    response = cafe.client.post(f'/api/events/{event["event_id"]}/rsvp',
                                headers=headers, json={'user_id': user['user_id']})
    assert response.status_code == 403
    assert cafe.counts() == before


def test_missing_and_expired_events_do_not_create_rsvp(cafe, user):
    before = cafe.counts()
    assert cafe.rsvp(user, 999999).status_code == 404
    event_id = cafe.client.get('/api/events').json()['events'][0]['event_id']
    with cafe.db.connect(write=True) as connection:
        connection.execute("UPDATE club_events SET event_date='2000-01-01T00:00:00Z' WHERE event_id=?", (event_id,))
    assert cafe.rsvp(user, event_id).status_code == 409
    assert cafe.counts() == before


@pytest.mark.parametrize('body', [{'user_id': 0}, {'user_id': 999999}, {'discount_percent': 100}])
def test_invalid_rsvp_body_or_unknown_customer(cafe, user, body):
    event_id = cafe.client.get('/api/events').json()['events'][0]['event_id']
    response = cafe.client.post(f'/api/events/{event_id}/rsvp', headers=cafe.headers(user), json=body)
    assert response.status_code == (404 if body.get('user_id') == 999999 else 422)


@pytest.mark.parametrize('age,eligible', [
    (timedelta(days=6, hours=23), False), (timedelta(days=7), False),
    (timedelta(days=7, microseconds=1), True), (timedelta(days=8), True),
])
def test_return_discount_strictly_more_than_seven_days(cafe, user, frozen_now, age, eligible):
    previous = cafe.order(user)
    cafe.complete(previous)
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE orders SET created_at=? WHERE order_id=?',
                           ((frozen_now - age).isoformat(), previous['order_id']))
    assert cafe.profile(user)['return_discount_eligible'] is eligible
    order = cafe.order(user)
    assert order['subtotal_amount'] == 18
    assert order['discount_amount'] == (3.60 if eligible else 0)
    assert order['total_amount'] == (14.40 if eligible else 18)
    assert order['points_earned'] == (144 if eligible else 180)
    assert cafe.profile(user)['return_discount_eligible'] is False
    assert cafe.order(user)['discount_amount'] == 0


def test_new_customer_and_cancelled_only_customer_are_not_inactive(cafe, user, frozen_now):
    assert cafe.profile(user)['return_discount_eligible'] is False
    order = cafe.order(user)
    cafe.advance(order, 'cancelled')
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE orders SET created_at=? WHERE order_id=?',
                           ((frozen_now - timedelta(days=30)).isoformat(), order['order_id']))
    assert cafe.profile(user)['return_discount_eligible'] is False
    assert cafe.order(user)['discount_amount'] == 0


def test_cancelled_checkouts_do_not_reset_inactivity_and_cancelled_return_offer_is_restored(cafe, user, frozen_now):
    previous = cafe.order(user)
    cafe.complete(previous)
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE orders SET created_at=? WHERE order_id=?',
                           ((frozen_now - timedelta(days=8)).isoformat(), previous['order_id']))
    first = cafe.order(user)
    assert first['discount_amount'] == 3.60
    assert cafe.profile(user)['return_discount_eligible'] is False
    cafe.advance(first, 'cancelled')
    assert cafe.profile(user)['return_discount_eligible'] is True
    assert cafe.order(user)['discount_amount'] == 3.60


@pytest.mark.parametrize('event_percent,expected_discount', [(15, 3.60), (20, 3.60), (25, 4.50)])
def test_return_and_event_discounts_use_better_offer_never_stack(cafe, user, frozen_now, event_percent, expected_discount):
    previous = cafe.order(user)
    cafe.complete(previous)
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE orders SET created_at=? WHERE order_id=?',
                           ((frozen_now - timedelta(days=8)).isoformat(), previous['order_id']))
        connection.execute('UPDATE club_events SET discount_percent=?', (event_percent,))
    reward = cafe.reward(user)
    order = cafe.order(user, promo_token=reward['token'])
    assert order['subtotal_amount'] == 18
    assert order['discount_amount'] == expected_discount
    assert order['total_amount'] == round(18 - expected_discount, 2)
    assert cafe.post(user, promo_token=reward['token']).status_code == 409


def test_platinum_upgrade_applies_before_event_discount_and_points(cafe, user, frozen_now):
    cafe.loyalty(user, 1500, 'Platinum')
    reward = cafe.reward(user)
    order = cafe.order(user, promo_token=reward['token'])
    assert order['used_upgrade'] == 1
    assert order['items'][0]['price'] == order['subtotal_amount'] == 16
    assert order['discount_amount'] == 2.40
    assert order['total_amount'] == 13.60
    assert order['points_earned'] == 136
    cafe.complete(order)
    assert cafe.profile(user)['loyalty_points'] == 1636
