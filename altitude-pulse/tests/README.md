# Altitude Pulse tests

Run from `altitude-pulse` after installing dependencies in your own environment:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests -o cache_dir=tests/.pytest_cache
```

Required environment packages: `pytest`, `fastapi`, Pydantic 2, `httpx`, and the
Starlette/AnyIO versions compatible with that FastAPI installation. No dependency
installation or backend/frontend edits are performed by this suite.

Each test uses `create_app(db_path=tmp_path / 'altitude.sqlite3', staff_key='test-key')`
and a context-managed FastAPI `TestClient`, so startup seeds and shutdown run.
Temporary SQLite databases do not touch the application's default database.
`sys.dont_write_bytecode` prevents backend bytecode writes. The cache override in
the command keeps pytest's persistent cache inside this directory. These tests do
not start Uvicorn, contact a payment provider, or need external network access.

## Coverage

- `test_catalog_and_customers.py`: seed/restart idempotence, live 24-hour popularity
  by individual items, deterministic ties, public feed shape, normalized unique
  registration, private identity/profile/history, ordered terminal receipts.
- `test_checkout.py`: the exact frontend request shape and receipt fields;
  authoritative catalog prices, sizes, decimal rounding, mock payment enums,
  per-item badge IDs A–Z, rejected tampering, malformed requests, token isolation,
  atomic failure, and historical price snapshots.
- `test_state_and_loyalty.py`: all 25 state/target combinations, idempotent status
  delivery, global queue ordering, ready orders removed from waiting positions but
  retained on KDS, terminal removal, completion-only points, Gold/Platinum threshold
  boundaries, Gold bonus/truncation, immutable anticipated points, cancellations,
  monthly Platinum upgrade reservation/consumption/release.
- `test_promotions.py`: event feed, authenticated/idempotent RSVP, customer-bound
  one-use rewards, cancellation release, rollback on validation and on a forced
  database error **after token redemption**, expired events, strict seven-day
  inactivity boundary, cancelled-order exclusion, return offer reservation,
  non-stacking discounts, and upgrade-before-discount ordering.
- `test_realtime_and_staff.py`: staff-only KDS/mock webhook, source audit logs,
  initial WebSocket snapshots, preparing/ready/completed updates, broadcasts that
  refresh another customer's queue, multiple subscribers/disconnect/reconnect,
  and unauthorized socket close code 1008.
- `test_transaction_races.py`: simultaneous reward redemption, completion points,
  monthly upgrade reservation, and return-offer reservation.
- `test_token_safety.py`: malformed non-ASCII URL tokens fail authorization without a server error.
- `test_static_and_frontend_contract.py`: served HTML/modules/styles/icons,
  manifest/icon dimensions/shortcuts, every service worker precache URL, privacy
  cache headers, 404 behavior, GLB resources, and frontend/API limit agreement.

## Explicit frontend contract

Derived from the existing frontend code, not an invented API:

- `js/shared.js` registers `{name, phone_number}` at `POST /api/users`, stores
  `{user_id, access_token, name, phone_number, loyalty_points, tier, ...}`, and sends
  `X-Customer-Token` for profile/history, RSVP, and checkout. A duplicate phone
  must not expose an existing profile or recover its token.
- `js/app.js` reads `{items, popular, promotion}` from `GET /api/menu`; items have
  IDs, names, category, price, description, flags, and optional model URL. Drinks
  use `12oz`/`16oz`; pastries use `Standard`. Twelve-ounce drinks cost AED 2 less.
  Quantities are expanded to individual `{item_id, item_size, customization}` lines.
- Checkout sends `{user_id, customer_name, order_type, table_number, items,
  payment_method, promo_token?}` to `POST /api/orders`. Service is `takeaway` or
  `table`; payment is `card` or `apple_pay`. **No client price, loyalty, status,
  or discount percentage is submitted or trusted.**
- Checkout/history/tracker retain a separate order `access_token`. Tracking uses
  `GET /api/orders/queue/{id}?token=...` and `/ws/orders/{id}?token=...`.
  The receipt includes item names/sizes/customizations/prices/unique `item_code`,
  subtotal/discount/total, `mock_paid`, anticipated points, status, and timestamps.
  `orders_ahead`/`queue_position` appear only while pending/preparing.
- `js/kds.js` sends `X-Staff-Key` to `GET /api/kds/active` and
  `POST /api/kds/status` with `{order_id, status}`. Transitions are
  pending → preparing → ready → completed. Cancellation is offered only while
  pending/preparing. Ready remains active for handoff but no longer blocks queues.
- `js/app.js` reads `{events}` from `GET /api/events`, posts `{user_id}` to
  `/api/events/{event_id}/rsvp`, and submits the returned opaque `token` at checkout.
  Public `promo_code` is display-only. Return/event offers use the better discount,
  never their sum. Points arrive on completion, not checkout.
- `js/shared.js` registers `/sw.js`; the worker explicitly precaches only public
  shell URLs, never API responses, private tokens, POST requests, or GLB assets.
  Tests inspect that policy and URL availability; they **do not execute a browser**
  or claim to verify actual offline cache behavior, notifications, or AR rendering.

## Regression checks and recorded validation

Frontend/API input bounds are aligned (name 60, phone 24, customization 200,
 table number 12), and both original GLB cup models are present. Contract tests
keep those boundaries and asset requirements from regressing.

Recorded validation: **234 passed** on Python 3.14.7 using `requirements.lock.txt`.
Starlette emitted one upstream deprecation warning about its HTTPX test adapter;
there were no failing or skipped cases. This is server/contract validation, not
real-device verification of AR, browser notifications, or visual layout.
