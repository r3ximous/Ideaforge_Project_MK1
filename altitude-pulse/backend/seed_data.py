"""Idempotent demo catalog, campus feed, and recent sales for live popularity."""
import secrets
from datetime import datetime, timedelta, timezone

MENU = [
    ('Iced Latte', 'Coffee', 18, 'Double espresso, chilled milk, and a little campus calm.', 0, 1),
    ('Cold Brew', 'Coffee', 20, 'Slow-steeped for 18 hours. Smooth, bold, never bitter.', 0, 1),
    ('Butter Croissant', 'Pastry', 12, 'Golden layers, baked fresh. Your coffee’s favorite plus-one.', 0, 1),
    ('Caramel Cloud Latte', 'Special', 24, 'Velvety espresso, caramel ribbons, cloud-soft cold foam.', 1, 0),
    ('Matcha on Ice', 'Tea', 22, 'Ceremonial-style matcha whisked smooth over milk and ice.', 0, 0),
    ('Peach Iced Tea', 'Cold Drinks', 16, 'Bright peach and black tea, made for Dubai afternoons.', 0, 0),
    ('Flat White', 'Coffee', 18, 'Rich ristretto beneath a silky layer of steamed milk.', 0, 0),
    ('Chocolate Cookie', 'Pastry', 10, 'Soft center, crisp edges, generous dark chocolate.', 0, 0),
]


def seed(db):
    with db.connect(write=True) as connection:
        if connection.execute('SELECT COUNT(*) FROM menu_items').fetchone()[0]:
            return
        for name, category, price, description, promo, popular in MENU:
            connection.execute(
                'INSERT INTO menu_items(name,category,price,description,is_promo,is_popular,model_3d_url) VALUES(?,?,?,?,?,?,?)',
                (name, category, price, description, promo, popular,
                 None if category == 'Pastry' else '/assets/models/cup_16oz.glb'),
            )
        today = datetime.now(timezone.utc)
        for club, title, description, days, discount in [
            ('AIRC', 'Build something that matters', 'Meet the makers. An evening of AI demos, ideas, and very good coffee.', 2, 15),
            ('IEEE', 'Circuits & cold brew', 'A hands-on hardware meetup. Bring your curiosity; we’ll bring the caffeine.', 4, 10),
            ('Student Council', 'Campus sunset sessions', 'Good music, new faces, and a well-earned break from the library.', 6, 10),
        ]:
            connection.execute(
                'INSERT INTO club_events(club_name,title,description,promo_code,discount_percent,event_date) VALUES(?,?,?,?,?,?)',
                (club, title, description, club.replace(' ', '').upper(), discount,
                 (today + timedelta(days=days)).strftime('%Y-%m-%dT17:00:00Z')),
            )
        user_id = connection.execute(
            "INSERT INTO users(phone_number,name,access_token,loyalty_points,tier) VALUES('+971500000000','Demo alumni',?,650,'Gold')",
            (secrets.token_urlsafe(32),),
        ).lastrowid
        # Completed sample sales don't clutter the live KDS. No public demo identity token.
        for index, item_id in enumerate([1, 1, 1, 2, 2, 3]):
            item = connection.execute('SELECT * FROM menu_items WHERE item_id=?', (item_id,)).fetchone()
            timestamp = (today - timedelta(hours=index + 1)).isoformat().replace('+00:00', 'Z')
            order_id = connection.execute(
                """INSERT INTO orders(user_id,customer_name,access_token,order_type,subtotal_amount,total_amount,
                points_earned,payment_method,status,created_at,completed_at) VALUES(?,?,?,'takeaway',?,?,0,'card','completed',?,?)""",
                (user_id, 'Demo alumni', secrets.token_urlsafe(32), item['price'], item['price'], timestamp, timestamp),
            ).lastrowid
            connection.execute(
                'INSERT INTO order_items(order_id,item_id,item_name,item_size,price,item_code) VALUES(?,?,?,?,?,?)',
                (order_id, item_id, item['name'], 'Standard' if item['category'] == 'Pastry' else '16oz', item['price'], f'{order_id}-A'),
            )
            connection.execute(
                "INSERT INTO order_logs(order_id,new_status,source) VALUES(?,'completed','seed')", (order_id,)
            )
