"""Hardened HTTP helpers for ARI-OS network callers."""
from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, build_opener


class _NoDowngrade(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.full_url.lower().startswith("https://") and newurl.lower().startswith(
            "http://"
        ):
            raise HTTPError(
                req.full_url,
                code,
                "refused HTTPS->HTTP redirect",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_NoDowngrade)


def open_url(req, timeout):
    """Drop-in replacement for urlopen(req, timeout=...) with no downgrades."""
    return _OPENER.open(req, timeout=timeout)
