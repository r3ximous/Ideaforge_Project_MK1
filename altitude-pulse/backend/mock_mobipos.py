"""A local simulator, NOT an implementation of MOBIPOS's proprietary protocol.

Usage: python -m backend.mock_mobipos 7 --staff-key altitude-demo-staff
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('order_id', type=int)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--staff-key', default=os.environ.get('ALTITUDE_STAFF_KEY', 'altitude-demo-staff'))
    parser.add_argument('--delay', type=float, default=2)
    parser.add_argument('--complete', action='store_true', help='Also mark picked up; otherwise stop at ready')
    args = parser.parse_args()
    states = ['preparing', 'ready'] + (['completed'] if args.complete else [])
    for index, status in enumerate(states):
        if index:
            time.sleep(max(0, args.delay))
        request = urllib.request.Request(
            args.url.rstrip('/') + '/api/mock/mobipos/webhook',
            data=json.dumps({'order_id': args.order_id, 'status': status}).encode(),
            headers={'Content-Type': 'application/json', 'X-Staff-Key': args.staff_key}, method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                order = json.load(response)
            print(f'Order #{order["order_id"]}: {order["status"]} (simulated POS event)')
        except urllib.error.HTTPError as error:
            parser.exit(1, f'Simulator rejected ({error.code}): {error.read().decode()}\n')
        except urllib.error.URLError as error:
            parser.exit(1, f'Cannot reach backend: {error.reason}\n')


if __name__ == '__main__':
    main()
