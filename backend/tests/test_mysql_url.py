"""Reading a `mysql://` URL.

Moved out of test_audit.py when the verticals store (task 22) became the second
caller. The percent-decoding case is the one that matters and the reason this is
shared rather than copied: it stands guard over a real incident, and two copies
of the parser would have meant two chances to lose it.
"""
import pytest

from app.services.mysql_url import dsn

FEATURE = "the audit log"


def test_dsn_reads_host_port_and_database():
    parsed = dsn("mysql://user:secret@infra_mysql:3307/ai_chatbot", feature=FEATURE)
    assert parsed["host"] == "infra_mysql"
    assert parsed["port"] == 3307
    assert parsed["user"] == "user"
    assert parsed["password"] == "secret"
    assert parsed["database"] == "ai_chatbot"


def test_dsn_defaults_the_port():
    assert dsn("mysql://u:p@host/db", feature=FEATURE)["port"] == 3306


def test_dsn_decodes_a_percent_encoded_password():
    """provision-project.sh generates hex, but a hand-set password need not be.

    A password with an `@` or a `/` in it has to be encoded to survive the URL,
    and handing MySQL the still-encoded form fails as a wrong password -- which
    reads like a credentials problem rather than a parsing one.
    """
    assert dsn("mysql://u:p%40ss%2Fword@host/db", feature=FEATURE)["password"] == "p@ss/word"


def test_dsn_accepts_the_driver_qualified_scheme():
    assert dsn("mysql+pymysql://u:p@host/db", feature=FEATURE)["host"] == "host"


@pytest.mark.parametrize(
    "url",
    ["postgres://u:p@host/db", "not a url", "mysql://u:p@host", "mysql://u:p@host/", ""],
)
def test_dsn_refuses_anything_it_cannot_use(url):
    assert dsn(url, feature=FEATURE) is None


def test_the_warning_names_which_store_went_dark(caplog):
    """Two callers now, one log file. "not a mysql:// url" on its own does not
    say which of the two URLs is the broken one."""
    with caplog.at_level("WARNING"):
        dsn("postgres://u:p@host/db", feature="the verticals store")
    assert "the verticals store is off" in caplog.text


def test_the_connection_is_set_up_the_way_mysql_needs():
    """utf8mb4 or a customer's name in Chinese comes back as question marks;
    autocommit because nothing here runs in a transaction it opened itself."""
    parsed = dsn("mysql://u:p@host/db", feature=FEATURE)
    assert parsed["charset"] == "utf8mb4"
    assert parsed["autocommit"] is True
    assert parsed["connect_timeout"] > 0
