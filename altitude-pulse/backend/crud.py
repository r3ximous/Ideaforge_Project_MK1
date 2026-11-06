"""Order invariants and derived views. All mutations run in immediate transactions."""
import secrets
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException

ACTIVE = ('pending', 'preparing', 'ready')
TRANSITIONS = {
    'pending': {'preparing', 'cancelled'},
    'preparing': {'ready', 'cancelled'},
    'ready': {'completed'},
    'completed': set(), 'cancelled': set(),
}


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def tier_for(points):
    return 'Platinum' if points >= 1500 else 'Gold' if points >= 500 else 'Base'


def get_user(connection, user_id):
    row = connection.execute('SELECT * FROM users WHERE user_id=?', (user_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Customer not found')
    return dict(row)


def return_eligible(connection, user_id):
    # No orders is a new customer, not an inactive customer. Ignore cancelled checkouts.
    last = connection.execute(
        "SELECT MAX(created_at) FROM orders WHERE user_id=? AND status!='cancelled'", (user_id,)
    ).fetchone()[0]
    if not last:
        return False
    parsed = datetime.fromisoformat(last.replace('Z', '+00:00'))
    return (datetime.now(timezone.utc) - parsed).total_seconds() > 7 * 86400


def profile(connection, user_id):
    user = get_user(connection, user_id)
    user['return_discount_eligible'] = return_eligible(connection, user_id)
    user['monthly_upgrade_available'] = (
        user['tier'] == 'Platinum' and user['upgrade_month'] != datetime.now(timezone.utc).strftime('%Y-%m')
        and not connection.execute(
            "SELECT 1 FROM orders WHERE user_id=? AND used_upgrade=1 AND status IN ('pending','preparing','ready')",
            (user_id,),
        ).fetchone()
    )
    return user


def token_matches(supplied: str | None, expected: str) -> bool:
    # Bytes comparison also rejects non-ASCII input without compare_digest raising.
    return bool(supplied) and secrets.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8'))


def require_customer(connection, user_id, token):
    user = get_user(connection, user_id)
    if not token_matches(token, user['access_token']):
        raise HTTPException(403, 'Customer access token required')
    return user


def order_view(connection, order_id):
    row = connection.execute('SELECT * FROM orders WHERE order_id=?', (order_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Order not found')
    order = dict(row)
    order['items'] = [dict(item) for item in connection.execute(
        'SELECT * FROM order_items WHERE order_id=? ORDER BY order_item_id', (order_id,)
    )]
    ahead = 0
    if order['status'] in ('pending', 'preparing'):
        ahead = connection.execute(
            """SELECT COUNT(*) FROM orders WHERE status IN ('pending','preparing')
            AND (created_at < ? OR (created_at = ? AND order_id < ?))""",
            (order['created_at'], order['created_at'], order_id),
        ).fetchone()[0]
    order['orders_ahead'] = ahead
    order['queue_position'] = ahead + 1 if order['status'] in ('pending', 'preparing') else 0
    order['points_awarded'] = order['status'] == 'completed'
    return order


def create_user(db, request):
    try:
        with db.connect(write=True) as connection:
            cursor = connection.execute(
                'INSERT INTO users(name,phone_number,access_token) VALUES(?,?,?)',
                (request.name, request.phone_number, secrets.token_urlsafe(32)),
            )
            return profile(connection, cursor.lastrowid)
    except sqlite3.IntegrityError as error:
        raise HTTPException(409, 'Phone already registered. Use the original browser profile; demo accounts have no recovery flow.') from error


def create_order(db, request, token):
    with db.connect(write=True) as connection:
        user = require_customer(connection, request.user_id, token)
        eligible = return_eligible(connection, request.user_id)
        discount = 20 if eligible else 0
        if request.promo_token:
            promo = connection.execute(
                'SELECT * FROM event_rsvps WHERE token=? AND user_id=?',
                (request.promo_token, request.user_id),
            ).fetchone()
            if not promo or promo['redeemed_order_id'] is not None:
                raise HTTPException(409, 'Discount token is invalid or has already been redeemed')
            discount = max(discount, promo['discount_percent'])
        lines = []
        upgrade_available = profile(connection, request.user_id)['monthly_upgrade_available']
        used_upgrade = False
        for line in request.items:
            item = connection.execute('SELECT * FROM menu_items WHERE item_id=?', (line.item_id,)).fetchone()
            if not item:
                raise HTTPException(422, f'Menu item {line.item_id} is unavailable')
            pastry = item['category'] == 'Pastry'
            if (pastry and line.item_size != 'Standard') or (not pastry and line.item_size == 'Standard'):
                raise HTTPException(422, f'Invalid size for {item["name"]}')
            price = money(item['price'])
            if not pastry and line.item_size == '12oz':
                price -= Decimal('2.00')
            elif not pastry and upgrade_available and not used_upgrade:
                price -= Decimal('2.00')
                used_upgrade = True
            lines.append((line, item['name'], price))
        subtotal = sum((line[2] for line in lines), Decimal('0.00'))
        reduction = money(subtotal * Decimal(discount) / 100)
        total = subtotal - reduction
        points = int(total * 10 * (Decimal('1.10') if user['tier'] == 'Gold' else Decimal('1')))
        cursor = connection.execute(
            """INSERT INTO orders(user_id,customer_name,access_token,order_type,table_number,
            subtotal_amount,discount_amount,total_amount,points_earned,payment_method,promo_token,used_upgrade)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (request.user_id, request.customer_name, secrets.token_urlsafe(32), request.order_type,
             request.table_number, float(subtotal), float(reduction), float(total), points,
             request.payment_method, request.promo_token, int(used_upgrade)),
        )
        order_id = cursor.lastrowid
        for index, (line, name, price) in enumerate(lines):
            connection.execute(
                """INSERT INTO order_items(order_id,item_id,item_name,item_size,customization,price,item_code)
                VALUES(?,?,?,?,?,?,?)""",
                (order_id, line.item_id, name, line.item_size, line.customization, float(price),
                 f'{order_id}-{chr(65 + index)}'),
            )
        if request.promo_token:
            connection.execute('UPDATE event_rsvps SET redeemed_order_id=? WHERE token=?', (order_id, request.promo_token))
        connection.execute(
            "INSERT INTO order_logs(order_id,new_status,source) VALUES(?,'pending','mock_checkout')", (order_id,)
        )
        return order_view(connection, order_id)


def update_status(db, order_id, status, source='kds'):
    with db.connect(write=True) as connection:
        order = order_view(connection, order_id)
        previous = order['status']
        # Idempotent delivery: repeated clicks/webhooks do not award points twice.
        if previous == status:
            return order
        if status not in TRANSITIONS[previous]:
            raise HTTPException(409, f'Cannot move an order from {previous} to {status}')
        connection.execute(
            """UPDATE orders SET status=?, completed_at=CASE WHEN ?='completed'
            THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE completed_at END WHERE order_id=?""",
            (status, status, order_id),
        )
        if status == 'completed':
            user = get_user(connection, order['user_id'])
            points = user['loyalty_points'] + order['points_earned']
            month = datetime.now(timezone.utc).strftime('%Y-%m') if order['used_upgrade'] else user['upgrade_month']
            connection.execute(
                'UPDATE users SET loyalty_points=?,tier=?,upgrade_month=? WHERE user_id=?',
                (points, tier_for(points), month, order['user_id']),
            )
        if status == 'cancelled' and order['promo_token']:
            connection.execute('UPDATE event_rsvps SET redeemed_order_id=NULL WHERE redeemed_order_id=?', (order_id,))
        connection.execute(
            'INSERT INTO order_logs(order_id,old_status,new_status,source) VALUES(?,?,?,?)',
            (order_id, previous, status, source),
        )
        return order_view(connection, order_id)


def menu(db):
    with db.connect() as connection:
        items = [dict(row) for row in connection.execute('SELECT * FROM menu_items ORDER BY item_id')]
        popular = [dict(row) for row in connection.execute(
            """SELECT m.*, COUNT(oi.order_item_id) AS popularity_index
            FROM menu_items m LEFT JOIN order_items oi ON oi.item_id=m.item_id
            AND oi.order_id IN (SELECT order_id FROM orders WHERE status!='cancelled'
              AND julianday(created_at) >= julianday('now','-24 hours'))
            GROUP BY m.item_id ORDER BY popularity_index DESC,m.is_popular DESC,m.item_id LIMIT 3"""
        )]
        return {'items': items, 'popular': popular, 'promotion': next((item for item in items if item['is_promo']), None)}
