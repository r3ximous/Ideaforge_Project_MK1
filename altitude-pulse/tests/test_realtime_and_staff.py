import pytest
from starlette.websockets import WebSocketDisconnect


@pytest.mark.parametrize('path', ['/api/kds/active', '/api/kds/status', '/api/mock/mobipos/webhook'])
@pytest.mark.parametrize('credential', ['missing', 'wrong', 'customer', 'order'])
def test_staff_routes_require_staff_key(cafe, user, path, credential):
    order = cafe.order(user)
    headers = {
        'missing': {}, 'wrong': {'X-Staff-Key': 'wrong'},
        'customer': cafe.headers(user), 'order': {'X-Staff-Key': order['access_token']},
    }[credential]
    before = cafe.snapshot(order)
    logs = cafe.logs(order)
    if path == '/api/kds/active':
        response = cafe.client.get(path, headers=headers)
    else:
        response = cafe.client.post(path, headers=headers,
                                    json={'order_id': order['order_id'], 'status': 'preparing'})
    assert response.status_code == 403
    assert order['access_token'] not in response.text
    assert cafe.snapshot(order) == before
    assert cafe.logs(order) == logs


def test_mock_webhook_uses_same_state_machine_and_audits_source(cafe, user):
    order = cafe.order(user)
    endpoint = '/api/mock/mobipos/webhook'
    assert cafe.status(order, 'completed', endpoint).status_code == 409
    for status in ('preparing', 'ready', 'completed'):
        response = cafe.status(order, status, endpoint)
        assert response.status_code == 200
        assert response.json()['status'] == status
    assert cafe.profile(user)['loyalty_points'] == order['points_earned']
    assert [entry['source'] for entry in cafe.logs(order)] == [
        'mock_checkout', 'mock_mobipos', 'mock_mobipos', 'mock_mobipos']
    assert cafe.status(order, 'completed', endpoint).status_code == 200
    assert len(cafe.logs(order)) == 4
    assert cafe.profile(user)['loyalty_points'] == order['points_earned']
    assert cafe.status(order, 'cancelled', endpoint).status_code == 409


@pytest.mark.parametrize('endpoint', ['/api/kds/status', '/api/mock/mobipos/webhook'])
def test_staff_mutations_validate_status_and_missing_order(cafe, endpoint):
    headers = {'X-Staff-Key': 'test-key'}
    assert cafe.client.post(endpoint, headers=headers,
                            json={'order_id': 999999, 'status': 'preparing'}).status_code == 404
    for body in ({'order_id': 0, 'status': 'preparing'}, {'order_id': 1, 'status': 'paid'},
                 {'order_id': 1, 'status': 'pending'},
                 {'order_id': 1, 'status': 'preparing', 'points_earned': 999}):
        assert cafe.client.post(endpoint, headers=headers, json=body).status_code == 422


def test_websocket_immediately_sends_snapshot_and_updates_through_ready_and_completion(cafe, user):
    order = cafe.order(user)
    url = f'/ws/orders/{order["order_id"]}?token={order["access_token"]}'
    with cafe.client.websocket_connect(url) as socket:
        assert socket.receive_json() == cafe.snapshot(order)
        for status in ('preparing', 'ready', 'completed'):
            expected = cafe.advance(order, status)
            snapshot = socket.receive_json()
            assert snapshot == expected
            assert snapshot == cafe.snapshot(order)
            assert snapshot['status'] == status
            if status == 'ready':
                assert snapshot['queue_position'] == 0
                assert snapshot['orders_ahead'] == 0
                assert snapshot['points_awarded'] is False
        assert snapshot['points_awarded'] is True


def test_websocket_refreshes_other_customers_queue_when_order_becomes_ready(cafe, user):
    first = cafe.order(user)
    other = cafe.register()
    second = cafe.order(other)
    urls = [f'/ws/orders/{order["order_id"]}?token={order["access_token"]}' for order in (first, second)]
    with cafe.client.websocket_connect(urls[0]) as first_socket, cafe.client.websocket_connect(urls[1]) as second_socket:
        assert first_socket.receive_json()['queue_position'] == 1
        assert second_socket.receive_json()['queue_position'] == 2
        cafe.advance(first, 'preparing')
        assert first_socket.receive_json()['status'] == 'preparing'
        assert second_socket.receive_json()['orders_ahead'] == 1
        cafe.advance(first, 'ready')
        assert first_socket.receive_json()['status'] == 'ready'
        snapshot = second_socket.receive_json()
        assert snapshot['status'] == 'pending'
        assert snapshot['queue_position'] == 1
        assert snapshot['orders_ahead'] == 0
        assert snapshot['order_id'] == second['order_id']
        assert snapshot['access_token'] == second['access_token']


def test_multiple_sockets_receive_checkout_and_cancel_updates_and_disconnect_cleanly(cafe, user):
    order = cafe.order(user)
    url = f'/ws/orders/{order["order_id"]}?token={order["access_token"]}'
    with cafe.client.websocket_connect(url) as remaining:
        remaining.receive_json()
        with cafe.client.websocket_connect(url) as departing:
            assert departing.receive_json()['order_id'] == order['order_id']
            cafe.order(user)
            assert remaining.receive_json()['status'] == 'pending'
            assert departing.receive_json()['status'] == 'pending'
        cafe.advance(order, 'cancelled')
        assert remaining.receive_json()['status'] == 'cancelled'
    with cafe.client.websocket_connect(url) as reconnected:
        assert reconnected.receive_json() == cafe.snapshot(order)


@pytest.mark.parametrize('credential', ['missing', 'wrong', 'customer', 'other_order', 'staff', 'unknown_order'])
def test_websocket_rejects_unauthorized_clients_with_policy_violation(cafe, user, credential):
    order = cafe.order(user)
    other = cafe.order(user)
    token = {'missing': None, 'wrong': 'wrong', 'customer': user['access_token'],
             'other_order': other['access_token'], 'staff': 'test-key',
             'unknown_order': order['access_token']}[credential]
    order_id = 999999 if credential == 'unknown_order' else order['order_id']
    url = f'/ws/orders/{order_id}' + (f'?token={token}' if token else '')
    with pytest.raises(WebSocketDisconnect) as error:
        with cafe.client.websocket_connect(url):
            pytest.fail('An unauthorized socket was accepted')
    assert error.value.code == 1008
