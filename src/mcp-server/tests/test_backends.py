import base64
import json

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backends.azure import KQL
from backends.github import AppTokens, GitHub
from guard import redact


def test_query_templates_take_only_validated_values():
    for name, template in KQL.items():
        query = template.format(drill_id="drill-x-1", minutes=30)
        assert "{" not in query and "}" not in query, name


def test_redaction_covers_common_secret_shapes():
    text = ("AccountKey=abc123def456; Password=hunter2; ghp_" + "a" * 36 +
            " eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U")
    out = redact(text)
    assert "abc123" not in out and "hunter2" not in out and "ghp_" not in out and "eyJ" not in out


def test_results_report_what_was_redacted_by_kind_never_the_value():
    # v2.2 (blueprint 4.4: redaction metadata in every response)
    from guard import envelope
    out = envelope("test", {"log": "AccountKey=abc123def456; Password=hunter2", "token": "ghp_" + "a" * 36})
    assert out["redaction"] == {"applied": True, "count": 3, "kinds": ["credential", "github_token"]}
    assert "hunter2" not in json.dumps(out) and "abc123" not in json.dumps(out)


def test_commit_uses_one_tree_and_never_forces():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        path = request.url.path
        if path.endswith("/git/ref/heads/candidate/drill-x-1"):
            return httpx.Response(200, json={"object": {"sha": "a" * 40}})
        if "/git/commits/" in path:
            return httpx.Response(200, json={"tree": {"sha": "t" * 40}})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "n" * 40})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "c" * 40})
        if request.method == "PATCH":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    gh = GitHub("org/repo", lambda: "token", transport=httpx.MockTransport(handler))
    assert gh.commit_files("candidate/drill-x-1", {"runbooks/a.md": "new"}, "msg") == "c" * 12
    assert [m for m, *_ in seen] == ["GET", "GET", "POST", "POST", "PATCH"]
    assert seen[-1][2] == {"sha": "c" * 40, "force": False}


def test_app_tokens_are_narrowed_and_cached():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    calls = []

    def handler(request):
        assertion = request.headers["authorization"].split()[1]
        claims = jwt.decode(assertion, key.public_key(), algorithms=["RS256"])
        calls.append((claims["iss"], json.loads(request.content)))
        return httpx.Response(201, json={"token": "ghs_x", "expires_at": "2099-01-01T00:00:00Z"})

    tokens = AppTokens("123", "456", pem, "repo", {"contents": "read"}, transport=httpx.MockTransport(handler))
    assert tokens() == "ghs_x" and tokens() == "ghs_x" and len(calls) == 1
    assert calls[0] == ("123", {"repositories": ["repo"], "permissions": {"contents": "read"}})


def test_read_file_decodes_contents():
    content = base64.b64encode(b"hello").decode()
    gh = GitHub("org/repo", lambda: "t", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"type": "file", "content": content})))
    assert gh.read_file("runbooks/a.md", "main") == "hello"
