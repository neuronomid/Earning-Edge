from app.core.logging import _redact_text


def test_redact_text_masks_common_url_credentials() -> None:
    message = (
        "HTTP Request: GET "
        "https://finnhub.io/api/v1/quote?symbol=CSCO&token=abc123 "
        "and https://example.test/path?api_key=secret-value&symbol=IBM"
    )

    redacted = _redact_text(message)

    assert "abc123" not in redacted
    assert "secret-value" not in redacted
    assert "token=<redacted>" in redacted
    assert "api_key=<redacted>" in redacted


def test_redact_text_masks_bearer_tokens() -> None:
    redacted = _redact_text("Authorization: Bearer sk-test-secret")

    assert "sk-test-secret" not in redacted
    assert "Bearer <redacted>" in redacted
