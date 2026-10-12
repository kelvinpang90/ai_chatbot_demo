"""Reviewer's end-to-end probe (task 40.1, round 1): real Redis, real HTTP, real thread.

Not a repro. Runs inside python:3.13-slim on a docker network with redis:7-alpine.
A receiver verifies the signature exactly as docs/chatbot-events.md (acuven_crm_demo)
words it, independently of the module's signer. Then: three events in order, receiver
down -> backoff, receiver back -> drained in order.
"""
import hashlib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = "e2e-secret"
os.environ.update(
    CRM_EVENTS_ENABLED="true",
    CRM_EVENTS_SECRET=SECRET,
    REDIS_URL="redis://e2e-redis:6379/1",
    CRM_EVENTS_URL="http://127.0.0.1:18080/internal/chatbot/events",
)

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

from app.services import crm_events  # noqa: E402

received = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        ts = self.headers["X-Acuven-Timestamp"]
        sig = self.headers["X-Acuven-Signature"]
        want = "sha256=" + hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(want, sig) and abs(time.time() - int(ts)) <= 300
        event = json.loads(body)
        received.append((ok, event["message"]["body"]))
        print("RECEIVER", "sig-ok" if ok else "SIG-BAD", event["message"]["body"], flush=True)
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"result":"stored"}')

    def log_message(self, *a):
        pass


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 18080), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


r = crm_events._redis()
r.delete(crm_events.QUEUE_KEY, crm_events.DEAD_KEY)

server = serve()
assert crm_events.start() is not None
who = crm_events.visitor("60123456789", None, "Aisha 陈")
for body in ("A 你好", "B café", "C ✓"):
    crm_events.enqueue("customer_message", who, message={"wa_message_id": body, "body": body})
time.sleep(3)
print("PHASE1", received, "LLEN", r.llen(crm_events.QUEUE_KEY), flush=True)

server.shutdown()
server.server_close()
received.clear()
for body in ("D", "E"):
    crm_events.enqueue("customer_message", who, message={"wa_message_id": body, "body": body})
time.sleep(8)
print("PHASE2 while down LLEN", r.llen(crm_events.QUEUE_KEY), flush=True)
server = serve()
time.sleep(12)
print("PHASE3", received, "LLEN", r.llen(crm_events.QUEUE_KEY), "DEAD", r.llen(crm_events.DEAD_KEY), flush=True)
