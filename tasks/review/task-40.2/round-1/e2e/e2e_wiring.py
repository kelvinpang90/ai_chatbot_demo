"""Reviewer's end-to-end run of task 40.2 (not part of the repo under review).

Real FastAPI app with its lifespan (so the real consumer thread), real Redis,
real signed webhook HTTP requests, real console endpoints. Meta's Graph API and
the CRM are two local stub HTTP servers: the Meta stub answers every send with a
message id, the CRM stub verifies the HMAC exactly as the contract words it and
records what arrived.

Run inside a container on a network with `redis` (see run_e2e.sh).
"""
import hashlib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

SECRET = "e2e-secret-0123456789"
APP_SECRET = "e2e-app-secret"
TOKEN = "e2e-console-token"
os.environ.update(
    CRM_EVENTS_ENABLED="true",
    CRM_EVENTS_URL="http://127.0.0.1:9001/internal/chatbot/events",
    CRM_EVENTS_SECRET=SECRET,
    REDIS_URL="redis://redis:6379/16",
    WHATSAPP_APP_SECRET=APP_SECRET,
    WHATSAPP_PHONE_NUMBER_ID="123",
    WHATSAPP_ACCESS_TOKEN="e2e-token",
    CONSOLE_TOKEN=TOKEN,
)

received: list[dict] = []
rejected: list[str] = []
sent_ids = iter(range(1, 10_000))
meta_sends: list[dict] = []


class Crm(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        ts = self.headers.get("X-Acuven-Timestamp", "")
        sig = self.headers.get("X-Acuven-Signature", "")
        want = "sha256=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(want, sig) or abs(time.time() - int(ts)) > 300:
            rejected.append(body.decode())
            self.send_response(401)
            self.end_headers()
            return
        received.append(json.loads(body))
        out = b'{"result":"stored"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class Meta(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        meta_sends.append(body)
        if "status" in body:  # typing indicator / mark as read
            out = b'{"success":true}'
        else:
            out = json.dumps({"messaging_product": "whatsapp", "messages": [{"id": f"wamid.out.{next(sent_ids)}"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


for port, handler in ((9001, Crm), (9002, Meta)):
    threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever, daemon=True).start()

import redis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import crm_events, llm, whatsapp  # noqa: E402

r = redis.Redis.from_url("redis://redis:6379/16", decode_responses=True)
r.flushdb()

PHONE = "60123459999"


def webhook(value):
    body = json.dumps({"entry": [{"changes": [{"value": value}]}]}).encode()
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = c.post("/webhook/whatsapp", content=body,
                  headers={"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"})
    assert resp.status_code == 200, resp.status_code


def msg(seq, kind, block):
    return {"messages": [{"id": f"wamid.in.{seq}", "from": PHONE, "timestamp": str(int(time.time())),
                          "type": kind, kind: block}],
            "contacts": [{"wa_id": PHONE, "profile": {"name": "E2E Visitor"}}]}


with patch.object(whatsapp, "GRAPH_API_BASE", "http://127.0.0.1:9002"), \
        patch.object(llm, "get_reply", return_value="We have **three** earbuds."), \
        TestClient(app) as c:
    H = {"X-Console-Token": TOKEN}
    webhook(msg(1, "text", {"body": "hi"}))
    webhook(msg(2, "interactive", {"type": "list_reply", "list_reply": {"id": "retail", "title": "Retail"}}))
    webhook(msg(3, "text", {"body": "do you have earbuds"}))
    webhook(msg(3, "text", {"body": "do you have earbuds"}))  # Meta retry
    webhook(msg(4, "text", {"body": "can I speak to a human please"}))
    print("console reply:", c.post("/console/reply", json={"key_id": PHONE, "text": "Boss, I check."}, headers=H).status_code)
    print("console give back:", c.post("/console/handover", json={"key_id": PHONE, "active": False}, headers=H).status_code)
    webhook({"statuses": [
        {"id": "wamid.out.3", "status": "delivered", "timestamp": str(int(time.time())), "recipient_id": PHONE},
        {"id": "wamid.out.3", "status": "failed", "timestamp": str(int(time.time())), "recipient_id": PHONE,
         "errors": [{"code": 131047, "title": "Re-engagement message"}]},
    ]})

    deadline = time.time() + 30
    while time.time() < deadline and (r.llen(crm_events.QUEUE_KEY) or not received):
        time.sleep(0.5)
    time.sleep(1.5)

print("queue left:", r.llen(crm_events.QUEUE_KEY), "dead:", r.llen(crm_events.DEAD_KEY), "rejected:", len(rejected))
for e in received:
    extra = {k: v for k, v in e.items() if k not in ("event_id", "type", "occurred_at", "visitor")}
    print(f"{e['type']:17} {e['occurred_at']} visitor={e['visitor']} {json.dumps(extra, ensure_ascii=False)}")
print("meta text sends:", [s.get("text", {}).get("body") or s.get("interactive", {}).get("type") for s in meta_sends if "status" not in s])
