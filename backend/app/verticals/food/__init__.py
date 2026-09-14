"""Nasi Lemak Express's back office (task 25).

Scene 4b is an order landing and then moving -- received, in the kitchen, out
with a rider, delivered -- and scene 3 hangs off the moment it leaves the
kitchen. There is no restaurant system to borrow for that, so this is it: one
table of orders and a page that shows them moving.

`models` owns the table and every statement that touches it; `routes` puts the
list behind the console's token. The ordering itself is `tools/food.py`, which
calls in here directly -- the model places the order, not a form.
"""
