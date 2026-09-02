"""Read-only edge probes.

1. Is anything other than the VPS nginx in front of these hosts? The whole
   `may_have_landed` classification now rests on "only 502/503/504 come from a
   proxy", and a CDN answering 52x would break it.
2. Does an application 500 really come back as text/plain, and is it really a 500
   (not a 502)?
3. What does POST /api/contacts do with a body that overflows a column?
"""
import httpx

for u in [
    "https://crm.kelvinpeng.com/api/health",
    "https://crm.kelvinpeng.com/",
    "https://erp.kelvinpeng.com/",
]:
    try:
        r = httpx.get(u, timeout=30)
        print(u, r.status_code)
        for k in ("server", "via", "cf-ray", "x-served-by", "cf-cache-status"):
            if k in r.headers:
                print("   ", k, "=", r.headers[k])
    except Exception as e:
        print(u, "ERR", type(e).__name__, e)

print()
print("=== unauthenticated POST /api/contacts (shape of a refusal) ===")
r = httpx.post("https://crm.kelvinpeng.com/api/contacts", json={}, timeout=30)
print(r.status_code, r.headers.get("content-type"), r.text[:200])

print()
print("=== a route that does not exist ===")
r = httpx.get("https://crm.kelvinpeng.com/api/nope", timeout=30)
print(r.status_code, r.headers.get("content-type"), r.text[:200])
