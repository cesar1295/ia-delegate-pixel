"""Errores con mensajes accionables. Cada uno trae su código de salida."""


class DelegateError(Exception):
    """Error de uso o de entorno que el usuario puede corregir."""

    exit_code = 2


class SecretFound(DelegateError):
    """El texto a enviar contiene posibles secretos; el envío se bloquea."""


class MainSessionTask(DelegateError):
    """La tarea le toca a la sesión principal (Claude), no se delega."""

    exit_code = 3
