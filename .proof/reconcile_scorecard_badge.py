#!/usr/bin/env python3
# Proof installer-owned runtime.
"""Reconcile and render the newest trustworthy PR scorecard for GitHub Pages."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


WORKFLOW_NAME = "Proof Scorecard"
WORKFLOW_FILE = ".github/workflows/proof-scorecard.yml"
VALID_EVENTS = {"pull_request_target", "pull_request_review"}
VALID_CONCLUSIONS = {"success", "failure"}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_MEMBER_BYTES = 64_000
MAX_EXPANDED_BYTES = 1_000_000
RUNS_PER_PAGE = 100
MAX_RUN_PAGES = 1_000


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class StalePublication(ValueError):
    """Raised when all completed candidates predate the published tuple."""


class CandidateRejected(ValueError):
    """Raised for invalid candidate-specific evidence while reconciliation continues."""


class ArtifactRejected(ValueError):
    """Raised when one artifact cannot be accepted as candidate evidence."""


class APIResponseError(ValueError):
    """Raised when authenticated GitHub API state cannot be validated."""


class TrustedRuntimeError(RuntimeError):
    """Raised when the default-branch publisher runtime cannot execute reliably."""


def _integer(value: Any, field: str, *, positive: bool = False) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    if value < (1 if positive else 0):
        raise ValueError(f"{field} must be {'positive' if positive else 'nonnegative'}")
    return value


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a normalized UTC timestamp")
    return value


def _repository(value: Any) -> str:
    if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value):
        raise ValueError("repository must use OWNER/REPOSITORY format")
    return value


def pages_base_url(repository: str) -> str:
    owner, name = _repository(repository).split("/", 1)
    owner = owner.lower()
    if name.lower() == f"{owner}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{name}/"


def workflow_path_allowed(value: Any, default_branch: str) -> bool:
    if not isinstance(value, str):
        return False
    return value in {
        WORKFLOW_FILE,
        f"{WORKFLOW_FILE}@{default_branch}",
        f"{WORKFLOW_FILE}@refs/heads/{default_branch}",
    }


def validate_run(
    run: dict[str, Any], repository: str, default_branch: str
) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise ValueError("workflow run must be an object")
    nested_repository = run.get("repository")
    if (
        not isinstance(nested_repository, dict)
        or nested_repository.get("full_name") != repository
    ):
        raise ValueError("workflow run repository does not match")
    if run.get("name") != WORKFLOW_NAME:
        raise ValueError("workflow run name does not match")
    if not workflow_path_allowed(run.get("path"), default_branch):
        raise ValueError(
            "workflow run path is not the default-branch scorecard workflow"
        )
    event = run.get("event")
    conclusion = run.get("conclusion")
    if not isinstance(event, str) or event not in VALID_EVENTS:
        raise ValueError("workflow run event is not eligible")
    if not isinstance(conclusion, str) or conclusion not in VALID_CONCLUSIONS:
        raise ValueError("workflow run conclusion is not eligible")
    normalized = dict(run)
    normalized["id"] = _integer(run.get("id"), "run.id", positive=True)
    normalized["run_attempt"] = _integer(
        run.get("run_attempt"), "run.run_attempt", positive=True
    )
    normalized["created_at"] = _timestamp(run.get("created_at"), "run.created_at")
    return normalized


def run_tuple(run: dict[str, Any]) -> tuple[str, int, int]:
    return (
        _timestamp(run.get("created_at"), "run.created_at"),
        _integer(run.get("id"), "run.id", positive=True),
        _integer(run.get("run_attempt"), "run.run_attempt", positive=True),
    )


def published_tuple(document: dict[str, Any] | None) -> tuple[str, int, int] | None:
    if document is None:
        return None
    if not isinstance(document, dict):
        raise ValueError("published scorecard must be an object")
    return (
        _timestamp(
            document.get("source_run_created_at"), "published.source_run_created_at"
        ),
        _integer(
            document.get("source_run_id"), "published.source_run_id", positive=True
        ),
        _integer(
            document.get("source_run_attempt"),
            "published.source_run_attempt",
            positive=True,
        ),
    )


def validate_published_scorecard(
    document: dict[str, Any] | None, repository: str
) -> dict[str, Any] | None:
    if document is None:
        return None
    if not isinstance(document, dict):
        raise ValueError("published scorecard must be an object")
    if document.get("version") != 1 or type(document.get("version")) is not int:
        raise ValueError("published scorecard version must be 1")
    if (
        document.get("operation") != "change"
        or document.get("repository") != repository
    ):
        raise ValueError("published scorecard identity does not match")
    status = document.get("status")
    decision = document.get("decision")
    if (
        not isinstance(status, str)
        or status not in {"GREEN", "ORANGE", "RED"}
        or not isinstance(decision, str)
        or decision not in {"allow", "block"}
    ):
        raise ValueError("published scorecard status is invalid")
    passed = _integer(document.get("passed"), "published.passed")
    total = _integer(document.get("total"), "published.total", positive=True)
    if passed > total:
        raise ValueError("published passed count cannot exceed total")
    modes: dict[str, tuple[int, int]] = {}
    for mode in ("enforced", "advisory"):
        counts = document.get(mode)
        if not isinstance(counts, dict):
            raise ValueError(f"published {mode} counts must be an object")
        mode_passed = _integer(counts.get("passed"), f"published.{mode}.passed")
        mode_total = _integer(counts.get("total"), f"published.{mode}.total")
        if mode_passed > mode_total:
            raise ValueError(f"published {mode} passed count cannot exceed total")
        modes[mode] = (mode_passed, mode_total)
    if passed != sum(value[0] for value in modes.values()) or total != sum(
        value[1] for value in modes.values()
    ):
        raise ValueError("published aggregate counts do not match mode counts")
    expected_status = (
        "RED"
        if modes["enforced"][0] < modes["enforced"][1]
        else "ORANGE"
        if modes["advisory"][0] < modes["advisory"][1]
        else "GREEN"
    )
    expected_decision = "block" if expected_status == "RED" else "allow"
    if status != expected_status or decision != expected_decision:
        raise ValueError("published status is inconsistent with counts")
    digest = document.get("subject_digest")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
    ):
        raise ValueError("published subject digest is invalid")
    published_tuple(document)
    return document


def validate_source_binding(
    source: dict[str, Any],
    run: dict[str, Any],
    pull_request: dict[str, Any],
    repository: str,
    default_branch: str,
    scorecard_revision: str,
    ancestry_checker: Callable[[str], bool],
) -> None:
    expected_keys = {
        "version",
        "run_id",
        "run_attempt",
        "event",
        "repository",
        "pull_request_number",
        "head_sha",
        "base_repository",
        "base_branch",
        "base_sha",
    }
    if not isinstance(source, dict) or set(source) != expected_keys:
        raise ValueError("source binding fields are incomplete or ambiguous")
    if source.get("version") != 1 or type(source.get("version")) is not int:
        raise ValueError("source binding version must be 1")
    if source.get("run_id") != run["id"] or type(source.get("run_id")) is not int:
        raise ValueError("source binding run ID does not match")
    if (
        source.get("run_attempt") != run["run_attempt"]
        or type(source.get("run_attempt")) is not int
    ):
        raise ValueError("source binding run attempt does not match")
    if source.get("event") != run["event"]:
        raise ValueError("source binding event does not match")
    if (
        source.get("repository") != repository
        or source.get("base_repository") != repository
    ):
        raise ValueError("source binding repository does not match")
    pull_number = _integer(
        source.get("pull_request_number"), "source.pull_request_number", positive=True
    )
    if pull_request.get("number") != pull_number:
        raise ValueError("source binding pull request number does not match")
    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise ValueError("pull request response is incomplete")
    base_repo = base.get("repo")
    if (
        not isinstance(base_repo, dict)
        or base_repo.get("full_name") != repository
        or base.get("ref") != default_branch
        or source.get("base_branch") != default_branch
    ):
        raise ValueError("pull request base is not the repository default branch")
    head_sha = source.get("head_sha")
    base_sha = source.get("base_sha")
    if not isinstance(head_sha, str) or not SHA_PATTERN.fullmatch(head_sha):
        raise ValueError("source head SHA is invalid")
    if not isinstance(base_sha, str) or not SHA_PATTERN.fullmatch(base_sha):
        raise ValueError("source base SHA is invalid")
    if head.get("sha") != head_sha or scorecard_revision != head_sha:
        raise ValueError("source head SHA does not match current PR and scorecard")
    if not ancestry_checker(base_sha):
        raise ValueError(
            "source base SHA is not an ancestor of the current default branch"
        )


def validate_pull_request_response(pull_request: Any) -> dict[str, Any]:
    if not isinstance(pull_request, dict):
        raise APIResponseError("pull request response must be an object")
    head = pull_request.get("head")
    base = pull_request.get("base")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    if (
        type(pull_request.get("number")) is not int
        or not isinstance(head, dict)
        or not isinstance(head.get("sha"), str)
        or not isinstance(base, dict)
        or not isinstance(base.get("ref"), str)
        or not isinstance(base_repo, dict)
        or not isinstance(base_repo.get("full_name"), str)
    ):
        raise APIResponseError("pull request response is incomplete or malformed")
    return pull_request


def extract_artifact(payload: bytes, destination: Path) -> Path:
    if not isinstance(payload, bytes) or len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("artifact archive exceeds the compressed size limit")
    destination = Path(destination)
    if destination.is_symlink() or (
        destination.exists() and any(destination.iterdir())
    ):
        raise ValueError(
            "artifact extraction destination must be an empty real directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f"artifact archive is not a valid ZIP: {error}") from error
    try:
        with archive:
            members = archive.infolist()
            names: set[str] = set()
            expanded = 0
            for member in members:
                name = member.filename
                path = PurePosixPath(name)
                mode = (member.external_attr >> 16) & 0xFFFF
                if (
                    not name
                    or "\\" in name
                    or path.is_absolute()
                    or len(path.parts) != 1
                    or path.parts[0] in {".", ".."}
                    or member.is_dir()
                    or stat.S_ISLNK(mode)
                    or (mode and not stat.S_ISREG(mode))
                ):
                    raise ValueError(f"artifact contains an unsafe member: {name!r}")
                if name in names:
                    raise ValueError(f"artifact contains a duplicate member: {name}")
                names.add(name)
                if member.file_size > MAX_MEMBER_BYTES:
                    raise ValueError(f"artifact member exceeds the size limit: {name}")
                expanded += member.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise ValueError("artifact exceeds the expanded size limit")
            scorecard_json = sorted(
                name
                for name in names
                if re.fullmatch(r"scorecard-[0-9]{8}-[0-9]{6}Z\.json", name)
            )
            if len(scorecard_json) != 1:
                raise ValueError(
                    "artifact must contain exactly one timestamped scorecard JSON"
                )
            paired_markdown = scorecard_json[0][:-5] + ".md"
            required = {scorecard_json[0], paired_markdown, "source.json"}
            if names != required:
                raise ValueError(
                    "artifact must contain only the scorecard pair and source binding"
                )
            for member in members:
                content = archive.read(member)
                if len(content) != member.file_size or len(content) > MAX_MEMBER_BYTES:
                    raise ValueError(
                        f"artifact member size changed while reading: {member.filename}"
                    )
                (destination / member.filename).write_bytes(content)
    except (RuntimeError, zipfile.BadZipFile) as error:
        raise ValueError(f"artifact ZIP cannot be read safely: {error}") from error
    return destination


def download_artifact(
    url: str,
    token: str,
    *,
    opener: Any = None,
    unsigned_open: Callable[..., Any] = urlopen,
) -> bytes:
    parsed_api = urlparse(url)
    if parsed_api.scheme != "https" or parsed_api.netloc != "api.github.com":
        raise APIResponseError("artifact API URL must use https://api.github.com")
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    redirect_opener = opener or build_opener(NoRedirectHandler())
    try:
        redirect_opener.open(request, timeout=20)
    except HTTPError as error:
        if error.code != 302:
            describe_http_failure(error, "artifact redirect")
            raise
        location = error.headers.get("Location")
    else:
        raise APIResponseError("artifact endpoint did not return the expected redirect")
    parsed = urlparse(location or "")
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise APIResponseError(
            "artifact redirect must be an absolute credential-free HTTPS URL"
        )
    unsigned_request = Request(location, headers={"Accept": "application/octet-stream"})
    try:
        with unsigned_open(unsigned_request, timeout=20) as response:
            content = response.read(MAX_ARCHIVE_BYTES + 1)
    except HTTPError as error:
        describe_http_failure(error, "artifact download")
        raise
    if len(content) > MAX_ARCHIVE_BYTES:
        raise ArtifactRejected("artifact archive exceeds the compressed size limit")
    return content


def exact_artifact(listing: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(listing, dict):
        raise APIResponseError("artifact listing must be an object")
    artifacts = listing.get("artifacts")
    total = listing.get("total_count")
    if (
        type(total) is not int
        or not isinstance(artifacts, list)
        or total != len(artifacts)
        or any(not isinstance(item, dict) for item in artifacts)
    ):
        raise APIResponseError("artifact listing is incomplete or malformed")
    expected = f"proof-scorecard-{run['id']}-{run['run_attempt']}"
    matching = [
        item
        for item in artifacts
        if item.get("name") == expected and item.get("expired") is False
    ]
    if len(matching) != 1:
        raise CandidateRejected(
            "source run must have one exact non-expired scorecard artifact"
        )
    _integer(matching[0].get("id"), "artifact.id", positive=True)
    return matching[0]


def select_candidate(
    runs: Iterable[dict[str, Any]],
    current: tuple[str, int, int] | None,
    validate: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    allow_fallback: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    rejected: list[str] = []
    reached_older = False
    previous: tuple[str, int, int] | None = None
    for candidate in runs:
        candidate_tuple = run_tuple(candidate)
        if previous is not None and candidate_tuple > previous:
            raise ValueError("workflow runs are not ordered newest-first")
        previous = candidate_tuple
        if current is not None and candidate_tuple < current:
            reached_older = True
            break
        try:
            return validate(candidate), rejected
        except CandidateRejected as error:
            if not allow_fallback:
                raise ValueError(f"private Pages cannot fall back to older evidence; newest candidate rejected: {error}") from error
            rejected.append(
                f"run {candidate.get('id')} attempt {candidate.get('run_attempt')}: {error}"
            )
    if reached_older:
        raise StalePublication(
            "no valid candidate is as new as the published scorecard"
        )
    raise ValueError("no valid completed scorecard candidate was found")


def github_request_context(url: str) -> str:
    """Name known operations without exposing repository names, query strings or signed URLs."""
    path = urlparse(url).path
    routes = (
        (r"/repos/[^/]+/[^/]+", "repository metadata"),
        (r"/repos/[^/]+/[^/]+/pages", "Pages configuration"),
        (r"/repos/[^/]+/[^/]+/actions/workflows/[^/]+/runs", "completed scorecard runs"),
        (r"/repos/[^/]+/[^/]+/actions/runs/[^/]+/artifacts", "run artifact listing"),
        (r"/repos/[^/]+/[^/]+/actions/artifacts/[^/]+/zip", "artifact redirect"),
        (r"/repos/[^/]+/[^/]+/pulls/[^/]+", "pull request metadata"),
    )
    return next((label for pattern, label in routes if re.fullmatch(pattern, path)), "GitHub API request")


def describe_http_failure(error: HTTPError, context: str) -> None:
    """Replace unsafe server prose with bounded diagnostics, retaining the same HTTPError and status."""
    headers = {name.lower(): str(value) for name, value in (error.headers or {}).items()}
    details = []
    for name in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-used", "x-ratelimit-reset", "retry-after"):
        value = headers.get(name, "")
        if re.fullmatch(r"[0-9]{1,20}", value):
            details.append(f"{name}={value}")
    request_id = headers.get("x-github-request-id", "")
    if re.fullmatch(r"[A-Za-z0-9:-]{1,128}", request_id):
        details.append(f"request-id={request_id}")
    message = ""
    try:
        body = json.loads(error.read(4096))
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            message = body["message"].lower()
    except (OSError, ValueError, TypeError, UnicodeError, HTTPException, RecursionError):
        pass
    classification = {401: "authentication-failed", 403: "forbidden-unknown", 404: "not-found",
                      429: "rate-limit-unspecified"}.get(error.code, "http-failure")
    if error.code in {403, 429}:
        if headers.get("x-ratelimit-remaining") == "0":
            classification = "primary-rate-limit"
        elif "secondary rate limit" in message:
            classification = "secondary-rate-limit"
        elif message in {"resource not accessible by integration", "resource not accessible by personal access token"}:
            classification = "permission-denied"
    error.msg = "; ".join([context, classification, *details])


class GitHubClient:
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("GitHub token is required")
        self.token = token

    def json(self, url: str) -> Any:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com":
            raise ValueError("GitHub API URL must use https://api.github.com")
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return json.load(response)
        except HTTPError as error:
            describe_http_failure(error, github_request_context(url))
            raise

    def artifact(self, repository: str, artifact_id: int) -> bytes:
        return download_artifact(
            f"https://api.github.com/repos/{repository}/actions/artifacts/{artifact_id}/zip",
            self.token,
        )


def completed_runs(client: GitHubClient, repository: str) -> Iterator[dict[str, Any]]:
    encoded_workflow = quote("proof-scorecard.yml", safe="")
    for page in range(1, MAX_RUN_PAGES + 1):
        payload = client.json(
            f"https://api.github.com/repos/{repository}/actions/workflows/{encoded_workflow}/runs"
            f"?status=completed&per_page={RUNS_PER_PAGE}&page={page}"
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("workflow_runs"), list
        ):
            raise ValueError("workflow-run page is malformed")
        page_runs = payload["workflow_runs"]
        if any(not isinstance(item, dict) for item in page_runs):
            raise ValueError("workflow-run page contains a non-object")
        for item in page_runs:
            yield item
        if len(page_runs) < RUNS_PER_PAGE:
            return
    raise ValueError("workflow-run pagination exceeds the safe page limit")


def read_published_scorecard(url: str) -> dict[str, Any] | None:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            value = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        describe_http_failure(error, "published scorecard download")
        raise
    if not isinstance(value, dict):
        raise ValueError("published scorecard response must be an object")
    return value


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"{label} is invalid: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    return value


def _run_renderer(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()
        if completed.returncode == 2 and completed.stderr.startswith("ERROR:"):
            raise CandidateRejected(detail)
        raise TrustedRuntimeError(
            f"trusted renderer failed ({' '.join(command[:3])}): {detail}"
        )
    return completed


def _write_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"output value for {key} contains a newline")
            stream.write(f"{key}={value}\n")


def publication_destination(
    repository: str, record: dict[str, Any], access: str, client: GitHubClient
) -> tuple[str, bool]:
    """Fail closed before reading evidence or rendering a nonpublic repository."""
    visibility = record.get("visibility")
    if not isinstance(visibility, str) or visibility not in {"public", "private", "internal"}:
        raise ValueError("repository visibility is unknown; keep reports in Actions")
    if access not in {"", "public", "private"}:
        raise ValueError("Pages access must be public or private")
    if visibility != "public" and access != "private":
        raise ValueError(
            "nonpublic repositories require PAGES_ACCESS=private and a private Pages site; "
            "keep reports in Actions until configured"
        )
    if access != "private":
        return pages_base_url(repository), False
    pages = client.json(f"https://api.github.com/repos/{repository}/pages")
    if not isinstance(pages, dict) or pages.get("public") is not False:
        raise ValueError("Pages is not verified private; refusing publication")
    url = pages.get("html_url")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (
        parsed is None or parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.query or parsed.fragment
        or any(character.isspace() for character in url)
    ):
        raise ValueError("private Pages URL is invalid")
    return url.rstrip("/") + "/", True


def reconcile(
    repository: str,
    token: str,
    repository_root: Path,
    renderer: Path,
    output_dir: Path,
    *,
    pages_access: str = "",
    client: GitHubClient | None = None,
    published_loader: Callable[[str], dict[str, Any] | None] = read_published_scorecard,
) -> tuple[dict[str, Any] | None, list[str], bool]:
    repository = _repository(repository)
    client = client or GitHubClient(token)
    repo_record = client.json(f"https://api.github.com/repos/{repository}")
    if not isinstance(repo_record, dict) or not isinstance(
        repo_record.get("default_branch"), str
    ):
        raise ValueError("repository API response does not identify a default branch")
    default_branch = repo_record["default_branch"]
    base_url, private_pages = publication_destination(repository, repo_record, pages_access, client)
    # Private Pages requires interactive authentication. Never send the API token
    # to a Pages host or probe the public github.io fallback for private reports.
    published = None if private_pages else validate_published_scorecard(
        published_loader(f"{base_url}scorecard.json"), repository
    )
    current = published_tuple(published)
    runs = completed_runs(client, repository)

    def validate(candidate: dict[str, Any]) -> dict[str, Any]:
        def candidate_value(operation: Callable[[], Any]) -> Any:
            try:
                return operation()
            except (KeyError, ValueError, subprocess.SubprocessError) as error:
                raise CandidateRejected(str(error)) from error

        normalized_run = candidate_value(
            lambda: validate_run(candidate, repository, default_branch)
        )
        try:
            listing = client.json(
                f"https://api.github.com/repos/{repository}/actions/runs/{normalized_run['id']}/artifacts?per_page=100"
            )
        except HTTPError as error:
            if error.code == 404:
                raise CandidateRejected(
                    "source run artifact listing is unavailable"
                ) from error
            raise
        artifact = exact_artifact(listing, normalized_run)
        try:
            payload = client.artifact(repository, artifact["id"])
        except HTTPError as error:
            if error.code == 404:
                raise CandidateRejected("source run artifact is unavailable") from error
            raise
        except ArtifactRejected as error:
            raise CandidateRejected(str(error)) from error
        with tempfile.TemporaryDirectory(prefix="proof-scorecard-") as directory:
            root = Path(directory)
            extracted = candidate_value(
                lambda: extract_artifact(payload, root / "artifact")
            )
            scorecard_source = root / "scorecard"
            scorecard_source.mkdir()
            for path in extracted.glob("scorecard-*"):
                (scorecard_source / path.name).write_bytes(path.read_bytes())
            inspection_path = root / "inspection.json"
            _run_renderer(
                [
                    sys.executable,
                    str(renderer),
                    "--source-dir",
                    str(scorecard_source),
                    "--inspect-output",
                    str(inspection_path),
                ]
            )
            try:
                inspected = _load_object(inspection_path, "scorecard inspection")
            except ValueError as error:
                raise TrustedRuntimeError(str(error)) from error
            source = candidate_value(
                lambda: _load_object(extracted / "source.json", "source binding")
            )
            pull_number = candidate_value(
                lambda: _integer(
                    source.get("pull_request_number"),
                    "source.pull_request_number",
                    positive=True,
                )
            )
            try:
                pull_request = client.json(
                    f"https://api.github.com/repos/{repository}/pulls/{pull_number}"
                )
            except HTTPError as error:
                if error.code == 404:
                    raise CandidateRejected(
                        "bound pull request is unavailable"
                    ) from error
                raise
            pull_request = validate_pull_request_response(pull_request)

            def ancestor(revision: str) -> bool:
                completed = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", revision, "HEAD"],
                    cwd=repository_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if completed.returncode not in {0, 1}:
                    raise OSError(
                        "could not verify source base ancestry: "
                        + (completed.stdout + completed.stderr).strip()
                    )
                return completed.returncode == 0

            revision = inspected.get("subject_revision")
            if not isinstance(revision, str):
                raise CandidateRejected(
                    "scorecard inspection did not return a revision"
                )
            candidate_value(
                lambda: validate_source_binding(
                    source,
                    normalized_run,
                    pull_request,
                    repository,
                    default_branch,
                    revision,
                    ancestor,
                )
            )
            if normalized_run["conclusion"] == "success":
                if (
                    inspected.get("decision") != "allow"
                    or inspected.get("status") == "RED"
                ):
                    raise CandidateRejected(
                        "successful source run must contain an allow scorecard"
                    )
            elif (
                inspected.get("decision") != "block" or inspected.get("status") != "RED"
            ):
                raise CandidateRejected(
                    "failed source run must contain a RED block scorecard"
                )
            run_url = (
                f"https://github.com/{repository}/actions/runs/{normalized_run['id']}"
                f"/attempts/{normalized_run['run_attempt']}"
            )
            _run_renderer(
                [
                    sys.executable,
                    str(renderer),
                    "--source-dir",
                    str(scorecard_source),
                    "--output-dir",
                    str(output_dir),
                    "--repository",
                    repository,
                    "--run-id",
                    str(normalized_run["id"]),
                    "--run-attempt",
                    str(normalized_run["run_attempt"]),
                    "--run-url",
                    run_url,
                    "--source-run-created-at",
                    normalized_run["created_at"],
                    "--expected-revision",
                    revision,
                ]
            )
            return {
                "run": normalized_run,
                "run_url": run_url,
                "pages_url": base_url,
                "output_dir": str(output_dir),
            }

    try:
        selected, rejected = select_candidate(runs, current, validate, allow_fallback=not private_pages)
    except StalePublication as error:
        return None, [str(error)], False
    candidate_tuple = run_tuple(selected["run"])
    publish = current is None or candidate_tuple >= current
    return selected, rejected, publish


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument(
        "--token", default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    )
    parser.add_argument("--pages-access", default=os.environ.get("PROOF_SCORECARD_BADGE_PAGES_ACCESS", ""))
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument(
        "--renderer", type=Path, default=Path(".proof/render_scorecard_badge.py")
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--github-output", required=True, type=Path)
    parser.add_argument("--job-summary", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if not args.token:
            raise ValueError("GitHub token is required")
        selected, rejected, publish = reconcile(
            args.repository,
            args.token,
            args.repository_root.resolve(),
            args.renderer.resolve(),
            args.output_dir.resolve(),
            pages_access=args.pages_access,
        )
        values = {"publish": "true" if publish else "false"}
        lines = ["## Latest PR scorecard reconciliation", ""]
        if selected is not None:
            source = selected["run"]
            values.update(
                {
                    "source_run_id": str(source["id"]),
                    "source_run_attempt": str(source["run_attempt"]),
                    "source_run_url": selected["run_url"],
                    "pages_url": selected["pages_url"],
                    "output_dir": selected["output_dir"],
                }
            )
            lines.extend(
                [
                    f"- Result: {'deploy' if publish else 'stale; no deployment'}",
                    f"- Pages: {selected['pages_url']}",
                    f"- Source: {selected['run_url']}",
                ]
            )
        else:
            lines.append("- Result: stale; no deployment")
        if rejected:
            lines.extend(
                ["", "### Rejected candidates", "", *[f"- {item}" for item in rejected]]
            )
        _write_output(args.github_output, values)
        with args.job_summary.open("a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        return 0
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        HTTPError,
        URLError,
        subprocess.SubprocessError,
        TrustedRuntimeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
