#!/usr/bin/env python3
"""Record evidence when the configured AI reviewer reviewed this PR revision."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".artifacts" / "proof" / "evidence" / "ai-engineering-review.json"


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    pull_request = os.environ["PR_NUMBER"]
    head_sha = os.environ["PR_HEAD_SHA"]
    reviewer_logins = {
        login.strip()
        for login in os.environ.get(
            "AI_REVIEWER_LOGINS", "chatgpt-codex-connector[bot]"
        ).split(",")
        if login.strip()
    }
    url = f"https://api.github.com/repos/{repository}/pulls/{pull_request}/reviews?per_page=100"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request) as response:
        reviews = json.load(response)

    matching = [
        review
        for review in reviews
        if review.get("user", {}).get("login") in reviewer_logins
        and review.get("commit_id") == head_sha
        and review.get("state") in {"COMMENTED", "APPROVED"}
    ]
    if matching:
        latest = matching[-1]
        check = {
            "producer": "GitHub Codex pull request review",
            "status": "passed",
            "evidence": [
                f"reviewer: {latest['user']['login']}",
                f"review_id: {latest['id']}",
                f"review_commit: {head_sha}",
                f"review_state: {latest['state']}",
            ],
        }
    else:
        check = {
            "producer": "GitHub Codex pull request review",
            "status": "not_run",
            "reason": "No configured AI review was found for the current PR head revision.",
        }

    evidence = {
        "version": 2,
        "subject": {"type": "git-commit", "revision": head_sha},
        "results": {"ai-engineering-review": {"ai-engineering-adapter": check}},
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"AI review evidence: {OUTPUT}")
    print(f"AI review status: {check['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
