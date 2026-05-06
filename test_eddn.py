"""Diagnostic script — tests EDDN connectivity independently of the GUI.
Run with: python test_eddn.py
"""

import json
import sys
import time
import zlib

import zmq

EDDN_RELAY = "tcp://eddn.edcd.io:9500"
TIMEOUT_MS = 10_000  # 10 seconds before declaring timeout

print(f"[1] Importing zmq... OK (version {zmq.zmq_version()})")
print(f"[2] Connecting to {EDDN_RELAY} ...")

ctx = zmq.Context()
sock = ctx.socket(zmq.SUB)
sock.setsockopt(zmq.RCVTIMEO, TIMEOUT_MS)
sock.setsockopt_string(zmq.SUBSCRIBE, "")
sock.connect(EDDN_RELAY)
print("[3] connect() called (ZMQ connect is async — waiting for first message...)")

received = 0
start = time.time()

while received < 5:
    try:
        raw = sock.recv()
        elapsed = time.time() - start
        try:
            msg = json.loads(zlib.decompress(raw))
            schema = msg.get("$schemaRef", "???").split("/")[-2:]
            print(f"[OK] msg #{received+1} after {elapsed:.1f}s — schema: {'/'.join(schema)} — raw size: {len(raw)} bytes")
        except Exception as e:
            print(f"[OK] msg #{received+1} after {elapsed:.1f}s — decode error: {e} — raw: {raw[:80]}")
        received += 1
    except zmq.Again:
        elapsed = time.time() - start
        print(f"[TIMEOUT] No data received after {elapsed:.0f}s — possible firewall/network block on port 9500")
        print("          Try: https://eddn.edcd.io/ to check if EDDN is up")
        break

sock.close()
ctx.term()

if received > 0:
    print(f"\n[SUCCESS] Received {received} messages — EDDN connection works!")
else:
    print("\n[FAIL] No messages received.")
    print("  Possible causes:")
    print("  1. Windows Firewall blocking outbound TCP port 9500")
    print("  2. ISP/VPN blocking the connection")
    print("  3. EDDN relay temporarily down")
    print("  Try disabling firewall temporarily or check with Wireshark.")
