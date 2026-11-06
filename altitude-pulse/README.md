# Altitude Pulse ↗

A zero-build campus cafe ordering PWA for **Altitude Cafe · RIT Dubai**, created for ideaForge (AIRC × Altitude). One FastAPI process serves a mobile customer experience, private live receipts, and a staff kitchen display.

## Run locally

Python 3.10+ is required; tested with Python 3.14.7. Run commands from this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m uvicorn backend.main:app --reload
```

- Customer: http://127.0.0.1:8000
- Barista KDS: http://127.0.0.1:8000/kds.html
- API documentation: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health

Enter **`altitude-demo-staff`** on the KDS to unlock the local demo. The key is not embedded in the frontend. Set `ALTITUDE_STAFF_KEY` to a strong private value before sharing the service. The included default is deliberately **not production security**.

SQLite is created and seeded automatically at `data/altitude.db`. `ALTITUDE_DB` accepts an alternate path. Eight menu items, three upcoming club events, and six historical sales make the first demo useful without filling the KDS with fake active orders. Seed data is inserted only into an empty catalog; restarting does not duplicate it. With the server stopped, deleting the local database resets all demo state, including private accounts.

`requirements.txt` declares supported ranges; `requirements.lock.txt` captures the exact validated environment. No Node toolchain is required. Styling, app code, icons, and cup models are local. The optional 3D viewer loads from Google's model-viewer CDN, so that feature needs internet access and sends normal asset-request metadata to that provider.

## Two-minute demo

1. Open the customer page and KDS in separate tabs (or a phone and tablet).
2. Browse/search without registering. Open **3D / AR**, compare 12oz and 16oz, then close the preview.
3. Add a latte and croissant. Checkout creates a lightweight browser-bound profile—use a fictional name and a unique demo phone number. No SMS is sent and no real phone verification occurs.
4. Optionally RSVP to a campus event first; its one-use reward is saved automatically for checkout.
5. Choose takeaway or a table and **demo card / Apple Pay**. Neither option contacts a payment provider or charges money. No card details are collected.
6. Tracking shows the order, per-item codes such as `7-A`, individual cup labels, and live queue position. Tap **Enable alerts** before changing statuses to hear the chime.
7. On the KDS, tap **Start preparing → Mark ready → Complete**. The customer's tracker receives live updates; completing the order awards points exactly once.
8. Open **History**, inspect the receipt, and **Reorder** at current catalog prices.

Use another unique phone in an incognito browser to demonstrate two independent customers. Customer identity is deliberately not recoverable by entering a known phone: retain the original browser storage for that demo profile. For a queue example, create two orders before advancing the first.

### Mock POS alternative

For a pending order, replace `7` with its ID:

```sh
.venv/bin/python -m backend.mock_mobipos 7
```

This sends authenticated simulated `preparing` and `ready` events, two seconds apart. Add `--complete` for handoff. Use `--staff-key` or the `ALTITUDE_STAFF_KEY` environment variable if the server uses a custom key. This is an internal webhook simulation—not an official MOBIPOS integration, payment terminal connection, or proprietary protocol implementation.

## Campus phone / QR demo

For LAN testing, start Uvicorn with `--host 0.0.0.0`; use the computer's actual LAN hostname/address in the phone browser. Point a QR code at that **customer URL**, not the staff key or a private receipt token. This project doesn't depend on an external QR service.

Use an **HTTPS deployment** for a full phone demo. Ordinary LAN HTTP can display the menu but does not provide the secure context needed for service workers, notifications, or WebXR. `localhost` is treated specially only on the device actually running the server. Use one Uvicorn worker; WebSocket subscribers are in process memory.

For hosting, install dependencies and start:

```sh
.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Configure TLS at the host/reverse proxy, preserve WebSocket upgrades, set a private staff key, and mount persistent storage for `ALTITUDE_DB`. No cross-origin setup is needed: frontend and API intentionally share one origin.

## Implemented behavior

- **Authoritative checkout:** per-item catalog snapshots, decimal monetary calculations, supported sizes, individual A–Z badges, table validation, atomic writes, and mock-paid receipts. One line represents one physical item; an order supports up to 26 items.
- **Explicit state machine:** `pending → preparing → ready → completed`; pending/preparing may be cancelled. Duplicate status messages are idempotent. Terminal orders leave the KDS; ready orders stay for handoff.
- **Queue semantics:** `orders_ahead` counts older pending/preparing orders using creation time and ID as a deterministic tie-breaker. `queue_position = orders_ahead + 1`. Ready/terminal orders return position 0 because they no longer wait for preparation. Position is not an ETA.
- **Realtime:** token-authorized WebSocket snapshots plus five-second polling fallback. Every order mutation refreshes all connected queue watchers. The KDS polls every three seconds.
- **Loyalty:** 10 points per paid AED, fractional points rounded down. Gold (500–1,499 points at checkout) earns a 10% points bonus. Platinum (1,500+) gets one 16oz drink for the 12oz price per UTC calendar month. An active order reserves the upgrade; completion consumes it; cancellation releases it. Points are awarded only on completion, never on cancelled orders.
- **Discounts:** customers whose last non-cancelled order is more than seven days old receive 20% automatically. A new customer with no order history is not inactive. Event RSVP rewards are customer-bound and single-use, with atomic redemption and cancellation release. The better of event/return offers applies; they do not stack. Percentage discounts apply after the size-upgrade saving.
- **Popular Now:** top three menu items ranked by individual items ordered in the rolling 24 hours, excluding cancelled orders. Seed flags break ties; this is live sales aggregation, not personalized AI.
- **PWA:** manifest, install icons, accessible dialogs/navigation, responsive CSS, public-shell offline caching. APIs, private data, and order POSTs are never cached or queued offline.
- **AR:** original GLBs in meters, approximate 12oz/16oz cup dimensions, fixed AR scale. Android WebXR/Scene Viewer and iOS Quick Look are enabled; model-viewer generates USDZ on demand for iOS ([official documentation](https://modelviewer.dev/examples/augmentedreality/)). Device support varies. Regenerate the assets with `python3 scripts/generate_cups.py`.

## Validation

```sh
.venv/bin/python -m pytest tests -q
.venv/bin/python -m compileall -q backend scripts
```

**Recorded result: 234 passed.** Covers transactional races, state transitions, prices, rewards, loyalty, private access, queue broadcasts, WebSockets, static assets, manifest, and frontend/API contracts. One upstream Starlette/HTTPX test-adapter deprecation warning remains. See `tests/README.md`.

Real browser visual layout, physical-device AR, OS notification permissions, PWA installation, and sound output still require a manual device pass. The live frontend/backend browser journey has not been verified in an actual browser; the server lifecycle and API contracts are covered by integration tests.

## Demo limits / production checklist

- **No real payments, refunds, printer connection, SMS, or official POS adapter.** Apple Pay is a labeled simulation, not Apple's SDK.
- Alerts use a Web Audio chime after a user gesture and optional browser notifications while the tracker is open. **There is no background Web Push server/subscription delivery.** Suspended tabs may miss an intermediate ready state; reopening always refreshes the current order.
- Browser-bound bearer tokens protect access but are not a production authentication system. Use fictional data. Clearing storage loses access; proper OTP/login, recovery, rate limits, CSRF/session design, and staff roles are future work.
- WebSocket tokens travel in the connection URL. Avoid query-string logging at the deployment proxy; use TLS. `Referrer-Policy: no-referrer` and API `no-store` are set. Do not share private tokens.
- A checkout timeout can occur after an order was accepted: the UI directs the user to History before retrying. Production payment creation needs idempotency keys and provider reconciliation.
- SQLite is suitable for this single-process cafe demo. Add migrations/backups, retention/privacy policies, monitoring, durable background jobs, and a shared event broker before multi-worker deployment. Existing custom database schemas are not automatically migrated.
- The demo does not automatically create slides or claim real-world AR/push/payment certification. `plan.md` includes the implementation map, demo narrative, and rollout checklist.
