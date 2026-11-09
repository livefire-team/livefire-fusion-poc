"""GitHub REST access. Each endpoint gets its own credential: read-only for the Planner, write for the Engineer."""
import base64
import threading
import time
from datetime import datetime
from urllib.parse import quote

import httpx
import jwt

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


class AppTokens:
    """Short-lived GitHub App installation tokens, narrowed to one repository and the given permissions."""

    def __init__(self, app_id: str, installation_id: str, private_key: str, repo_name: str,
                 permissions: dict, api: str = API, transport=None):
        self.app_id, self.installation_id, self.key = app_id, installation_id, private_key
        self.body = {"repositories": [repo_name], "permissions": permissions}
        self.http = httpx.Client(base_url=api, timeout=20, transport=transport)
        self._token, self._expires, self._lock = None, 0.0, threading.Lock()

    def __call__(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires - 300:
                return self._token
            now = int(time.time())
            assertion = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.key, algorithm="RS256")
            r = self.http.post(f"/app/installations/{self.installation_id}/access_tokens",
                               headers={**HEADERS, "Authorization": f"Bearer {assertion}"}, json=self.body)
            r.raise_for_status()
            data = r.json()
            self._token = data["token"]
            self._expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00")).timestamp()
            return self._token


class GitHub:
    def __init__(self, repo: str, tokens, api: str = API, transport=None):
        self.repo, self.tokens = repo, tokens
        self.http = httpx.Client(base_url=api, timeout=20, transport=transport)

    def _call(self, method, url, **kw):
        r = self.http.request(method, url, headers={**HEADERS, "Authorization": f"Bearer {self.tokens()}"}, **kw)
        if r.status_code == 404:
            raise FileNotFoundError(url)
        r.raise_for_status()
        return r.json() if r.content else {}

    # ---- reads ----
    def read_file(self, path, ref):
        data = self._call("GET", f"/repos/{self.repo}/contents/{quote(path)}", params={"ref": ref})
        if isinstance(data, list) or data.get("type") != "file":
            raise FileNotFoundError(path)
        return base64.b64decode(data["content"]).decode()

    def commit_history(self, path, limit, ref):
        data = self._call("GET", f"/repos/{self.repo}/commits", params={"path": path, "sha": ref, "per_page": limit})
        return [{"sha": c["sha"][:12], "date": c["commit"]["author"]["date"],
                 "author": c["commit"]["author"]["name"], "message": c["commit"]["message"]} for c in data]

    # ---- candidate branch ----
    def _ref_sha(self, branch):
        return self._call("GET", f"/repos/{self.repo}/git/ref/heads/{quote(branch)}")["object"]["sha"]

    def branch_exists(self, branch):
        try:
            self._ref_sha(branch)
            return True
        except FileNotFoundError:
            return False

    def create_branch(self, name, base):
        if self.branch_exists(name):
            return {"branch": name, "created": False}
        sha = base if len(base) == 40 else self._ref_sha(base)
        self._call("POST", f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})
        return {"branch": name, "created": True, "base": sha[:12]}

    def commit_files(self, branch, files: dict, message):
        head = self._ref_sha(branch)
        base_tree = self._call("GET", f"/repos/{self.repo}/git/commits/{head}")["tree"]["sha"]
        tree = self._call("POST", f"/repos/{self.repo}/git/trees", json={
            "base_tree": base_tree,
            "tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()],
        })["sha"]
        commit = self._call("POST", f"/repos/{self.repo}/git/commits",
                            json={"message": message, "tree": tree, "parents": [head]})["sha"]
        self._call("PATCH", f"/repos/{self.repo}/git/refs/heads/{quote(branch)}", json={"sha": commit, "force": False})
        return commit[:12]

    def ci_results(self, branch):
        runs = self._call("GET", f"/repos/{self.repo}/actions/runs", params={"branch": branch, "per_page": 1})
        if not runs.get("workflow_runs"):
            return {"branch": branch, "status": "not_started"}
        run = runs["workflow_runs"][0]
        jobs = self._call("GET", f"/repos/{self.repo}/actions/runs/{run['id']}/jobs").get("jobs", [])
        failed = [{"job": j["name"], "steps": [s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"]}
                  for j in jobs if j.get("conclusion") == "failure"]
        return {"branch": branch, "status": run["status"], "conclusion": run.get("conclusion"),
                "url": run["html_url"], "head_sha": run["head_sha"][:12], "failed_jobs": failed}
