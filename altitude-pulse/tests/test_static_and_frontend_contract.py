"""Server/static integration, not a browser execution or offline-runtime test.

The API contract below is taken from frontend/js/{app,shared,tracker,kds,history}.js.
Known mismatches remain ordinary failing assertions, not xfails or skips.
"""
import json
import re
import struct
from html.parser import HTMLParser
from pathlib import Path

import pytest


FRONTEND = Path(__file__).resolve().parents[1] / 'frontend'


class Elements(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def by_id(self, element_id):
        return next(attrs for _, attrs in self.elements if attrs.get('id') == element_id)


def test_home_is_the_actual_frontend_index(client):
    response = client.get('/')
    assert response.status_code == 200
    assert response.text == (FRONTEND / 'index.html').read_text()
    assert response.headers['content-type'].startswith('text/html')


@pytest.mark.parametrize('path,module', [
    ('/index.html', '/js/app.js'), ('/track.html', '/js/tracker.js'),
    ('/history.html', '/js/history.js'), ('/kds.html', '/js/kds.js'),
])
def test_html_pages_serve_modules_styles_manifest_and_local_assets(client, path, module):
    response = client.get(path)
    assert response.status_code == 200
    elements = Elements(response.text).elements
    assert any(tag == 'script' and attrs.get('src') == module and attrs.get('type') == 'module'
               for tag, attrs in elements)
    assert any(tag == 'link' and attrs.get('rel') == 'manifest' and attrs.get('href') == '/manifest.webmanifest'
               for tag, attrs in elements)
    assert any(tag == 'link' and attrs.get('rel') == 'stylesheet' and attrs.get('href') == '/assets/style.css'
               for tag, attrs in elements)
    for tag, attrs in elements:
        resource = attrs.get('src') if tag in ('script', 'img') else attrs.get('href') if tag == 'link' else None
        if resource and resource.startswith('/'):
            assert client.get(resource).status_code == 200, resource


@pytest.mark.parametrize('path,content_type', [
    ('/assets/style.css', 'text/css'), ('/assets/icon.svg', 'image/svg+xml'),
    ('/assets/icon-192.png', 'image/png'), ('/assets/icon-512.png', 'image/png'),
    ('/js/shared.js', 'javascript'), ('/js/app.js', 'javascript'),
    ('/js/tracker.js', 'javascript'), ('/js/history.js', 'javascript'), ('/js/kds.js', 'javascript'),
    ('/sw.js', 'javascript'),
])
def test_static_resource_content_types(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert content_type in response.headers['content-type']
    assert response.content


def test_manifest_scope_icons_dimensions_and_shortcuts(client):
    response = client.get('/manifest.webmanifest')
    assert response.status_code == 200
    manifest = response.json()
    assert manifest['id'] == manifest['start_url'] == manifest['scope'] == '/'
    assert manifest['display'] == 'standalone'
    assert manifest['name'].startswith('Altitude Pulse')
    for icon in manifest['icons']:
        image = client.get(icon['src'])
        assert image.status_code == 200
        assert image.headers['content-type'].split(';')[0] == icon['type']
        if icon['type'] == 'image/png':
            assert image.content[:8] == b'\x89PNG\r\n\x1a\n'
            width, height = struct.unpack('>II', image.content[16:24])
            assert f'{width}x{height}' == icon['sizes']
    assert {shortcut['url'] for shortcut in manifest['shortcuts']} == {'/track.html', '/history.html'}
    for shortcut in manifest['shortcuts']:
        assert client.get(shortcut['url']).status_code == 200


def test_every_service_worker_precache_url_is_available(client):
    worker = client.get('/sw.js')
    assert worker.status_code == 200
    match = re.search(r'const SHELL\s*=\s*(\[[\s\S]*?\]);', worker.text)
    assert match, 'Could not locate the explicit shell allowlist'
    shell = json.loads(re.sub(r',\s*\]', ']', match.group(1)))
    assert {'/', '/index.html', '/track.html', '/history.html', '/kds.html',
            '/manifest.webmanifest', '/js/shared.js'} <= set(shell)
    assert len(shell) == len(set(shell))
    for path in shell:
        assert not path.startswith(('/api/', '/ws/'))
        assert '?' not in path
        assert not path.endswith('.glb')
        assert client.get(path).status_code == 200, f'cache.addAll would fail for {path}'
    # Source assertions only: browser caching behavior requires browser tests.
    assert 'event.request.method !== "GET"' in worker.text
    assert 'url.origin !== self.location.origin' in worker.text
    assert '!SHELL.includes(url.pathname)' in worker.text
    assert 'credentials: "omit"' in worker.text
    assert 'cache.put(url.pathname' in worker.text


@pytest.mark.parametrize('path', ['/api/health', '/api/menu', '/api/events', '/api/users/999999', '/api/kds/active'])
def test_api_responses_including_errors_are_not_cacheable(client, path):
    response = client.get(path)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_private_success_and_validation_responses_are_not_cacheable(cafe, user):
    order = cafe.order(user)
    responses = [
        cafe.client.get(f'/api/users/{user["user_id"]}', headers=cafe.headers(user)),
        cafe.client.get(f'/api/users/{user["user_id"]}/history', headers=cafe.headers(user)),
        cafe.client.get(f'/api/orders/queue/{order["order_id"]}', params={'token': order['access_token']}),
        cafe.post(user, items=[]),
    ]
    assert [response.status_code for response in responses] == [200, 200, 200, 422]
    assert all(response.headers['cache-control'] == 'no-store' for response in responses)


def test_service_worker_revalidates_and_static_has_security_headers(client):
    assert client.get('/sw.js').headers['cache-control'] == 'no-cache'
    for path in ('/', '/track.html', '/js/shared.js', '/manifest.webmanifest'):
        response = client.get(path)
        assert response.headers['referrer-policy'] == 'no-referrer'
        assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize('path', ['/missing.html', '/assets/missing.js', '/api/not-a-route'])
def test_missing_resources_are_404_not_spa_html(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert '<!doctype html>' not in response.text.lower()


@pytest.mark.parametrize('size', ['12oz', '16oz'])
def test_frontend_advertised_cup_models_are_real_glb_assets(client, size):
    # app.js replaces cup_16oz.glb with cup_12oz.glb when preview size changes.
    menu = client.get('/api/menu').json()
    url = next(item['model_3d_url'] for item in menu['items'] if item['model_3d_url'])
    response = client.get(url.replace('16oz', size))
    assert response.status_code == 200, f'Frontend advertises missing {size} model: {response.text}'
    assert response.content[:4] == b'glTF'
    magic, version, length = struct.unpack('<4sII', response.content[:12])
    assert magic == b'glTF'
    assert version == 2
    assert length == len(response.content)


@pytest.mark.parametrize('source,element,model,field', [
    ('shared.js', 'customer-name', 'UserCreate', 'name'),
    ('shared.js', 'customer-phone', 'UserCreate', 'phone_number'),
    ('index.html', 'item-customization', 'OrderLine', 'customization'),
    ('index.html', 'table-number', 'OrderCreate', 'table_number'),
])
def test_frontend_input_maximums_do_not_exceed_api_limits(client, source, element, model, field):
    # Profile fields are generated in shared.js, not present in index.html.
    url = '/js/' + source if source.endswith('.js') else '/' + source
    attrs = Elements(client.get(url).text).by_id(element)
    frontend_limit = int(attrs['maxlength'])
    field_schema = client.get('/openapi.json').json()['components']['schemas'][model]['properties'][field]
    variants = field_schema.get('anyOf', [field_schema])
    api_limit = next(variant['maxLength'] for variant in variants if 'maxLength' in variant)
    assert frontend_limit <= api_limit, (
        f'{source} #{element} accepts {frontend_limit} characters but {model}.{field} rejects over {api_limit}'
    )


def test_checkout_form_enums_match_api_schema(client):
    elements = Elements(client.get('/').text).elements
    schema = client.get('/openapi.json').json()['components']['schemas']['OrderCreate']['properties']
    for field in ('order_type', 'payment_method'):
        values = {attrs['value'] for tag, attrs in elements
                  if tag == 'input' and attrs.get('name') == field}
        assert values == set(schema[field]['enum'])
