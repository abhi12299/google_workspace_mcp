"""A reply carries the message it answers below it, as Gmail's own composer
does, so the recipient keeps the whole thread in one message."""

import time

import pytest

from gmail.gmail_tools import draft_gmail_message, send_gmail_message
from tests.gmail.test_draft_gmail_message import (
    _mock_gmail_service,
    _parse_raw_message,
    _thread_message,
    _unwrap,
)


def _service_with_thread(**message_kwargs):
    service = _mock_gmail_service()
    service.users().messages().send().execute.return_value = {"id": "sent"}
    service.users().drafts().create().execute.return_value = {"id": "draft"}
    message_kwargs.setdefault("from_value", "Alice Example <alice@example.com>")
    message_kwargs.setdefault("text", "Original plain text")
    message_kwargs.setdefault("html", "<p>Original html</p>")
    service.users().threads().get().execute.return_value = {
        "messages": [_thread_message("<msg1@example.com>", **message_kwargs)]
    }
    return service


def _sent(service):
    kwargs = service.users.return_value.messages.return_value.send.call_args.kwargs
    return _parse_raw_message(kwargs["body"]["raw"])


def _drafted(service):
    kwargs = service.users.return_value.drafts.return_value.create.call_args.kwargs
    return _parse_raw_message(kwargs["body"]["message"]["raw"])


def _html(message):
    return message.get_body(preferencelist=("html",)).get_content()


def _text(message):
    return message.get_body(preferencelist=("plain",)).get_content()


async def _reply(tool, service, **kwargs):
    await _unwrap(tool)(
        service=service,
        user_google_email="user@example.com",
        to="alice@example.com",
        subject="Re: Meeting tomorrow",
        body="Thanks for the update.",
        thread_id="thread123",
        include_signature=False,
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool, read", [(send_gmail_message, _sent), (draft_gmail_message, _drafted)]
)
async def test_reply_quotes_the_original_by_default(monkeypatch, tool, read):
    monkeypatch.delenv("WORKSPACE_MCP_GMAIL_PLAIN_AS_HTML", raising=False)
    service = _service_with_thread()

    await _reply(tool, service)

    html_part = _html(read(service))
    assert "<p>Thanks for the update.</p>" in html_part
    assert "<p>Original html</p>" in html_part


@pytest.fixture
def ist(monkeypatch):
    """Pin the local zone: the attribution reads in the composer's time, as Gmail's does."""
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.asyncio
async def test_quote_uses_gmail_markup_and_attribution(ist):
    service = _service_with_thread(date="Fri, 06 Nov 2026 05:44:59 +0000")

    await _reply(send_gmail_message, service)

    html_part = _html(_sent(service))
    assert '<div class="gmail_quote gmail_quote_container">' in html_part
    assert (
        '<div dir="ltr" class="gmail_attr">On Fri, 6 Nov 2026 at 11:14 AM, '
        'Alice Example &lt;<a href="mailto:alice@example.com">alice@example.com</a>'
        "&gt; wrote:<br></div>"
    ) in html_part
    assert '<blockquote class="gmail_quote"' in html_part
    # Gmail collapses everything inside the quote container behind "...".
    reply_end = html_part.index("Thanks for the update.")
    assert reply_end < html_part.index("gmail_quote_container")


@pytest.mark.asyncio
async def test_text_alternative_quotes_with_angle_brackets(monkeypatch):
    monkeypatch.delenv("WORKSPACE_MCP_GMAIL_PLAIN_AS_HTML", raising=False)
    service = _service_with_thread(text="First line\n\nSecond line")

    await _reply(draft_gmail_message, service)

    text_part = _text(_drafted(service)).replace("\r\n", "\n")
    assert text_part.startswith("Thanks for the update.\n\nOn ")
    assert "Alice Example <alice@example.com> wrote:\n" in text_part
    assert "> First line\n>\n> Second line" in text_part


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool, read", [(send_gmail_message, _sent), (draft_gmail_message, _drafted)]
)
async def test_text_only_original_keeps_its_spacing(monkeypatch, tool, read):
    monkeypatch.delenv("WORKSPACE_MCP_GMAIL_PLAIN_AS_HTML", raising=False)
    original = "def f():\n    return 1  # a < b\n\ncol1    col2"
    service = _service_with_thread(text=original, html=None)

    await _reply(tool, service)

    html_part = _html(read(service)).replace("\r\n", "\n")
    assert (
        '<div style="white-space:pre-wrap">'
        "def f():\n    return 1  # a &lt; b\n\ncol1    col2</div>"
    ) in html_part


@pytest.mark.asyncio
async def test_quote_keeps_only_the_body_and_drops_inline_images():
    outlook_html = (
        "<html><head><style>p{color:red}</style></head>"
        '<body lang="EN-US"><p>Original html</p>'
        '<img border="0" src="cid:image001.png@01DC" alt="logo">'
        '<img src="https://example.com/remote.png"></body></html>'
    )
    service = _service_with_thread(html=outlook_html)

    await _reply(send_gmail_message, service)

    html_part = _html(_sent(service))
    assert "<p>Original html</p>" in html_part
    assert "cid:" not in html_part
    assert '<img src="https://example.com/remote.png">' in html_part
    assert "<style>" not in html_part and "<body" not in html_part


@pytest.mark.asyncio
async def test_quote_original_false_sends_the_new_text_alone():
    service = _service_with_thread()

    await _reply(send_gmail_message, service, quote_original=False)

    message = _sent(service)
    assert "Original" not in _html(message)
    assert "wrote:" not in _text(message)
    # Headers still thread the reply.
    assert message["In-Reply-To"] == "<msg1@example.com>"
