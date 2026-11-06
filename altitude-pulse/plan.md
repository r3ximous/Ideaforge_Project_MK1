# Altitude Pulse — architecture & implementation map

## Outcome and judging alignment

A single-origin, zero-build PWA for Altitude Cafe at RIT Dubai. The QR destination is the public menu; profile creation happens only when ordering or claiming a reward. FastAPI serves static pages and REST/WebSocket APIs, with SQLite as the durable source of truth.

| Criterion | Weight | Demo evidence |
| --- | --- | --- |
| Solution fit | 25% | Browse → mock checkout → private queue tracker → labeled handoff → digital receipt |
| Innovation | 20% | Fixed-scale AR cup comparison, live 24-hour popular picks, per-item badges, club reward tokens |
| Technical execution | 20% | Transactional SQLite, enforced transitions, authenticated realtime snapshots, mocked POS adapter, 234 passing tests |
| Design/UX | 20% | Responsive espresso/cream/lime customer surface; large KDS actions; explicit error/offline states |
| Pitch/feasibility | 15% | One Python process, automatic seeds, no frontend build, QR entry, three-action staff workflow |

## Runtime and ownership

- `backend/main.py`: app factory/lifespan, API routes, request access checks, realtime connection registry, public static mount.
- `backend/database.py`: schema, foreign keys, WAL, per-operation connections, immediate write transactions.
- `backend/models.py`: Pydantic request schemas; unknown price/status fields rejected.
- `backend/crud.py`: canonical pricing, order snapshots, badges, queue, state machine, rewards, loyalty, popularity.
- `backend/seed_data.py`: eight menu items, three future events, one private alumni profile, six completed sample sales.
- `backend/mock_mobipos.py`: CLI sending authenticated fake POS status callbacks; no proprietary integration.
- `frontend/index.html` + `js/app.js`: catalog, cart, popular items, spotlight, loyalty, event RSVP, checkout, AR modal.
- `frontend/track.html` + `js/tracker.js`: private itemized receipt, progress, queue, live socket, polling fallback.
- `frontend/history.html` + `js/history.js`: private historical receipts and current-price reorder.
- `frontend/kds.html` + `js/kds.js`: staff-gated active board; three-second polling and state actions.
- `frontend/js/shared.js`: same-origin API wrapper, local profile/order credentials, alerts, escaped receipt rendering.
- `frontend/assets/style.css`: local responsive design; Tailwind/Alpine are unnecessary dependencies here.
- `frontend/sw.js` + `manifest.webmanifest`: installable shell, local icons, allowlisted public cache only.
- `scripts/generate_cups.py`: original dependency-free glTF generator for 12oz and 16oz illustrative models, units in meters.
- `tests/`: isolated SQLite/TestClient integration tests and static frontend contract checks.

## Durable schema additions to the original plan

The original users/menu/orders/order_items/club_events entities are retained. Implementation adds:

- Random customer and order access tokens to avoid disclosure via predictable IDs.
- Price/discount/points/payment snapshots on orders so catalog changes cannot rewrite receipts.
- `event_rsvps`, binding opaque reward tokens to a customer/event and one redeemed order.
- `order_logs`, recording state changes and their KDS/mock-POS origin.
- `users.upgrade_month` and `orders.used_upgrade` to reserve and consume monthly Platinum upgrades.
- Indexed queue, user history, and order item queries.

SQLite writes use `BEGIN IMMEDIATE`; validation, price calculation, discount redemption, lines, and audit insertion commit together. Completion points, tier changes, and upgrade consumption share a transaction. Historical price snapshots are immutable through the public API.

## Order and realtime contract

1. Public `GET /api/menu` and `/api/events` load without an account.
2. `POST /api/users` creates a browser-bound profile and random bearer credential. It does not verify a phone or grant recovery by phone number.
3. `POST /api/events/{id}/rsvp` creates/retrieves a customer-bound one-use discount.
4. `POST /api/orders` authenticates the customer, checks sizes/table details, computes totals, creates one line per physical item, and returns an order-specific credential.
5. Tracker connects to `WS /ws/orders/{id}?token=...`, receiving an initial full snapshot. GET polling provides fallback. Every mutation refreshes all watchers to keep other customers' positions current.
6. Staff requests require `X-Staff-Key`. KDS transitions are `pending → preparing → ready → completed`; cancellation is allowed only from pending/preparing. Repeating the same state is safe; skipping states returns HTTP 409.
7. Completed orders award the checkout-time point estimate exactly once; cancellation awards nothing and releases rewards/upgrades.

`orders_ahead` counts earlier pending/preparing orders; the displayed position is that count plus one. Ready items no longer block preparation positions but remain on the KDS until handed off. This deliberately distinguishes a zero-based count from a one-based position and does not promise an ETA.

## Loyalty and offers

- Base: 0–499 points; Gold: 500–1,499; Platinum: 1,500+.
- Earn 10 points per final AED spent, rounded down; Gold gets a 10% points bonus based on its tier at checkout.
- Platinum receives one 16oz-at-12oz-price drink per UTC calendar month. An active order reserves this benefit, completion consumes it, cancellation releases it.
- More than seven days since the last non-cancelled order yields a 20% return offer; a brand-new customer is not inactive.
- Event reward and return offer do not stack: apply the higher percentage after any size-upgrade saving.
- Popularity counts individual non-cancelled items in the preceding 24 hours. This is explainable live ranking, not a machine-learned recommendation claim.

## Verification status

- Backend foundation, KDS/state engine, customer PWA, local AR assets, history, loyalty, and campus rewards: implemented.
- 234 server/contract tests pass, including concurrent redemption/completion and realtime queue broadcasts. Python compile checks pass.
- Manual browser/device verification remains: visual layout, actual phone/tablet checkout-to-handoff journey, sound, notification permissions, install/offline shell, and Android/iOS AR.
- Browser audio requires an explicit user gesture. Notifications are foreground-page features, not background Web Push.
- Quick Look uses model-viewer's on-demand USDZ generation; device support and HTTPS must be verified on the demonstration phone.

## Suggested pitch sequence

1. **Problem (20 seconds):** a PDF menu and crowded pickup counter cannot tell a student what is available or which cup is theirs.
2. **Customer demo (40 seconds):** open QR destination, choose a size in 3D, RSVP for a club reward, and place a labeled simulated order.
3. **Operations demo (30 seconds):** barista advances a card; the tracker turns ready and sounds its user-enabled chime. Show `#7 | SARAH | 1 of 2` and `7-A` together.
4. **Retention (20 seconds):** show the digital receipt, completed-order points, reorder, and explain rolling best-sellers.
5. **Feasibility (20 seconds):** one deployment, existing tablets/phones, staff onboarding in three actions. Be explicit that payment/POS are currently mock adapters.

No slide deck is generated; this narrative is a starting point for the team's presentation.

## Operational rollout gates

Before public production use: real authentication/recovery and staff roles, private staff secret, real provider checkout with webhook verification/idempotency and refunds, official POS integration, schema migrations/backups, rate limits, privacy/retention rules, TLS, structured logs without credential query strings, and production monitoring.

For scale: move broadcasts to a shared broker before enabling multiple workers; evaluate a server database and durable jobs for background push and re-engagement delivery. The current re-engagement offer is computed on visits/checkout; no unsolicited messages are sent.

See `README.md` for exact run/deployment commands, the two-minute demo, and a candid limitations checklist.
