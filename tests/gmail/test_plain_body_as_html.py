"""A plain-text outgoing body is sent as HTML paragraphs, so Gmail never
opens it in Plain text mode and hard-wraps it."""

import base64
from email import policy
from email.parser import BytesParser

import pytest

from gmail.gmail_helpers import plain_text_to_html, resolve_outgoing_body
from gmail.gmail_tools import draft_gmail_message
from tests.gmail.test_draft_gmail_message import _mock_gmail_service, _unwrap


def test_paragraphs_become_p_and_single_newlines_become_br():
    text = "Hi Akhil,\r\n\r\nFirst line\nsecond line.\n\n\n  \nLast & <done>.\n"
    assert plain_text_to_html(text) == (
        "<p>Hi Akhil,</p>\n"
        "<p>First line<br>second line.</p>\n"
        "<p>Last &amp; &lt;done&gt;.</p>"
    )


def test_long_paragraph_stays_on_one_line():
    sentence = "word " * 60
    assert "\n" not in plain_text_to_html(sentence)


def test_plain_body_resolves_to_html(monkeypatch):
    monkeypatch.delenv("WORKSPACE_MCP_GMAIL_PLAIN_AS_HTML", raising=False)
    assert resolve_outgoing_body("a\n\nb", "plain") == ("<p>a</p>\n<p>b</p>", "html")


def test_html_body_is_untouched():
    assert resolve_outgoing_body("<b>x</b>", "html") == ("<b>x</b>", "html")


@pytest.mark.parametrize("body", [None, ""])
def test_empty_body_is_untouched(body):
    assert resolve_outgoing_body(body, "plain") == (body, "plain")


@pytest.mark.parametrize("value", ["false", "0", "No"])
def test_env_switch_keeps_plain(monkeypatch, value):
    monkeypatch.setenv("WORKSPACE_MCP_GMAIL_PLAIN_AS_HTML", value)
    assert resolve_outgoing_body("a\n\nb", "plain") == ("a\n\nb", "plain")


@pytest.mark.asyncio
async def test_plain_draft_is_html_with_unwrapped_text_alternative(monkeypatch):
    monkeypatch.delenv("WORKSPACE_MCP_GMAIL_PLAIN_AS_HTML", raising=False)
    service = _mock_gmail_service()
    service.users().drafts().create().execute.return_value = {"id": "d1"}
    long_paragraph = "This sentence is long enough to be wrapped. " * 6

    await _unwrap(draft_gmail_message)(
        service=service,
        user_google_email="user@example.com",
        to="recipient@example.com",
        subject="Wrap test",
        body=f"Hi,\n\n{long_paragraph}\n\nThanks",
        include_signature=False,
    )

    raw = service.users.return_value.drafts.return_value.create.call_args.kwargs[
        "body"
    ]["message"]["raw"]
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw)
    )
    assert message.get_content_type() == "multipart/alternative"
    html_part = message.get_body(preferencelist=("html",)).get_content()
    assert f"<p>{long_paragraph.strip()}</p>" in html_part
    text_part = message.get_body(preferencelist=("plain",)).get_content()
    assert long_paragraph.strip() in text_part
