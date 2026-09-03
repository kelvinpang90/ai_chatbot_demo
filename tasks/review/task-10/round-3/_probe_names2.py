import ast
p = r"E:\projects\erp_os\backend\scripts\seed_skus.py"
tree = ast.parse(open(p, encoding="utf-8").read())
for node in ast.walk(tree):
    if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "RAW_SKUS":
        raw = ast.literal_eval(node.value)
names = [t[2] for t in raw]
over = sorted([n for n in names if len(n) > 38], key=len, reverse=True)
for n in over: print(len(n), n)
