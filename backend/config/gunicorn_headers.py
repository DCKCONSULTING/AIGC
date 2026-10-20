"""Drop duplicate Host headers that nginx can send to Gunicorn.

Gunicorn 26 treats Host as a singleton (RFC 9110) and returns 400 when nginx
sets it twice: `include proxy_params` (Host $http_host) plus
`proxy_set_header Host $host` in the same location.
"""


def install_duplicate_host_workaround() -> None:
    try:
        from gunicorn.http.message import HeaderPolicy
    except ImportError:
        return

    original = HeaderPolicy._apply_header_policy

    def _apply_header_policy(
        self,
        name,
        value,
        scheme_state,
        seen,
        secure_scheme_headers,
        forwarder_headers,
        from_trailer=False,
    ):
        if name == "HOST" and name in seen:
            return None
        return original(
            self,
            name,
            value,
            scheme_state,
            seen,
            secure_scheme_headers,
            forwarder_headers,
            from_trailer=from_trailer,
        )

    HeaderPolicy._apply_header_policy = _apply_header_policy
