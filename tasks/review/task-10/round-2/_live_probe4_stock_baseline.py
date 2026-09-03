import os, httpx, json
BASE="https://erp.kelvinpeng.com"
t=httpx.post(f"{BASE}/api/auth/login",json={"email":os.environ["ERP_EMAIL"],"password":os.environ["ERP_PASSWORD"]},timeout=30).json()["access_token"]
h={"Authorization":f"Bearer {t}"}
r=httpx.get(f"{BASE}/api/inventory/branch-matrix",params={"sku_query":"earbuds","page_size":5},headers=h,timeout=30).json()
for row in r.get("rows",[]):
    print(row.get("sku_code"), row.get("sku_name"))
    for c in row.get("warehouses",[]):
        print("   ", c.get("warehouse_name"), "on_hand=",c.get("on_hand"), "reserved=",c.get("reserved"), "available=",c.get("available"))
