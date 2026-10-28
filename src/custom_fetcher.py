import os
from urllib.error import URLError
from urllib.parse import urlsplit
from flask import current_app, has_app_context
from weasyprint.urls import default_url_fetcher
from .logger import ERROR_LOGGER


class ForbiddenURL(Exception):
    pass


def _origin(url):
    parts = urlsplit(url)
    return (parts.scheme.lower(), (parts.hostname or "").lower(), parts.port)


def _base_url():
    if has_app_context():
        return current_app.config.get("BASE_URL")
    return os.environ.get("BASE_URL")


def is_allowed_url(url, base_url):
    """Only inline data and assets served by BASE_URL can be fetched."""
    if url.startswith("data:"):
        return True
    if not base_url:
        return False

    scheme, host, port = _origin(url)
    return scheme in ("http", "https") and (scheme, host, port) == _origin(base_url)


def custom_url_fetcher(url, timeout=10, ssl_context=None):
    if not is_allowed_url(url, _base_url()):
        ERROR_LOGGER.warning("asset refused", extra={"context": {"url": url}})
        # WeasyPrint logs and skips the resource: the PDF is generated without it.
        raise ForbiddenURL(url)

    try:
        result = default_url_fetcher(url, timeout, ssl_context)
    except URLError as e:
        ERROR_LOGGER.warning(
            "asset missing", exc_info=e, extra={"context": {"url": url}}
        )
        # Ugly hack:
        # the caller swallows all `Exception`
        # but raise an AttributeError if the result is None
        result = None
    return result
