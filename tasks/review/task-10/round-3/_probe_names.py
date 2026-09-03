import ast, re, textwrap
p = r"E:\projects\erp_os\backend\scripts\seed_skus.py"
src = open(p, encoding="utf-8").read()
tree = ast.parse(src)
raw = None
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "RAW_SKUS":
        raw = ast.literal_eval(node.value)
print("skus:", len(raw))
names = [t[2] for t in raw]
width = int((300.0-50)/(9*0.6))
old = 38
print("new width chars:", width)
over_old = [n for n in names if len(n) > old]
over_new = [n for n in names if len(n) > width]
print("longer than old 38:", len(over_old))
print("longer than new 46:", len(over_new))
print("max len:", max(len(n) for n in names), repr(max(names, key=len)))
bad = []
for n in names:
    rows = textwrap.wrap(n, width) or [""]
    rows = rows[:3]
    if " ".join(rows) != n:
        bad.append((n, rows))
print("names changed by wrap:", len(bad))
for b in bad[:10]: print(b)
for n in over_new: print("WRAPS:", len(n), repr(n), textwrap.wrap(n, width))
# also non-latin check
nonlatin = [n for n in names if n.encode("cp1252","replace") != n.encode("cp1252","ignore")]
print("non-cp1252 names:", nonlatin[:5])
