"""The SaaS support desk's back office (task 38.4).

The support bot could always open and look up a ticket, but the tickets lived
only inside each customer's own Redis record -- the same gap task 38.3 closed for
the hotel. This is the table a support engineer's list reads from.

`models` owns the table and every statement that touches it; `routes` puts the
list behind the console's token. The known-issues list stays in
`bots/data/saas.json`, and the ticket itself is still opened by `tools/local.py`.
"""
