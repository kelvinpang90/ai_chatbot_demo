"""KL Homes Realty's back office (task 23).

The property demo is the one that has to show a booking landing somewhere. Retail
borrows a real ERP for that; there is no property system to borrow, so this is
it: eight listings seeded from the bot's own prompt data, a table of viewing
requests, and a page that shows them arriving.

`models` owns both tables and every statement that touches them; `routes` puts
three of them behind the console's token. Task 24 hangs the WhatsApp Flow off
`book_viewing` -- the form submission is an inbound message, so it arrives
through the webhook and calls in here directly rather than over HTTP.
"""
