"""The two demo businesses that have a back office of their own (batch 04).

Retail borrows a real ERP and a real CRM, and that is what makes the flagship
scene worth watching. Property and food have no such thing to borrow, so they
bring their own: a handful of tables on the shared infra_mysql, and an admin page
on the console's domain. Deliberately not a second project -- one deployment
unit, one image, one set of credentials to keep.

Each vertical owns a subpackage and contributes its own tables. `db` holds the
one connection they share; a vertical calls `db.store.register(*SCHEMA)` at
import time and the statements run the first time anybody touches the database.
"""
from app.verticals.db import StoreUnavailable, store

__all__ = ["StoreUnavailable", "store"]
