"""Isolated API fixtures. Importing backend.main does not start its default app.

Run from altitude-pulse: .venv/bin/python -m pytest tests
All databases live under pytest's tmp_path, never backend/data or project data.
"""
import itertools
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Also support pytest launched from the workspace parent. Do not create backend
# bytecode files: this suite is intentionally allowed to write only under tests
# (and pytest's temporary database directory).
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.main import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=tmp_path / 'altitude.sqlite3', staff_key='test-key')


@pytest.fixture
def client(app):
    with TestClient(app) as session:
        yield session


@pytest.fixture
def db(app, client):
    return app.state.db


class Cafe:
    """Helpers assert setup success; tests assert the behavior under examination."""

    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.numbers = itertools.count(1)
        self.menu = {item['name']: item for item in client.get('/api/menu').json()['items']}

    def register(self, **overrides):
        body = {'name': 'Campus Customer', 'phone_number': f'+97151{next(self.numbers):07d}'}
        body.update(overrides)
        response = self.client.post('/api/users', json=body)
        assert response.status_code == 201, response.text
        return response.json()

    @staticmethod
    def headers(user):
        return {'X-Customer-Token': user['access_token']}

    def line(self, name='Iced Latte', size=None, **overrides):
        item = self.menu[name]
        body = {'item_id': item['item_id'],
                'item_size': size or ('Standard' if item['category'] == 'Pastry' else '16oz'),
                'customization': ''}
        body.update(overrides)
        return body

    def payload(self, user, items=None, **overrides):
        body = {'user_id': user['user_id'], 'customer_name': user['name'],
                'order_type': 'takeaway', 'table_number': None,
                'items': items if items is not None else [self.line()],
                'payment_method': 'card'}
        body.update(overrides)
        return body

    def post(self, user, items=None, **overrides):
        return self.client.post('/api/orders', headers=self.headers(user),
                                json=self.payload(user, items, **overrides))

    def order(self, user, items=None, **overrides):
        response = self.post(user, items, **overrides)
        assert response.status_code == 201, response.text
        return response.json()

    def profile(self, user):
        response = self.client.get(f'/api/users/{user["user_id"]}', headers=self.headers(user))
        assert response.status_code == 200, response.text
        return response.json()

    def history(self, user):
        response = self.client.get(f'/api/users/{user["user_id"]}/history', headers=self.headers(user))
        assert response.status_code == 200, response.text
        return response.json()['orders']

    def snapshot(self, order):
        response = self.client.get(f'/api/orders/queue/{order["order_id"]}',
                                   params={'token': order['access_token']})
        assert response.status_code == 200, response.text
        return response.json()

    def status(self, order, status, endpoint='/api/kds/status'):
        return self.client.post(endpoint, headers={'X-Staff-Key': 'test-key'},
                                json={'order_id': order['order_id'], 'status': status})

    def advance(self, order, *statuses):
        result = order
        for status in statuses:
            response = self.status(order, status)
            assert response.status_code == 200, response.text
            result = response.json()
        return result

    def complete(self, order):
        return self.advance(order, 'preparing', 'ready', 'completed')

    def active(self):
        response = self.client.get('/api/kds/active', headers={'X-Staff-Key': 'test-key'})
        assert response.status_code == 200, response.text
        return response.json()['orders']

    def rsvp(self, user, event_id=None):
        if event_id is None:
            event_id = self.client.get('/api/events').json()['events'][0]['event_id']
        return self.client.post(f'/api/events/{event_id}/rsvp', headers=self.headers(user),
                                json={'user_id': user['user_id']})

    def reward(self, user):
        response = self.rsvp(user)
        assert response.status_code == 200, response.text
        return response.json()

    def loyalty(self, user, points, tier, upgrade_month=None):
        with self.db.connect(write=True) as connection:
            connection.execute('UPDATE users SET loyalty_points=?,tier=?,upgrade_month=? WHERE user_id=?',
                               (points, tier, upgrade_month, user['user_id']))

    def logs(self, order):
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute(
                'SELECT * FROM order_logs WHERE order_id=? ORDER BY log_id', (order['order_id'],))]

    def counts(self):
        with self.db.connect() as connection:
            return {table: connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                    for table in ('users', 'orders', 'order_items', 'order_logs', 'event_rsvps')}


@pytest.fixture
def cafe(client, db):
    return Cafe(client, db)


@pytest.fixture
def user(cafe):
    return cafe.register()


@pytest.fixture
def frozen_now(monkeypatch):
    from datetime import datetime, timezone
    from backend import crud

    # Keep SQLite's real-time created_at defaults aligned with the frozen clock.
    instant = datetime.now(timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    monkeypatch.setattr(crud, 'datetime', Clock)
    return instant
