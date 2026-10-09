"""Shared image URL policy for server-side image consumers."""

from urllib.parse import urlsplit

ALLOWED_IMAGE_HOST_SUFFIXES = (
    "olxcdn.com",
    "staticmorizon.com.pl",
    "nieruchomosci-online.pl",
    "st-nieruchomosci-online.pl",
    "otodom.pl",
    "otodomcdn.com",
    "unsplash.com",
)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_DATA_IMAGE_URL_CHARS = MAX_IMAGE_BYTES * 4 // 3 + 256


def is_allowed_image_url(url: str) -> bool:
    """Allow only known public image hosts and standard HTTP(S) ports."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        return False
    if port is not None and port not in {80, 443}:
        return False
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_IMAGE_HOST_SUFFIXES)


def is_allowed_image_reference(url: str) -> bool:
    """Allow capped inline images or remote images from known public hosts."""
    if url.startswith("data:image/"):
        return len(url) <= MAX_DATA_IMAGE_URL_CHARS
    return is_allowed_image_url(url)
