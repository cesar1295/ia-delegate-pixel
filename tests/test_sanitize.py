import pytest

from aidelegate.errors import SecretFound
from aidelegate.sanitize import find_secrets, mask_pii, sanitize

SECRETS = [
    "usa sk-proj-abcdefghijklmnopqrstuvwx1234",
    "token ghp_" + "a" * 36,
    "GITHUB_TOKEN=abc123",
    "export DB_PASSWORD=hunter2",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijkl",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "AKIAABCDEFGHIJKLMNOP",
]


@pytest.mark.parametrize("text", SECRETS)
def test_blocks_secrets(text):
    with pytest.raises(SecretFound):
        sanitize(text, source="la tarea")


def test_block_message_never_contains_the_value():
    with pytest.raises(SecretFound) as err:
        sanitize("linea\nAPI_TOKEN=supersecreto123", source="la tarea")
    assert "supersecreto123" not in str(err.value)
    assert "línea 2" in str(err.value)


@pytest.mark.parametrize("text", [
    "API_TOKEN=", 'API_TOKEN=""', "API_TOKEN=$API_TOKEN", "DB_PASSWORD=<tu-password>",
    "  token: string;", "const apiKey = process.env.API_KEY", "usa la variable OPENAI_API_KEY",
    "const API_KEY = process.env.API_KEY", "SECRET: string", "API_KEY = os.environ['API_KEY']",
])
def test_placeholders_and_code_are_not_secrets(text):
    assert find_secrets(text) == []


def test_redact_mode_removes_instead_of_blocking():
    out = sanitize("falló con GITHUB_TOKEN=abc123", source="checks", on_secret="redact")
    assert "abc123" not in out and "[SECRETO-REMOVIDO]" in out


def test_masks_email_phone_and_valid_card():
    out = mask_pii("escribe a ana.lopez@gmail.com o al +52 55 1234 5678, tarjeta 4111 1111 1111 1111")
    assert "[CORREO]" in out and "[TELÉFONO]" in out and "[TARJETA]" in out
    assert "gmail" not in out and "4111" not in out


def test_does_not_mask_invalid_card_dates_or_versions():
    text = "pedido 1234567890123 del 2026-10-04, versión 1.2.15, puerto 3000"
    assert mask_pii(text) == text
