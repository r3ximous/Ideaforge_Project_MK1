from decimal import Decimal

import pytest


def test_checkout_matches_frontend_payload_receipt_and_individual_badges(cafe, user):
    lines = [cafe.line(customization=' Oat milk, less ice '), cafe.line(),
             cafe.line(size='12oz'), cafe.line('Butter Croissant')]
    order = cafe.order(user, lines, order_type='table', table_number=' 04 ', payment_method='apple_pay')
    assert {'order_id', 'user_id', 'customer_name', 'access_token', 'order_type', 'table_number',
            'subtotal_amount', 'discount_amount', 'total_amount', 'points_earned', 'points_awarded',
            'payment_method', 'payment_status', 'status', 'created_at', 'completed_at', 'items',
            'orders_ahead', 'queue_position', 'used_upgrade'} <= order.keys()
    assert order['customer_name'] == user['name']
    assert order['user_id'] == user['user_id']
    assert order['order_type'] == 'table'
    assert order['table_number'] == '04'
    assert order['subtotal_amount'] == order['total_amount'] == 64
    assert order['discount_amount'] == 0
    assert order['payment_method'] == 'apple_pay'
    assert order['payment_status'] == 'mock_paid'
    assert order['points_earned'] == 640
    assert order['points_awarded'] is False
    assert order['status'] == 'pending'
    assert order['completed_at'] is None
    assert order['queue_position'] == 1
    assert order['orders_ahead'] == 0
    assert len(order['access_token']) >= 32
    assert order['access_token'] != user['access_token']
    assert len(order['items']) == 4
    for index, (item, requested) in enumerate(zip(order['items'], lines)):
        assert {'order_item_id', 'order_id', 'item_id', 'item_name', 'item_size',
                'customization', 'price', 'item_code'} <= item.keys()
        assert item['order_id'] == order['order_id']
        assert item['item_id'] == requested['item_id']
        assert item['item_size'] == requested['item_size']
        assert item['customization'] == requested['customization'].strip()
        assert item['item_code'] == f'{order["order_id"]}-{chr(65 + index)}'
    assert [item['price'] for item in order['items']] == [18, 18, 16, 12]
    assert cafe.profile(user)['loyalty_points'] == 0
    assert cafe.snapshot(order) == order


@pytest.mark.parametrize('name,size,price', [
    ('Iced Latte', '16oz', 18), ('Iced Latte', '12oz', 16),
    ('Cold Brew', '16oz', 20), ('Cold Brew', '12oz', 18),
    ('Matcha on Ice', '12oz', 20), ('Peach Iced Tea', '12oz', 14),
    ('Caramel Cloud Latte', '12oz', 22), ('Flat White', '12oz', 16),
    ('Butter Croissant', 'Standard', 12), ('Chocolate Cookie', 'Standard', 10),
])
def test_server_prices_all_categories_and_sizes(cafe, user, name, size, price):
    order = cafe.order(user, [cafe.line(name, size)])
    assert order['items'][0]['price'] == order['subtotal_amount'] == order['total_amount'] == price
    assert order['points_earned'] == price * 10


def test_server_reads_current_catalog_price_and_snapshots_receipt(cafe, user):
    item = cafe.menu['Iced Latte']
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE menu_items SET price=19.99 WHERE item_id=?', (item['item_id'],))
    order = cafe.order(user, [cafe.line(size='12oz')])
    assert order['total_amount'] == 17.99
    assert order['points_earned'] == 179
    with cafe.db.connect(write=True) as connection:
        connection.execute("UPDATE menu_items SET price=30,name='Renamed latte' WHERE item_id=?", (item['item_id'],))
    assert cafe.snapshot(order)['items'] == order['items']
    assert cafe.snapshot(order)['total_amount'] == 17.99


def test_takeaway_discards_table_number_and_defaults_are_frontend_compatible(cafe, user):
    response = cafe.client.post('/api/orders', headers=cafe.headers(user), json={
        'user_id': user['user_id'], 'customer_name': user['name'],
        'items': [{'item_id': cafe.menu['Iced Latte']['item_id']}], 'table_number': '04',
    })
    assert response.status_code == 201, response.text
    order = response.json()
    assert order['order_type'] == 'takeaway'
    assert order['table_number'] is None
    assert order['payment_method'] == 'card'
    assert order['items'][0]['item_size'] == '16oz'
    assert order['items'][0]['customization'] == ''


@pytest.mark.parametrize('count', [1, 26])
def test_badges_are_unique_through_z_and_across_orders(cafe, user, count):
    first = cafe.order(user, [cafe.line() for _ in range(count)])
    second = cafe.order(user, [cafe.line() for _ in range(count)])
    for order in (first, second):
        assert [item['item_code'] for item in order['items']] == [
            f'{order["order_id"]}-{chr(65 + index)}' for index in range(count)]
    items = first['items'] + second['items']
    assert len({item['item_code'] for item in items}) == count * 2
    assert len({item['order_item_id'] for item in items}) == count * 2


@pytest.mark.parametrize('patch', [
    {'items': []}, {'items': [{'item_id': 0}]}, {'items': [{'item_id': -1}]},
    {'items': [{'item_id': 999999}]}, {'items': [{'item_id': 1, 'item_size': '20oz'}]},
    {'items': [{'item_id': 1, 'item_size': 'Standard'}]},
    {'items': [{'item_id': 3, 'item_size': '16oz'}]},
    {'items': [{'item_id': 3, 'item_size': '12oz'}]},
    {'items': [{'item_id': 1, 'customization': 'x' * 201}]},
    {'customer_name': ''}, {'customer_name': '   '}, {'customer_name': 'x' * 61},
    {'order_type': 'delivery'}, {'order_type': 'table'},
    {'order_type': 'table', 'table_number': ''},
    {'order_type': 'table', 'table_number': '   '},
    {'order_type': 'table', 'table_number': '1' * 13},
    {'payment_method': 'cash'}, {'payment_method': 'paid'},
    {'promo_token': 'x' * 129}, {'user_id': 0},
    {'items': [{'item_id': 1}] * 27},
])
def test_checkout_validation_is_atomic(cafe, user, patch):
    before = cafe.counts()
    response = cafe.client.post('/api/orders', headers=cafe.headers(user), json=cafe.payload(user, **patch))
    assert response.status_code == 422, response.text
    assert cafe.counts() == before
    assert cafe.history(user) == []
    assert cafe.profile(user)['loyalty_points'] == 0


@pytest.mark.parametrize('field,value', [
    ('total_amount', 0), ('subtotal_amount', 0), ('discount_amount', 999),
    ('points_earned', 99999), ('tier', 'Platinum'), ('status', 'completed'),
    ('payment_status', 'paid'), ('used_upgrade', True), ('access_token', 'chosen'),
    ('promo_code', 'AIRC'), ('discount_percent', 100),
])
def test_client_cannot_set_server_owned_checkout_fields(cafe, user, field, value):
    before = cafe.counts()
    response = cafe.post(user, **{field: value})
    assert response.status_code == 422
    assert cafe.counts() == before


@pytest.mark.parametrize('field,value', [('price', 0), ('quantity', 5), ('item_name', 'Free latte'), ('item_code', '1-A')])
def test_client_cannot_set_server_owned_line_fields(cafe, user, field, value):
    before = cafe.counts()
    response = cafe.post(user, [cafe.line(**{field: value})])
    assert response.status_code == 422
    assert cafe.counts() == before


@pytest.mark.parametrize('credential', ['missing', 'wrong', 'other_user', 'order', 'staff'])
def test_checkout_requires_matching_customer_token(cafe, user, credential):
    other = cafe.register()
    order = cafe.order(user)
    credentials = {
        'missing': {}, 'wrong': {'X-Customer-Token': 'wrong'},
        'other_user': cafe.headers(other),
        'order': {'X-Customer-Token': order['access_token']},
        'staff': {'X-Staff-Key': 'test-key'},
    }
    before = cafe.counts()
    response = cafe.client.post('/api/orders', headers=credentials[credential], json=cafe.payload(user))
    assert response.status_code == 403
    assert cafe.counts() == before


@pytest.mark.parametrize('credential', ['missing', 'wrong', 'customer', 'other_order', 'staff'])
def test_order_lookup_requires_its_own_order_token(cafe, user, credential):
    order = cafe.order(user)
    other = cafe.order(user)
    credentials = {
        'missing': {}, 'wrong': {'X-Customer-Token': 'wrong'},
        'customer': cafe.headers(user), 'other_order': {'X-Customer-Token': other['access_token']},
        'staff': {'X-Staff-Key': 'test-key'},
    }
    response = cafe.client.get(f'/api/orders/queue/{order["order_id"]}', headers=credentials[credential])
    assert response.status_code == 403
    assert order['access_token'] not in response.text
    assert user['name'] not in response.text


def test_order_token_works_in_query_or_header_but_not_as_customer_identity(cafe, user):
    order = cafe.order(user)
    response = cafe.client.get(f'/api/orders/queue/{order["order_id"]}',
                               headers={'X-Customer-Token': order['access_token']})
    assert response.status_code == 200
    assert response.json() == cafe.snapshot(order)
    assert cafe.client.get(f'/api/users/{user["user_id"]}',
                           headers={'X-Customer-Token': order['access_token']}).status_code == 403


def test_fractional_discount_is_rounded_once_half_up_before_points(cafe, user):
    with cafe.db.connect(write=True) as connection:
        connection.execute('UPDATE menu_items SET price=18.10 WHERE item_id=?', (cafe.menu['Iced Latte']['item_id'],))
    reward = cafe.reward(user)  # 15% of 18.10 = 2.715 => 2.72, not banker's rounding.
    order = cafe.order(user, promo_token=reward['token'])
    assert Decimal(str(order['subtotal_amount'])) == Decimal('18.10')
    assert Decimal(str(order['discount_amount'])) == Decimal('2.72')
    assert Decimal(str(order['total_amount'])) == Decimal('15.38')
    assert order['points_earned'] == 153
