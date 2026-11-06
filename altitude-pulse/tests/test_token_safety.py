"""Malformed URL credentials must fail authorization, not crash the request."""
from backend.crud import token_matches


def test_non_ascii_order_tokens_are_rejected_safely(cafe, user):
    order = cafe.order(user)
    assert not token_matches('incorrect-☕', order['access_token'])
    response = cafe.client.get(
        f'/api/orders/queue/{order["order_id"]}', params={'token': 'incorrect-☕'}
    )
    assert response.status_code == 403
