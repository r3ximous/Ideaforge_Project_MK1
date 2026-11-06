"""Run from the repository root: python -m uvicorn backend.main:app --reload."""
import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import crud
from .database import Database
from .models import OrderCreate, RSVPCreate, StatusUpdate, UserCreate
from .seed_data import seed

ROOT = Path(__file__).resolve().parent.parent


class OrderStream:
    def __init__(self, db):
        self.db = db
        self.clients = {}
        self.lock = asyncio.Lock()

    async def publish(self):
        # Refresh all watchers: advancing one order changes other customers' queues.
        async with self.lock:
            for order_id, sockets in list(self.clients.items()):
                with self.db.connect() as connection:
                    snapshot = crud.order_view(connection, order_id)
                for socket in list(sockets):
                    try:
                        await asyncio.wait_for(socket.send_json(snapshot), timeout=2)
                    except (RuntimeError, OSError, asyncio.TimeoutError, WebSocketDisconnect):
                        sockets.discard(socket)


def create_app(db_path=None, staff_key=None, seed_demo=True):
    db = Database(db_path or os.environ.get('ALTITUDE_DB', str(ROOT / 'data' / 'altitude.db')))
    key = staff_key or os.environ.get('ALTITUDE_STAFF_KEY', 'altitude-demo-staff')
    stream = OrderStream(db)

    @asynccontextmanager
    async def lifespan(application):
        db.initialize()
        if seed_demo:
            seed(db)
        yield
        for sockets in list(stream.clients.values()):
            for socket in list(sockets):
                await socket.close(code=1001)

    application = FastAPI(title='Altitude Pulse', version='1.0.0', lifespan=lifespan,
                          description='Campus cafe demo. Payments are simulated; no card details are collected.')
    application.state.db = db

    def require_staff(value):
        if not crud.token_matches(value, key):
            raise HTTPException(403, 'A valid staff key is required')

    @application.get('/api/health')
    def health():
        with db.connect() as connection:
            connection.execute('SELECT 1').fetchone()
        return {'status': 'ok', 'payments': 'mock', 'realtime': 'single-process'}

    @application.get('/api/menu')
    def get_menu():
        return crud.menu(db)

    @application.post('/api/users', status_code=201)
    def register(request: UserCreate):
        return crud.create_user(db, request)

    @application.get('/api/users/{user_id}')
    def get_profile(user_id: int, x_customer_token: str | None = Header(default=None)):
        with db.connect() as connection:
            crud.require_customer(connection, user_id, x_customer_token)
            return crud.profile(connection, user_id)

    @application.get('/api/users/{user_id}/history')
    def get_history(user_id: int, x_customer_token: str | None = Header(default=None)):
        with db.connect() as connection:
            crud.require_customer(connection, user_id, x_customer_token)
            ids = connection.execute('SELECT order_id FROM orders WHERE user_id=? ORDER BY created_at DESC,order_id DESC', (user_id,))
            return {'orders': [crud.order_view(connection, row[0]) for row in ids.fetchall()]}

    @application.get('/api/events')
    def get_events():
        with db.connect() as connection:
            return {'events': [dict(row) for row in connection.execute('SELECT * FROM club_events ORDER BY event_date')]}

    @application.post('/api/events/{event_id}/rsvp')
    def rsvp(event_id: int, request: RSVPCreate, x_customer_token: str | None = Header(default=None)):
        with db.connect(write=True) as connection:
            crud.require_customer(connection, request.user_id, x_customer_token)
            event = connection.execute('SELECT * FROM club_events WHERE event_id=?', (event_id,)).fetchone()
            if not event:
                raise HTTPException(404, 'Event not found')
            if connection.execute("SELECT julianday(?) <= julianday('now')", (event['event_date'],)).fetchone()[0]:
                raise HTTPException(409, 'This event has ended')
            existing = connection.execute('SELECT * FROM event_rsvps WHERE user_id=? AND event_id=?', (request.user_id, event_id)).fetchone()
            if existing:
                if existing['redeemed_order_id'] is not None:
                    raise HTTPException(409, 'This event reward has already been redeemed')
                return {'token': existing['token'], 'discount_percent': existing['discount_percent']}
            token = secrets.token_urlsafe(24)
            connection.execute('INSERT INTO event_rsvps(user_id,event_id,token,discount_percent) VALUES(?,?,?,?)',
                               (request.user_id, event_id, token, event['discount_percent']))
            return {'token': token, 'discount_percent': event['discount_percent']}

    @application.post('/api/orders', status_code=201)
    async def post_order(request: OrderCreate, x_customer_token: str | None = Header(default=None)):
        order = crud.create_order(db, request, x_customer_token)
        await stream.publish()
        return order

    @application.get('/api/orders/queue/{order_id}')
    def get_order(order_id: int, token: str | None = Query(default=None), x_customer_token: str | None = Header(default=None)):
        with db.connect() as connection:
            order = crud.order_view(connection, order_id)
            supplied = token or x_customer_token
            if not crud.token_matches(supplied, order['access_token']):
                raise HTTPException(403, 'Order access token required')
            return order

    @application.get('/api/kds/active')
    def active_orders(x_staff_key: str | None = Header(default=None)):
        require_staff(x_staff_key)
        with db.connect() as connection:
            ids = connection.execute("SELECT order_id FROM orders WHERE status IN ('pending','preparing','ready') ORDER BY created_at,order_id").fetchall()
            return {'orders': [crud.order_view(connection, row[0]) for row in ids]}

    async def change_status(request, supplied_key, source):
        require_staff(supplied_key)
        order = crud.update_status(db, request.order_id, request.status, source)
        await stream.publish()
        return order

    @application.post('/api/kds/status')
    async def set_status(request: StatusUpdate, x_staff_key: str | None = Header(default=None)):
        return await change_status(request, x_staff_key, 'kds')

    @application.post('/api/mock/mobipos/webhook', tags=['Mock MOBIPOS'])
    async def mobipos(request: StatusUpdate, x_staff_key: str | None = Header(default=None)):
        return await change_status(request, x_staff_key, 'mock_mobipos')

    @application.websocket('/ws/orders/{order_id}')
    async def order_socket(socket: WebSocket, order_id: int, token: str | None = Query(default=None)):
        try:
            with db.connect() as connection:
                order = crud.order_view(connection, order_id)
            if not crud.token_matches(token, order['access_token']):
                await socket.close(code=1008)
                return
        except HTTPException:
            await socket.close(code=1008)
            return
        await socket.accept()
        clients = None
        try:
            # Serialize the initial snapshot with broadcasts so a slow handshake
            # cannot send a stale state after a newer status update.
            async with stream.lock:
                clients = stream.clients.setdefault(order_id, set())
                clients.add(socket)
                with db.connect() as connection:
                    order = crud.order_view(connection, order_id)
                await asyncio.wait_for(socket.send_json(order), timeout=2)
            while True:
                await socket.receive_text()
        except (WebSocketDisconnect, RuntimeError, OSError, asyncio.TimeoutError):
            pass
        finally:
            if clients is not None:
                clients.discard(socket)
                if not clients:
                    stream.clients.pop(order_id, None)

    @application.middleware('http')
    async def response_policy(request, call_next):
        response = await call_next(request)
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.url.path == '/sw.js':
            response.headers['Cache-Control'] = 'no-cache'
        return response

    @application.get('/', include_in_schema=False)
    def home():
        return FileResponse(ROOT / 'frontend' / 'index.html')

    application.mount('/', StaticFiles(directory=ROOT / 'frontend', html=True), name='frontend')
    return application


app = create_app()
