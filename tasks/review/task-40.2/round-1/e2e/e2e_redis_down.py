"""Reviewer probe: how long one customer turn takes when Redis is unreachable,
switch off vs on. Real redis-py against a blackholed address; Meta stubbed
locally; LLM stubbed. Not part of the repo under review."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

os.environ.update(
    REDIS_URL="redis://10.255.255.1:6379/16",  # not routable: connect times out
    CRM_EVENTS_SECRET="s",
    WHATSAPP_PHONE_NUMBER_ID="123",
    WHATSAPP_ACCESS_TOKEN="t",
)


class Meta(BaseHTTPRequestHandler):
    n = 0

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        Meta.n += 1
        out = json.dumps({"messages": [{"id": f"wamid.out.{Meta.n}"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", 9002), Meta).serve_forever, daemon=True).start()

from app.config import settings  # noqa: E402
from app.routers.whatsapp_webhook import _handle_incoming_message  # noqa: E402
from app.services import crm_events, llm, whatsapp  # noqa: E402


def turn(seq, phone, kind, block):
    msg = {"id": f"wamid.in.{phone}.{seq}", "from": phone, "timestamp": str(int(time.time())), "type": kind, kind: block}
    t = time.monotonic()
    _handle_incoming_message(msg, {"wa_id": phone, "profile": {"name": "X"}})
    return time.monotonic() - t


with patch.object(whatsapp, "GRAPH_API_BASE", "http://127.0.0.1:9002"), \
        patch.object(llm, "get_reply", return_value="ok"):
    # warm up user_store's own offline switch so only crm_events is measured
    turn(0, "60120000000", "text", {"body": "hi"})
    for on in (False, True):
        crm_events.reset()
        with patch.object(settings, "crm_events_enabled", on):
            phone = "6012000000" + ("1" if on else "2")
            sends_before = Meta.n
            a = turn(1, phone, "text", {"body": "hi"})
            b = turn(2, phone, "interactive", {"type": "list_reply", "list_reply": {"id": "retail", "title": "Retail"}})
            c = turn(3, phone, "text", {"body": "do you have earbuds"})
            print(f"switch {'on ' if on else 'off'}: menu turn {a:.2f}s, pick-demo turn {b:.2f}s, "
                  f"reply turn {c:.2f}s, total {a + b + c:.2f}s, meta sends {Meta.n - sends_before}")
