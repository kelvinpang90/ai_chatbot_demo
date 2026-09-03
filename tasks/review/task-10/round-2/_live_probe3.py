import os, collections, httpx
BASE="https://erp.kelvinpeng.com"
t=httpx.post(f"{BASE}/api/auth/login",json={"email":os.environ["ERP_EMAIL"],"password":os.environ["ERP_PASSWORD"]},timeout=30).json()["access_token"]
h={"Authorization":f"Bearer {t}"}
inv=[];p=1
while True:
    r=httpx.get(f"{BASE}/api/invoices",params={"page":p,"page_size":100},headers=h,timeout=30).json()
    rows=r.get("items",[]); inv+=rows
    if len(rows)<100: break
    p+=1
print("invoice statuses:", collections.Counter(i["status"] for i in inv))
print("with sales_order_id:", sum(1 for i in inv if i.get("sales_order_id")))
so=[];p=1
while True:
    r=httpx.get(f"{BASE}/api/sales-orders",params={"page":p,"page_size":100},headers=h,timeout=30).json()
    rows=r.get("items",[]); so+=rows
    if len(rows)<100: break
    p+=1
print("SO statuses:", collections.Counter(s["status"] for s in so))
print("SO doc_no sample:", [s["document_no"] for s in so[:3]], "count", len(so))
