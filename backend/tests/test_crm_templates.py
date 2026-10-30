"""The CRM's template whitelist and `POST /internal/crm/templates` (task 46.1).

The contract is `docs/chatbot-phase3.md` sections 5.3 and 7 in acuven_crm_demo.
Signatures are computed here from the contract's text, never by the module
under test, the way `test_internal_crm.py` does it.
"""
import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import CrmTemplate, Settings, settings
from app.main import app
from app.routers import internal_crm
from app.services import crm_templates

client = TestClient(app)

URL = "/internal/crm/templates"
SECRET = "test-send-secret"
OLD_SECRET = "test-send-secret-before-rotation"
NOW = 1_760_000_000

FOLLOWUP = {
    "name": "crm_followup",
    "language": "en",
    "category": "UTILITY",
    "params": [{"label": "Visitor name", "max_len": 60}],
    "body": "Hi {{1}}, this is Acuven Technology following up on your recent enquiry.",
}
FOLLOWUP_CN = {
    "name": "crm_followup_cn",
    "language": "zh_CN",
    "category": "UTILITY",
    "params": [{"label": "访客称呼", "max_len": 60}],
    "body": "您好 {{1}}，这里是 Acuven Technology，想跟进一下您之前的咨询。",
}
TWO_SLOTS = {
    "name": "two_slots",
    "language": "en",
    "category": "UTILITY",
    "params": [{"label": "Name", "max_len": 10}, {"label": "Company", "max_len": 20}],
    "body": "Dear {{1}}, {{2}} here.",
}


def _sign(secret: str, timestamp, body: bytes) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()


def _post(body: bytes = b"{}", *, secret: str = SECRET, timestamp=NOW, headers: dict | None = None):
    if headers is None:
        headers = {
            "X-Acuven-Timestamp": str(timestamp),
            "X-Acuven-Signature": _sign(secret, timestamp, body),
        }
    return client.post(URL, content=body, headers={"Content-Type": "application/json", **headers})


def _whitelist(*entries: dict) -> list[CrmTemplate]:
    return [CrmTemplate.model_validate(entry) for entry in entries]


@pytest.fixture(autouse=True)
def configured():
    with patch.object(settings, "crm_send_secret", SECRET), \
            patch.object(settings, "crm_send_secret_previous", ""), \
            patch.object(settings, "crm_templates", []), \
            patch.object(internal_crm, "_now", lambda: NOW):
        yield


# --- the door -------------------------------------------------------------------


def test_without_a_secret_it_is_503():
    with patch.object(settings, "crm_send_secret", ""):
        assert _post().status_code == 503


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Acuven-Timestamp": str(NOW), "X-Acuven-Signature": "sha256=" + "0" * 64},
        # Signed over the body alone, without the timestamp in front.
        {
            "X-Acuven-Timestamp": str(NOW),
            "X-Acuven-Signature": "sha256=" + hmac.new(SECRET.encode(), b"{}", hashlib.sha256).hexdigest(),
        },
    ],
    ids=["unsigned", "wrong-signature", "body-only"],
)
def test_a_bad_signature_is_401(headers):
    assert _post(headers=headers).status_code == 401


def test_a_stale_timestamp_is_401():
    assert _post(timestamp=NOW - 301).status_code == 401


def test_the_previous_key_still_gets_in():
    with patch.object(settings, "crm_send_secret_previous", OLD_SECRET):
        assert _post(secret=OLD_SECRET).status_code == 200


def test_a_bad_signature_on_a_bad_body_is_401_not_422():
    """Nobody unsigned learns from a 422 what the body should look like."""
    assert _post(b"not json", secret="wrong").status_code == 401


def test_a_signed_body_that_is_not_an_object_is_422():
    assert _post(b"not json").status_code == 422


# --- the answer -----------------------------------------------------------------


def test_an_empty_whitelist_is_an_empty_list():
    response = _post()
    assert response.status_code == 200
    assert response.json() == {"templates": []}


def test_the_whitelist_comes_back_as_configured():
    with patch.object(settings, "crm_templates", _whitelist(FOLLOWUP, FOLLOWUP_CN)):
        response = _post()
    assert response.status_code == 200
    assert response.json() == {"templates": [FOLLOWUP, FOLLOWUP_CN]}


# --- reading CRM_TEMPLATES ------------------------------------------------------


def test_crm_templates_is_read_from_the_environment_as_json(monkeypatch):
    monkeypatch.setenv("CRM_TEMPLATES", json.dumps([FOLLOWUP, FOLLOWUP_CN], ensure_ascii=False))
    loaded = Settings(_env_file=None).crm_templates
    assert [template.model_dump() for template in loaded] == [FOLLOWUP, FOLLOWUP_CN]


def test_crm_templates_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("CRM_TEMPLATES", raising=False)
    assert Settings(_env_file=None).crm_templates == []


def _with(**changes) -> dict:
    return {**FOLLOWUP, **changes}


@pytest.mark.parametrize(
    "entry",
    [
        _with(body="Hi there, no slot at all."),
        _with(body="Hi {{1}} and {{2}}."),
        _with(params=[{"label": "a", "max_len": 5}, {"label": "b", "max_len": 5}], body="Hi {{1}} and {{3}}."),
        _with(params=[{"label": "Visitor name", "max_len": 0}]),
        _with(params=[{"label": "", "max_len": 60}]),
        _with(name=""),
        _with(category=""),
        {key: value for key, value in FOLLOWUP.items() if key != "body"},
    ],
    ids=["slot-missing", "slot-extra", "slot-skipped", "max-len-0", "blank-label", "blank-name",
         "blank-category", "no-body"],
)
def test_a_wrong_entry_stops_the_process(monkeypatch, entry):
    monkeypatch.setenv("CRM_TEMPLATES", json.dumps([entry]))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_the_same_template_twice_stops_the_process(monkeypatch):
    monkeypatch.setenv("CRM_TEMPLATES", json.dumps([FOLLOWUP, _with(category="MARKETING")]))
    with pytest.raises(ValidationError, match="twice"):
        Settings(_env_file=None)


def test_the_same_name_in_two_languages_is_two_templates(monkeypatch):
    monkeypatch.setenv("CRM_TEMPLATES", json.dumps([FOLLOWUP, _with(language="zh_CN")]))
    assert len(Settings(_env_file=None).crm_templates) == 2


# --- finding, checking, filling in ---------------------------------------------


@pytest.fixture
def listed():
    with patch.object(settings, "crm_templates", _whitelist(FOLLOWUP, FOLLOWUP_CN, TWO_SLOTS)):
        yield


def test_find_matches_name_and_language_exactly(listed):
    assert crm_templates.find("crm_followup_cn", "zh_CN").name == "crm_followup_cn"
    for name, language in [("crm_followup", "zh_CN"), ("crm_followup_cn", "zh_cn"), ("nope", "en")]:
        with pytest.raises(crm_templates.TemplateRefused):
            crm_templates.find(name, language)


def test_nothing_is_found_on_an_empty_whitelist():
    with pytest.raises(crm_templates.TemplateRefused):
        crm_templates.find("crm_followup", "en")


def test_params_are_trimmed(listed):
    template = crm_templates.find("two_slots", "en")
    assert crm_templates.checked_params(template, ["  Mei ", "Acuven "]) == ["Mei", "Acuven"]


@pytest.mark.parametrize("params", [[], ["Mei"], ["Mei", "Acuven", "extra"]])
def test_the_number_of_params_must_match(listed, params):
    with pytest.raises(crm_templates.TemplateRefused, match="takes 2 params"):
        crm_templates.checked_params(crm_templates.find("two_slots", "en"), params)


def test_the_length_limit_is_after_trimming_and_inclusive(listed):
    template = crm_templates.find("two_slots", "en")
    assert crm_templates.checked_params(template, ["x" * 10 + "   ", "y"]) == ["x" * 10, "y"]
    with pytest.raises(crm_templates.TemplateRefused, match="param 1 must be 1-10"):
        crm_templates.checked_params(template, ["x" * 11, "y"])
    with pytest.raises(crm_templates.TemplateRefused, match="param 2 must be 1-20"):
        crm_templates.checked_params(template, ["Mei", "   "])


@pytest.mark.parametrize("value", ["Mei\nLim", "Mei\rLim", "Mei\tLim"])
def test_no_line_break_or_tab(listed, value):
    with pytest.raises(crm_templates.TemplateRefused, match="line break or a tab"):
        crm_templates.checked_params(crm_templates.find("crm_followup", "en"), [value])


def test_three_spaces_pass_and_four_do_not(listed):
    template = crm_templates.find("crm_followup", "en")
    assert crm_templates.checked_params(template, ["Mei   Lim"]) == ["Mei   Lim"]
    with pytest.raises(crm_templates.TemplateRefused, match="four or more spaces"):
        crm_templates.checked_params(template, ["Mei    Lim"])


def test_a_refusal_never_repeats_the_value(listed):
    with pytest.raises(crm_templates.TemplateRefused) as refused:
        crm_templates.checked_params(crm_templates.find("crm_followup", "en"), ["Secret\nName"])
    assert "Secret" not in str(refused.value)


def test_render_fills_every_slot_in_place(listed):
    assert crm_templates.render(crm_templates.find("two_slots", "en"), ["Mei", "Acuven"]) == "Dear Mei, Acuven here."
    assert crm_templates.render(crm_templates.find("crm_followup_cn", "zh_CN"), ["李先生"]).startswith("您好 李先生，")


def test_render_does_not_fill_in_a_value_that_looks_like_a_slot(listed):
    rendered = crm_templates.render(crm_templates.find("two_slots", "en"), ["{{2}}", "Acuven"])
    assert rendered == "Dear {{2}}, Acuven here."


def test_an_empty_value_in_the_env_file_is_an_empty_whitelist(monkeypatch):
    """`.env.example` ships `CRM_TEMPLATES=` with nothing after it."""
    monkeypatch.setenv("CRM_TEMPLATES", "")
    assert Settings(_env_file=None).crm_templates == []


def test_json_that_does_not_parse_stops_the_process(monkeypatch):
    monkeypatch.setenv("CRM_TEMPLATES", '[{"name": "crm_followup",')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
