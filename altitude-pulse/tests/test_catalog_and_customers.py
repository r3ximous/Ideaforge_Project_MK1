from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.seed_data import MENU, seed


def test_health_identifies_mock_payment_and_single_process_realtime(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'payments': 'mock', 'realtime': 'single-process'}


def test_menu_seed_and_frontend_shape(client, cafe):
    response = client.get('/api/menu')
    assert response.status_code == 200
    menu = response.json()
    assert set(menu) == {'items', 'popular', 'promotion'}
    assert len(menu['items']) == len(MENU) == 8
    assert {item['category'] for item in menu['items']} == {'Coffee', 'Tea', 'Cold Drinks', 'Pastry', 'Special'}
    for item, expected in zip(menu['items'], MENU):
        assert {'item_id', 'name', 'category', 'price', 'description', 'is_promo',
                'is_popular', 'model_3d_url'} <= item.keys()
        assert (item['name'], item['category'], item['price'], item['description'],
                item['is_promo'], item['is_popular']) == expected
        assert item['model_3d_url'] == (None if item['category'] == 'Pastry' else '/assets/models/cup_16oz.glb')
    assert menu['promotion'] == cafe.menu['Caramel Cloud Latte']
    assert [(item['name'], item['popularity_index']) for item in menu['popular']] == [
        ('Iced Latte', 3), ('Cold Brew', 2), ('Butter Croissant', 1)]
    assert cafe.active() == []


def test_seed_is_idempotent_including_tokens_and_sales(db, client):
    tables = ('users', 'menu_items', 'orders', 'order_items', 'club_events', 'event_rsvps', 'order_logs')

    def snapshot():
        with db.connect() as connection:
            return {table: [tuple(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in tables}

    original = snapshot()
    seed(db)
    db.initialize()
    seed(db)
    assert snapshot() == original


def test_restarting_app_does_not_duplicate_seed(tmp_path):
    path = tmp_path / 'restart.sqlite3'
    first_app = create_app(db_path=path, staff_key='test-key')
    with TestClient(first_app) as client:
        original = client.get('/api/menu').json()
    second_app = create_app(db_path=path, staff_key='test-key')
    with TestClient(second_app) as client:
        assert client.get('/api/menu').json() == original
        with second_app.state.db.connect() as connection:
            assert connection.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 6


def test_seed_demo_can_be_disabled(tmp_path):
    with TestClient(create_app(db_path=tmp_path / 'empty.sqlite3', staff_key='test-key', seed_demo=False)) as client:
        assert client.get('/api/menu').json() == {'items': [], 'popular': [], 'promotion': None}
        assert client.get('/api/events').json() == {'events': []}
        assert client.get('/api/kds/active', headers={'X-Staff-Key': 'test-key'}).json() == {'orders': []}


def test_popularity_counts_individual_recent_non_cancelled_sales(cafe, user):
    # A new bestseller has five cups, not one checkout.
    recent = cafe.order(user, [cafe.line('Chocolate Cookie') for _ in range(5)])
    cancelled = cafe.order(user, [cafe.line('Peach Iced Tea') for _ in range(6)])
    cafe.advance(cancelled, 'cancelled')
    old = cafe.order(user, [cafe.line('Matcha on Ice') for _ in range(7)])
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE orders SET created_at=? WHERE order_id=?',
                           ((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), old['order_id']))
    popular = cafe.client.get('/api/menu').json()['popular']
    assert [(item['name'], item['popularity_index']) for item in popular] == [
        ('Chocolate Cookie', 5), ('Iced Latte', 3), ('Cold Brew', 2)]
    cafe.complete(recent)
    assert cafe.client.get('/api/menu').json()['popular'] == popular


def test_popularity_ties_use_seed_flags_then_item_id(cafe):
    with cafe.db.connect(write=True) as connection:
        connection.execute("UPDATE orders SET created_at='2000-01-01T00:00:00Z'")
    popular = cafe.client.get('/api/menu').json()['popular']
    assert [(item['name'], item['popularity_index']) for item in popular] == [
        ('Iced Latte', 0), ('Cold Brew', 0), ('Butter Croissant', 0)]


def test_registration_normalizes_and_starts_with_private_base_profile(cafe):
    user = cafe.register(name='  Ada Lovelace  ', phone_number='+971 (50) 123-4567')
    assert user['name'] == 'Ada Lovelace'
    assert user['phone_number'] == '+971501234567'
    assert isinstance(user['user_id'], int)
    assert len(user['access_token']) >= 32
    assert user['loyalty_points'] == 0
    assert user['tier'] == 'Base'
    assert user['return_discount_eligible'] is False
    assert user['monthly_upgrade_available'] is False
    assert user['upgrade_month'] is None
    assert user['created_at']
    assert cafe.profile(user) == user
    assert cafe.history(user) == []


def test_duplicate_normalized_phone_does_not_recover_or_change_identity(cafe):
    user = cafe.register(phone_number='+971 (50) 123-4567')
    response = cafe.client.post('/api/users', json={'name': 'Impersonator', 'phone_number': '+971501234567'})
    assert response.status_code == 409
    assert set(response.json()) == {'detail'}
    assert user['access_token'] not in response.text
    assert cafe.profile(user) == user


@pytest.mark.parametrize('body', [
    {'name': '', 'phone_number': '1234567'},
    {'name': '   ', 'phone_number': '1234567'},
    {'name': 'x' * 61, 'phone_number': '1234567'},
    {'name': 'Ada', 'phone_number': '123456'},
    {'name': 'Ada', 'phone_number': '1' * 16},
    {'name': 'Ada', 'phone_number': '+971abc1234567'},
    {'name': 'Ada', 'phone_number': '123+4567'},
    {'name': 'Ada', 'phone_number': '-------'},
    {'name': 'Ada', 'phone_number': '1234567', 'loyalty_points': 1500},
    {'name': 'Ada', 'phone_number': '1234567', 'tier': 'Platinum'},
    {'name': 'Ada', 'phone_number': '1234567', 'access_token': 'chosen'},
    {'name': 'Ada'},
])
def test_invalid_registration_is_atomic(cafe, body):
    before = cafe.counts()
    assert cafe.client.post('/api/users', json=body).status_code == 422
    assert cafe.counts() == before


@pytest.mark.parametrize('suffix', ['', '/history'])
@pytest.mark.parametrize('credential', ['missing', 'wrong', 'other_user', 'order'])
def test_profile_and_history_require_own_customer_token(cafe, user, suffix, credential):
    other = cafe.register()
    order = cafe.order(user)
    tokens = {'wrong': 'not-a-token', 'other_user': other['access_token'], 'order': order['access_token']}
    headers = {} if credential == 'missing' else {'X-Customer-Token': tokens[credential]}
    response = cafe.client.get(f'/api/users/{user["user_id"]}{suffix}', headers=headers)
    assert response.status_code == 403
    assert user['phone_number'] not in response.text
    assert user['access_token'] not in response.text
    assert order['access_token'] not in response.text


def test_history_is_private_latest_first_and_includes_terminal_receipts(cafe, user):
    first = cafe.order(user)
    second = cafe.order(user, [cafe.line('Butter Croissant')])
    third = cafe.order(user)
    cafe.complete(first)
    cafe.advance(second, 'cancelled')
    other = cafe.register()
    cafe.order(other)
    with cafe.db.connect(write=True) as connection:
        connection.execute("UPDATE orders SET created_at='2030-01-01T00:00:00Z' WHERE user_id=?", (user['user_id'],))
    history = cafe.history(user)
    assert [order['order_id'] for order in history] == [third['order_id'], second['order_id'], first['order_id']]
    assert [order['status'] for order in history] == ['pending', 'cancelled', 'completed']
    for order in history:
        assert order['user_id'] == user['user_id']
        assert order['access_token']
        assert order['access_token'] != user['access_token']
        assert order == cafe.snapshot(order)


def test_missing_customer_and_order_return_404(client):
    for path in ('/api/users/999999', '/api/users/999999/history', '/api/orders/queue/999999'):
        assert client.get(path, headers={'X-Customer-Token': 'wrong'}).status_code == 404


def test_public_feeds_never_expose_demo_customer_secrets(client, db):
    with db.connect() as connection:
        user = dict(connection.execute('SELECT * FROM users').fetchone())
        tokens = [row[0] for row in connection.execute('SELECT access_token FROM orders')]
    for path in ('/api/menu', '/api/events', '/api/health'):
        response = client.get(path)
        assert response.status_code == 200
        assert user['access_token'] not in response.text
        assert user['phone_number'] not in response.text
        assert all(token not in response.text for token in tokens)
