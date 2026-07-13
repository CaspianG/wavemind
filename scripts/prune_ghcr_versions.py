from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable


SHA_TAG = re.compile(r"sha-[0-9a-f]+", re.IGNORECASE)


def should_delete(tags: Iterable[str]) -> bool:
    normalized = [tag.strip() for tag in tags if tag and tag.strip()]
    return bool(normalized) and all(SHA_TAG.fullmatch(tag) for tag in normalized)


def _request(url: str, token: str, *, method: str = "GET") -> object | None:
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "wavemind-package-retention",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status == 204:
                return None
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {url} failed: {exc.code} {detail}") from exc


def list_versions(api_url: str, owner: str, package: str, token: str) -> list[dict]:
    package_name = urllib.parse.quote(package, safe="")
    versions: list[dict] = []
    for page in range(1, 101):
        url = (
            f"{api_url}/users/{urllib.parse.quote(owner, safe='')}/packages/container/"
            f"{package_name}/versions?per_page=100&page={page}"
        )
        payload = _request(url, token)
        if not isinstance(payload, list):
            raise RuntimeError("GitHub package versions response is not a list")
        versions.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            break
    return versions


def version_tags(version: dict) -> list[str]:
    metadata = version.get("metadata")
    if not isinstance(metadata, dict):
        return []
    container = metadata.get("container")
    if not isinstance(container, dict):
        return []
    tags = container.get("tags")
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags]


def prune(
    *,
    api_url: str,
    owner: str,
    package: str,
    token: str,
    apply: bool,
    max_delete: int,
) -> dict:
    versions = list_versions(api_url, owner, package, token)
    candidates = [version for version in versions if should_delete(version_tags(version))]
    candidates.sort(key=lambda item: str(item.get("created_at", "")))
    selected = candidates[:max_delete]

    deleted: list[int] = []
    if apply:
        package_name = urllib.parse.quote(package, safe="")
        owner_name = urllib.parse.quote(owner, safe="")
        for version in selected:
            version_id = int(version["id"])
            url = (
                f"{api_url}/users/{owner_name}/packages/container/"
                f"{package_name}/versions/{version_id}"
            )
            _request(url, token, method="DELETE")
            deleted.append(version_id)

    return {
        "schema": "wavemind.ghcr_retention.v1",
        "owner": owner,
        "package": package,
        "apply": apply,
        "scanned": len(versions),
        "candidates": len(candidates),
        "selected": len(selected),
        "deleted": len(deleted),
        "protected": len(versions) - len(candidates),
        "candidate_ids": [int(version["id"]) for version in selected],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete GHCR versions whose tags are exclusively one-off sha-* tags."
    )
    parser.add_argument("--owner", default=os.getenv("GITHUB_REPOSITORY_OWNER", "CaspianG"))
    parser.add_argument("--package", default="wavemind")
    parser.add_argument("--api-url", default=os.getenv("GITHUB_API_URL", "https://api.github.com"))
    parser.add_argument("--max-delete", type=int, default=500)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        parser.error("GITHUB_TOKEN is required")
    if args.max_delete < 1:
        parser.error("--max-delete must be at least 1")

    result = prune(
        api_url=args.api_url.rstrip("/"),
        owner=args.owner,
        package=args.package,
        token=token,
        apply=args.apply,
        max_delete=args.max_delete,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
