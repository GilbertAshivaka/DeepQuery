"""Isolation test — the must-fail path.

Confirms --network=none genuinely isolates the sandbox. A poisoned
model-generated script trying to exfiltrate data must hit a wall here.
Expected output: "OK: network blocked".
"""

import urllib.request

try:
    urllib.request.urlopen("http://example.com", timeout=5)
    print("FAIL: network reachable — sandbox is NOT isolated")
except Exception as e:  # noqa: BLE001 — any failure proves isolation
    print("OK: network blocked —", type(e).__name__)
