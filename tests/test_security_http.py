import pytest
from urllib.error import HTTPError
from urllib.request import Request

from ari_os.tools import _http


def test_no_https_to_http_downgrade():
    handler = _http._NoDowngrade()
    req = Request("https://api.example.com/x")
    with pytest.raises(HTTPError):
        handler.redirect_request(
            req,
            None,
            302,
            "Found",
            {},
            "http://evil.example.com/x",
        )
