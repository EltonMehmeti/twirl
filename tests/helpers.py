import re

CSRF_RE = re.compile(r'name="csrf-token" content="([^"]+)"')


def csrf_from(client, path: str = "/") -> str:
    match = CSRF_RE.search(client.get(path).text)
    assert match, f"no csrf meta tag on {path}"
    return match.group(1)


def post(client, path: str, data: dict | None = None, files=None):
    token = csrf_from(client, "/")
    return client.post(
        path, data={**(data or {}), "csrf_token": token}, files=files, follow_redirects=False
    )


PASSWORD = "pw-123456"


def login(client, email: str, password: str = PASSWORD):
    token = csrf_from(client, "/login")
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token, "next": "/shop"},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response
