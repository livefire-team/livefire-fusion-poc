"""Canned evidence and an in-memory repository: G1 work and tests, no Azure or GitHub needed."""
import copy
import hashlib
import json
import os
from pathlib import Path


FAULT_SETS = ("identity-rbac", "secret-drift", "config-drift", "network-drift")


class FixtureEvidence:
    """The twin's evidence as canned data. v2.0: one set per fault, chosen from the drill's own drill.start event,
    as if the tools were reading the real twin. The fault's name is never part of any result."""

    def __init__(self, path: str, store=None):
        self.data = json.loads(Path(path).read_text())
        self.store = store

    def _set(self, drill_id) -> dict:
        fault = None
        if self.store is not None and drill_id:
            try:
                start = next((e for e in self.store.read(drill_id) if e.get("action") == "drill.start"), None)
                fault = ((start or {}).get("details") or {}).get("fault")
            except (OSError, ValueError):
                fault = None
        base = {k: self.data[k] for k in ("telemetry", "identity_snapshot", "secret_metadata", "app_configuration",
                                          "network_rules") if k in self.data}
        if fault in FAULT_SETS and fault in self.data.get("faults", {}):
            base = {**base, **self.data["faults"][fault]}
        return base

    def telemetry(self, drill_id, signal, minutes):
        return copy.deepcopy(self._set(drill_id)["telemetry"].get(signal, []))

    def identity_snapshot(self, drill_id=None):
        return copy.deepcopy(self._set(drill_id)["identity_snapshot"])

    def secret_metadata(self, drill_id=None):
        return copy.deepcopy(self._set(drill_id)["secret_metadata"])

    def app_configuration(self, drill_id=None):
        return copy.deepcopy(self._set(drill_id)["app_configuration"])

    def network_rules(self, drill_id=None):
        return copy.deepcopy(self._set(drill_id)["network_rules"])

    def _learned(self) -> list[dict]:
        """Findings earlier drills left (the learning loop, laptop form): KNOWLEDGE_DIR/*.json from the Drill Runner."""
        root = os.environ.get("KNOWLEDGE_DIR")
        if not root or not Path(root).is_dir():
            return []
        return [json.loads(p.read_text()) for p in sorted(Path(root).glob("*.json"))]

    def search_incidents(self, query, top, from_date=None, to_date=None):
        words = {w.lower() for w in query.split() if len(w) > 2}
        scored = []
        for doc in self.data["incidents"] + self._learned():
            day = str(doc.get("occurred_at", ""))[:10]
            if (from_date and day < from_date) or (to_date and day > to_date):
                continue
            text = " ".join(str(v) for v in doc.values()).lower()
            score = sum(text.count(w) for w in words)
            if score:
                scored.append((score, doc))
        return [copy.deepcopy(d) for _, d in sorted(scored, key=lambda s: -s[0])[:top]]

    def read_file(self, path, ref):
        try:
            return self.data["repo"][path]
        except KeyError:
            raise FileNotFoundError(path) from None

    def commit_history(self, path, limit, ref):
        return copy.deepcopy(self.data["commits"].get(path, []))[:limit]


class FixtureRepo:
    """Branches held in memory. Same methods as the GitHub backend."""

    def __init__(self, files: dict[str, str]):
        self.branches = {"main": dict(files)}
        self.commits: dict[str, list[str]] = {"main": []}

    def read_file(self, path, ref):
        files = self.branches.get(ref)
        if files is None or path not in files:
            raise FileNotFoundError(path)
        return files[path]

    def branch_exists(self, name):
        return name in self.branches

    def create_branch(self, name, base):
        if name in self.branches:
            return {"branch": name, "created": False}
        self.branches[name] = dict(self.branches[base])
        self.commits[name] = []
        return {"branch": name, "created": True, "base": base}

    def commit_files(self, branch, files, message):
        self.branches[branch].update(files)
        # A fake 40-hex commit ID for the in-memory repo
        sha = hashlib.sha256((branch + message + json.dumps(files, sort_keys=True)).encode()).hexdigest()[:40]
        self.commits[branch].append(sha)
        return sha[:12]

    def ci_results(self, branch):
        if not self.commits.get(branch):
            return {"branch": branch, "status": "not_started"}
        return {"branch": branch, "status": "completed", "conclusion": "success", "failed_jobs": []}
