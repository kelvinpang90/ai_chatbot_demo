"""Langkawi Breeze Resort's back office (task 38.3).

The hotel bot could always book, look up and change a stay, but the bookings
lived only inside each guest's own Redis record: seven days, twenty rows, and no
page anywhere that listed them. Every other demo has its "refresh the back office
and there it is" moment; this is the hotel's.

`models` owns the table and every statement that touches it; `routes` puts the
list behind the console's token. The room catalogue stays in `bots/data/hotel.json`,
which is also what the model reads rates from, and the booking itself is still
made by `tools/local.py`.
"""
