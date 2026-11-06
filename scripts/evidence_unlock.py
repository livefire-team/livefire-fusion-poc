"""Before a teardown only: removes the evidence store's unlocked immutability policies so azd down can delete it.

    python scripts/evidence_unlock.py --yes       # reads EVIDENCE_BLOB_URL and CONTROL_RG from the azd environment

Download anything you want to keep first (az storage blob download-batch --auth-mode login ...). This deletes the
container's default policy, then every blob version's own policy, then every blob version. Locked policies can't be
removed, which is why the lab keeps them unlocked.
"""
import json
import subprocess
import sys

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import AzureCliCredential
from azure.storage.blob import ContainerClient


def azd_values() -> dict:
    out = subprocess.run(["azd", "env", "get-values", "-o", "json"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def main(argv: list[str]) -> int:
    if "--yes" not in argv:
        print(__doc__)
        return 2
    v = azd_values()
    account_url, _, name = v["EVIDENCE_BLOB_URL"].rstrip("/").rpartition("/")
    account = account_url.split("//", 1)[1].split(".", 1)[0]
    rg = v["CONTROL_RG"]
    show = subprocess.run(["az", "storage", "container", "immutability-policy", "show", "--account-name", account,
                           "-g", rg, "--container-name", name, "--query", "etag", "-o", "tsv"],
                          capture_output=True, text=True)
    etag = show.stdout.strip()
    if etag:
        subprocess.run(["az", "storage", "container", "immutability-policy", "delete", "--account-name", account,
                        "-g", rg, "--container-name", name, "--if-match", etag, "-o", "none"], check=True)
        print("container default policy removed")
    container = ContainerClient(account_url, name, credential=AzureCliCredential())
    removed = deleted = failed = 0
    for b in container.list_blobs(include=["versions", "immutabilitypolicy", "legalhold"]):
        client = container.get_blob_client(b.name)
        try:
            if getattr(b.immutability_policy, "expiry_time", None):
                client.delete_immutability_policy(version_id=b.version_id)
                removed += 1
            if getattr(b, "has_legal_hold", False):
                client.set_legal_hold(False, version_id=b.version_id)
            if b.is_current_version:
                client.delete_blob()  # Azure refuses a current version by id (OperationNotAllowedOnRootBlob)
            else:
                client.delete_blob(version_id=b.version_id)
                deleted += 1
        except ResourceNotFoundError:
            continue
        except HttpResponseError as exc:
            failed += 1
            print(f"  could not clear {b.name} ({b.version_id}): {exc.status_code} {exc.error_code}")
    # deleting a current version leaves a previous version behind; one more pass clears what remains
    for b in container.list_blobs(include=["versions"]):
        try:
            container.get_blob_client(b.name).delete_blob(version_id=b.version_id)
            deleted += 1
        except (ResourceNotFoundError, HttpResponseError):
            pass
    # that pass ignores its errors, so whatever is still listed is what azd down would trip over
    left = sum(1 for _ in container.list_blobs(include=["versions"]))
    print(f"version policies removed: {removed}, versions deleted: {deleted}, versions left: {left}, "
          f"failures: {failed}")
    return 1 if failed or left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
