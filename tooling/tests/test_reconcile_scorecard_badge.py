from __future__ import annotations

import importlib.util
from http.client import IncompleteRead
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tooling" / "reconcile_scorecard_badge.py"
SPEC = importlib.util.spec_from_file_location("reconcile_scorecard_badge", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise AssertionError(f"cannot load module spec: {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


REPOSITORY = "owner/repo"
DEFAULT_BRANCH = "main"
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40


def run(run_id: int = 123, attempt: int = 2, **overrides: Any) -> dict[str, Any]:
    value = {
        "id": run_id,
        "run_attempt": attempt,
        "name": "Proof Scorecard",
        "path": ".github/workflows/proof-scorecard.yml@refs/heads/main",
        "event": "pull_request_target",
        "conclusion": "success",
        "created_at": "2026-09-08T12:00:00Z",
        "repository": {"full_name": REPOSITORY},
    }
    value.update(overrides)
    return value


def source_binding(**overrides: Any) -> dict[str, Any]:
    value = {
        "version": 1,
        "run_id": 123,
        "run_attempt": 2,
        "event": "pull_request_target",
        "repository": REPOSITORY,
        "pull_request_number": 7,
        "head_sha": HEAD_SHA,
        "base_repository": REPOSITORY,
        "base_branch": DEFAULT_BRANCH,
        "base_sha": BASE_SHA,
    }
    value.update(overrides)
    return value


def pull_request(**overrides: Any) -> dict[str, Any]:
    value = {
        "number": 7,
        "head": {"sha": HEAD_SHA},
        "base": {"ref": DEFAULT_BRANCH, "repo": {"full_name": REPOSITORY}},
    }
    value.update(overrides)
    return value


def archive(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w") as output:
            for name, content, mode in entries:
                info = zipfile.ZipInfo(name)
                if mode is not None:
                    info.external_attr = mode << 16
                output.writestr(info, content)
    return stream.getvalue()


def valid_archive(
    *, binding: dict[str, Any] | None = None, revision: str = HEAD_SHA
) -> bytes:
    card = {
        "version": 2,
        "operation": "change",
        "status": "GREEN",
        "decision": "allow",
        "subject": {"type": "git-commit", "revision": revision},
        "enforced": {"passed": 2, "total": 2},
        "advisory": {"passed": 1, "total": 1},
    }
    return archive(
        [
            (
                "scorecard-20260908-120000Z.json",
                json.dumps(card).encode(),
                stat.S_IFREG | 0o644,
            ),
            ("scorecard-20260908-120000Z.md", b"report", stat.S_IFREG | 0o644),
            (
                "source.json",
                json.dumps(binding or source_binding()).encode(),
                stat.S_IFREG | 0o644,
            ),
        ]
    )


class ReconcilerTests(unittest.TestCase):
    def test_workflow_path_allowlist_is_exact(self) -> None:
        accepted = (
            ".github/workflows/proof-scorecard.yml",
            ".github/workflows/proof-scorecard.yml@main",
            ".github/workflows/proof-scorecard.yml@refs/heads/main",
        )
        for value in accepted:
            self.assertTrue(MODULE.workflow_path_allowed(value, DEFAULT_BRANCH))
        for value in (
            ".github/workflows/proof-scorecard.yml@feature",
            ".github/workflows/proof-scorecard.yml@refs/pull/7/merge",
            ".github/workflows/proof-scorecard.yml@refs/heads/main/evil",
            ".github/workflows/other.yml",
            None,
        ):
            self.assertFalse(MODULE.workflow_path_allowed(value, DEFAULT_BRANCH))

    def test_run_and_source_binding_require_exact_current_pr_state(self) -> None:
        normalized = MODULE.validate_run(run(), REPOSITORY, DEFAULT_BRANCH)
        MODULE.validate_source_binding(
            source_binding(),
            normalized,
            pull_request(),
            REPOSITORY,
            DEFAULT_BRANCH,
            HEAD_SHA,
            lambda revision: revision == BASE_SHA,
        )
        invalid_runs = (
            run(name="Other"),
            run(path=".github/workflows/proof-scorecard.yml@feature"),
            run(event="push"),
            run(conclusion="cancelled"),
            run(repository={"full_name": "other/repo"}),
            run(run_attempt=True),
        )
        for invalid in invalid_runs:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.validate_run(invalid, REPOSITORY, DEFAULT_BRANCH)
        invalid_sources = (
            source_binding(run_attempt=1),
            source_binding(repository="other/repo"),
            source_binding(head_sha="c" * 40),
            source_binding(base_repository="other/repo"),
            source_binding(base_branch="develop"),
            source_binding(base_sha="short"),
        )
        for invalid in invalid_sources:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.validate_source_binding(
                    invalid,
                    normalized,
                    pull_request(),
                    REPOSITORY,
                    DEFAULT_BRANCH,
                    HEAD_SHA,
                    lambda _: True,
                )

    def test_archive_extraction_is_bounded_and_attempt_specific(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            extracted = MODULE.extract_artifact(valid_archive(), Path(directory))
            self.assertEqual(
                {path.name for path in extracted.iterdir()},
                {
                    "scorecard-20260908-120000Z.json",
                    "scorecard-20260908-120000Z.md",
                    "source.json",
                },
            )
        unsafe_archives = (
            archive([("../source.json", b"{}", stat.S_IFREG | 0o644)]),
            archive([("nested/source.json", b"{}", stat.S_IFREG | 0o644)]),
            archive([("source.json", b"{}", stat.S_IFLNK | 0o777)]),
            archive(
                [
                    (
                        "source.json",
                        b"x" * (MODULE.MAX_MEMBER_BYTES + 1),
                        stat.S_IFREG | 0o644,
                    )
                ]
            ),
            archive(
                [
                    ("source.json", b"{}", stat.S_IFREG | 0o644),
                    ("source.json", b"{}", stat.S_IFREG | 0o644),
                ]
            ),
        )
        for payload in unsafe_archives:
            with (
                self.subTest(size=len(payload)),
                tempfile.TemporaryDirectory() as directory,
            ):
                with self.assertRaises(ValueError):
                    MODULE.extract_artifact(payload, Path(directory))

    def test_artifact_download_drops_authorization_after_redirect(self) -> None:
        requests = []

        class RedirectingOpener:
            def open(self, request: Any, timeout: int) -> None:
                requests.append(request)
                raise HTTPError(
                    request.full_url,
                    302,
                    "Found",
                    {"Location": "https://signed.example/archive.zip"},
                    None,
                )

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def read(self, amount: int) -> bytes:
                return b"zip"

        def unsigned_open(request: Any, timeout: int) -> Response:
            requests.append(request)
            return Response()

        payload = MODULE.download_artifact(
            "https://api.github.com/repos/owner/repo/actions/artifacts/9/zip",
            "secret-token",
            opener=RedirectingOpener(),
            unsigned_open=unsigned_open,
        )
        self.assertEqual(payload, b"zip")
        self.assertIn("Authorization", requests[0].headers)
        self.assertNotIn("Authorization", requests[1].headers)
        self.assertEqual(requests[1].full_url, "https://signed.example/archive.zip")

    def test_artifact_download_treats_missing_redirect_as_api_failure(self) -> None:
        class NonRedirectingOpener:
            def open(self, request: Any, timeout: int) -> None:
                return None

        with self.assertRaises(MODULE.APIResponseError):
            MODULE.download_artifact(
                "https://api.github.com/repos/owner/repo/actions/artifacts/9/zip",
                "secret-token",
                opener=NonRedirectingOpener(),
            )

    def test_candidate_selection_crosses_more_than_twenty_rejections(self) -> None:
        runs = [run(run_id=200 - index, attempt=1) for index in range(25)]
        runs.append(run(run_id=175, attempt=3, created_at="2026-09-07T12:00:00Z"))

        def validate(candidate: dict[str, Any]) -> dict[str, Any]:
            if candidate["id"] != 175:
                raise MODULE.CandidateRejected("missing or malformed artifact")
            return {"run": candidate}

        selected, rejected = MODULE.select_candidate(runs, None, validate)
        self.assertEqual(selected["run"]["id"], 175)
        self.assertEqual(len(rejected), 25)

    def test_candidate_selection_is_monotonic_and_attempt_aware(self) -> None:
        published = ("2026-09-08T12:00:00Z", 123, 2)
        same_attempt = run()
        older_attempt = run(attempt=1)
        selected, _ = MODULE.select_candidate(
            [same_attempt, older_attempt],
            published,
            lambda candidate: {"run": candidate},
        )
        self.assertEqual(selected["run"]["run_attempt"], 2)
        with self.assertRaises(ValueError):
            MODULE.select_candidate(
                [older_attempt], published, lambda candidate: {"run": candidate}
            )
        with self.assertRaisesRegex(ValueError, "not ordered newest-first"):
            MODULE.select_candidate(
                [older_attempt, run(created_at="2026-09-09T12:00:00Z")],
                None,
                lambda _: (_ for _ in ()).throw(MODULE.CandidateRejected("bad")),
            )
        with self.assertRaisesRegex(ValueError, "no valid completed"):
            MODULE.select_candidate([], None, lambda candidate: {"run": candidate})

    def test_published_scorecard_metadata_is_validated_before_use(self) -> None:
        document = {
            "version": 1,
            "operation": "change",
            "repository": REPOSITORY,
            "status": "GREEN",
            "decision": "allow",
            "passed": 3,
            "total": 3,
            "enforced": {"passed": 2, "total": 2},
            "advisory": {"passed": 1, "total": 1},
            "subject_digest": "sha256:" + "c" * 64,
            "source_run_created_at": "2026-09-08T12:00:00Z",
            "source_run_id": 123,
            "source_run_attempt": 2,
        }
        self.assertEqual(
            MODULE.validate_published_scorecard(document, REPOSITORY), document
        )
        for field, value in (
            ("version", 2),
            ("repository", "other/repo"),
            ("status", []),
            ("passed", True),
            ("total", 0),
            ("advisory", {"passed": 0, "total": 1}),
            ("subject_digest", HEAD_SHA),
        ):
            invalid = {**document, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                MODULE.validate_published_scorecard(invalid, REPOSITORY)

        for invalid in (
            {**document, "passed": 4},
            {**document, "enforced": []},
            {**document, "enforced": {"passed": 3, "total": 2}},
            {**document, "status": "ORANGE"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                MODULE.validate_published_scorecard(invalid, REPOSITORY)

    def test_completed_run_pagination_is_lazy_and_crosses_a_full_page(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.pages: list[int] = []

            def json(self, url: str) -> dict[str, Any]:
                page = int(url.rsplit("page=", 1)[1])
                self.pages.append(page)
                if page == 1:
                    return {
                        "workflow_runs": [
                            run(run_id=300 - index, attempt=1)
                            for index in range(MODULE.RUNS_PER_PAGE)
                        ]
                    }
                return {"workflow_runs": [run(run_id=200, attempt=1)]}

        client = Client()
        candidates = MODULE.completed_runs(client, REPOSITORY)

        selected, rejected = MODULE.select_candidate(
            candidates,
            None,
            lambda candidate: (
                {"run": candidate}
                if candidate["id"] == 200
                else (_ for _ in ()).throw(MODULE.CandidateRejected("rejected"))
            ),
        )

        self.assertEqual(selected["run"]["id"], 200)
        self.assertEqual(len(rejected), MODULE.RUNS_PER_PAGE)
        self.assertEqual(client.pages, [1, 2])

    def test_api_failures_are_not_downgraded_to_rejected_candidates(self) -> None:
        failure = HTTPError("https://api.github.com", 500, "error", {}, None)
        with self.assertRaises(HTTPError):
            MODULE.select_candidate(
                [run()], None, lambda _: (_ for _ in ()).throw(failure)
            )

    def test_reconcile_falls_back_from_invalid_newest_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository_root = root / "repository"
            repository_root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository_root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repository_root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repository_root,
                check=True,
            )
            (repository_root / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository_root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "fixture"], cwd=repository_root, check=True
            )
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository_root,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            newest = run(run_id=200, attempt=1, created_at="2026-09-08T13:00:00Z")
            fallback = run(run_id=199, attempt=1, created_at="2026-09-08T12:00:00Z")
            binding = source_binding(
                run_id=199,
                run_attempt=1,
                head_sha=revision,
                base_sha=revision,
            )

            class Client:
                def json(self, url: str) -> Any:
                    if url == "https://api.github.com/repos/owner/repo":
                        return {"default_branch": DEFAULT_BRANCH, "visibility": "public"}
                    if "/actions/workflows/" in url:
                        return {"workflow_runs": [newest, fallback]}
                    if "/actions/runs/200/artifacts" in url:
                        return {
                            "total_count": 1,
                            "artifacts": [
                                {
                                    "id": 20,
                                    "name": "proof-scorecard-200-1",
                                    "expired": False,
                                }
                            ],
                        }
                    if "/actions/runs/199/artifacts" in url:
                        return {
                            "total_count": 1,
                            "artifacts": [
                                {
                                    "id": 19,
                                    "name": "proof-scorecard-199-1",
                                    "expired": False,
                                }
                            ],
                        }
                    if url.endswith("/pulls/7"):
                        return pull_request(head={"sha": revision})
                    raise AssertionError(url)

                def artifact(self, repository: str, artifact_id: int) -> bytes:
                    if repository != REPOSITORY:
                        raise AssertionError(repository)
                    if artifact_id == 20:
                        raise MODULE.ArtifactRejected(
                            "artifact archive exceeds the compressed size limit"
                        )
                    return valid_archive(binding=binding, revision=revision)

            output = root / "site"
            selected, rejected, publish = MODULE.reconcile(
                REPOSITORY,
                "token",
                repository_root,
                ROOT / "tooling" / "render_scorecard_badge.py",
                output,
                client=Client(),
                published_loader=lambda _: None,
            )

            self.assertTrue(publish)
            self.assertEqual(selected["run"]["id"], 199)
            self.assertEqual(len(rejected), 1)
            published = json.loads((output / "scorecard.json").read_text())
            self.assertEqual(published["source_run_id"], 199)

            class PrivateClient(Client):
                def json(self, url: str) -> Any:
                    if url == "https://api.github.com/repos/owner/repo":
                        return {"default_branch": DEFAULT_BRANCH, "visibility": "private"}
                    if url.endswith("/pages"):
                        return {"public": False, "html_url": "https://private.pages.github.io/"}
                    if "/actions/workflows/" in url:
                        return {"workflow_runs": [fallback]}
                    return super().json(url)

            loader = mock.Mock(side_effect=AssertionError("private Pages must not be fetched"))
            private_output = root / "private-site"
            selected, rejected, publish = MODULE.reconcile(
                REPOSITORY, "token", repository_root,
                ROOT / "tooling" / "render_scorecard_badge.py", private_output,
                pages_access="private", client=PrivateClient(), published_loader=loader,
            )
            self.assertTrue(publish)
            self.assertEqual(selected["pages_url"], "https://private.pages.github.io/")
            self.assertEqual(selected["run"]["id"], 199)
            self.assertEqual(rejected, [])
            self.assertTrue((private_output / "index.html").is_file())
            loader.assert_not_called()

    def test_reconcile_propagates_malformed_api_state_without_output(self) -> None:
        class Client:
            def json(self, url: str) -> Any:
                if url == "https://api.github.com/repos/owner/repo":
                    return {"default_branch": DEFAULT_BRANCH, "visibility": "public"}
                if "/actions/workflows/" in url:
                    return {"workflow_runs": [run()]}
                if "/artifacts" in url:
                    return {"unexpected": []}
                raise AssertionError(url)

            def artifact(self, repository: str, artifact_id: int) -> bytes:
                raise AssertionError("artifact download must not be reached")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "site"
            with self.assertRaises(MODULE.APIResponseError):
                MODULE.reconcile(
                    REPOSITORY,
                    "token",
                    root,
                    ROOT / "tooling" / "render_scorecard_badge.py",
                    output,
                    client=Client(),
                    published_loader=lambda _: None,
                )
            self.assertFalse(output.exists())

    def test_reconcile_propagates_artifact_api_failure_without_output(self) -> None:
        class Client:
            def json(self, url: str) -> Any:
                if url == "https://api.github.com/repos/owner/repo":
                    return {"default_branch": DEFAULT_BRANCH, "visibility": "public"}
                if "/actions/workflows/" in url:
                    return {"workflow_runs": [run()]}
                if "/artifacts" in url:
                    return {
                        "total_count": 1,
                        "artifacts": [
                            {
                                "id": 9,
                                "name": "proof-scorecard-123-2",
                                "expired": False,
                            }
                        ],
                    }
                raise AssertionError(url)

            def artifact(self, repository: str, artifact_id: int) -> bytes:
                raise MODULE.APIResponseError("artifact redirect is missing")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "site"
            with self.assertRaises(MODULE.APIResponseError):
                MODULE.reconcile(
                    REPOSITORY,
                    "token",
                    root,
                    ROOT / "tooling" / "render_scorecard_badge.py",
                    output,
                    client=Client(),
                    published_loader=lambda _: None,
                )
            self.assertFalse(output.exists())

    def test_renderer_runtime_failure_is_not_a_candidate_rejection(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["python", "renderer.py"],
            returncode=3,
            stdout="",
            stderr="ERROR runtime: disk unavailable\n",
        )
        with (
            mock.patch.object(MODULE.subprocess, "run", return_value=completed),
            self.assertRaises(MODULE.TrustedRuntimeError),
        ):
            MODULE._run_renderer(["python", "renderer.py"])

    def test_validation_rejects_malformed_run_published_and_source_records(self) -> None:
        normalized = MODULE.validate_run(run(), REPOSITORY, DEFAULT_BRANCH)
        invalid_sources = (
            {},
            source_binding(version=2),
            source_binding(run_id=999),
            source_binding(event="pull_request"),
            source_binding(pull_request_number=8),
            source_binding(head_sha="short"),
            source_binding(base_sha="c" * 40),
        )
        for source in invalid_sources:
            with self.subTest(source=source), self.assertRaises(ValueError):
                MODULE.validate_source_binding(
                    source,
                    normalized,
                    pull_request(),
                    REPOSITORY,
                    DEFAULT_BRANCH,
                    HEAD_SHA,
                    lambda revision: revision == BASE_SHA,
                )
        with self.assertRaises(ValueError):
            MODULE.validate_source_binding(
                source_binding(),
                normalized,
                {"number": 7, "base": None, "head": None},
                REPOSITORY,
                DEFAULT_BRANCH,
                HEAD_SHA,
                lambda _: True,
            )
        with self.assertRaises(ValueError):
            MODULE.validate_run([], REPOSITORY, DEFAULT_BRANCH)
        with self.assertRaises(ValueError):
            MODULE.published_tuple([])
        with self.assertRaises(ValueError):
            MODULE.validate_published_scorecard([], REPOSITORY)
        with self.assertRaises(MODULE.APIResponseError):
            MODULE.validate_pull_request_response([])
        with self.assertRaises(MODULE.APIResponseError):
            MODULE.validate_pull_request_response({"number": 7})
        self.assertEqual(
            MODULE.pages_base_url("owner/owner.github.io"),
            "https://owner.github.io/",
        )
        with self.assertRaises(ValueError):
            MODULE.pages_base_url("not-a-repository")

    def test_artifact_download_rejects_protocol_and_size_failures(self) -> None:
        with self.assertRaises(MODULE.APIResponseError):
            MODULE.download_artifact("https://example.com/archive", "token")

        class ErrorOpener:
            def __init__(self, status: int, location: str | None = None) -> None:
                self.status = status
                self.location = location

            def open(self, request: Any, timeout: int) -> None:
                headers = {"Location": self.location} if self.location else {}
                raise HTTPError(request.full_url, self.status, "error", headers, None)

        with self.assertRaises(HTTPError):
            MODULE.download_artifact(
                "https://api.github.com/repos/owner/repo/actions/artifacts/9/zip",
                "token",
                opener=ErrorOpener(500),
            )
        for location in (None, "http://signed.example/archive.zip", "https://u:p@signed.example/archive.zip"):
            with self.subTest(location=location), self.assertRaises(
                MODULE.APIResponseError
            ):
                MODULE.download_artifact(
                    "https://api.github.com/repos/owner/repo/actions/artifacts/9/zip",
                    "token",
                    opener=ErrorOpener(302, location),
                )

        class OversizedResponse:
            def __enter__(self) -> "OversizedResponse":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def read(self, amount: int) -> bytes:
                return b"x" * amount

        with self.assertRaises(MODULE.ArtifactRejected):
            MODULE.download_artifact(
                "https://api.github.com/repos/owner/repo/actions/artifacts/9/zip",
                "token",
                opener=ErrorOpener(302, "https://signed.example/archive.zip"),
                unsigned_open=lambda request, timeout: OversizedResponse(),
            )

    def test_helpers_reject_malformed_pages_files_and_output_values(self) -> None:
        class Client:
            def __init__(self, payload: Any) -> None:
                self.payload = payload

            def json(self, url: str) -> Any:
                return self.payload

        for payload in ({}, {"workflow_runs": [None]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                list(MODULE.completed_runs(Client(payload), REPOSITORY))
        with self.assertRaises(MODULE.APIResponseError):
            MODULE.exact_artifact([], run())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE._load_object(malformed, "fixture")
            scalar = root / "scalar.json"
            scalar.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE._load_object(scalar, "fixture")
            with self.assertRaises(ValueError):
                MODULE._write_output(root / "github-output", {"bad": "line\nbreak"})

    def test_cli_writes_selected_and_stale_reconciliation_summaries(self) -> None:
        selected = {
            "run": run(),
            "run_url": "https://github.com/owner/repo/actions/runs/123/attempts/2",
            "pages_url": "https://owner.github.io/repo/",
            "output_dir": "/tmp/site",
        }
        cases = (
            ((selected, ["older candidate rejected"], True), "publish=true", "Result: deploy"),
            ((None, ["already published"], False), "publish=false", "Result: stale"),
        )
        for index, (result, expected_output, expected_summary) in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                github_output = root / "github-output"
                summary = root / "summary.md"
                argv = [
                    str(SCRIPT),
                    "--repository",
                    REPOSITORY,
                    "--token",
                    "token",
                    "--output-dir",
                    str(root / "site"),
                    "--github-output",
                    str(github_output),
                    "--job-summary",
                    str(summary),
                ]
                with (
                    mock.patch.object(sys, "argv", argv),
                    mock.patch.object(MODULE, "reconcile", return_value=result),
                ):
                    self.assertEqual(MODULE.main(), 0)
                self.assertIn(expected_output, github_output.read_text())
                self.assertIn(expected_summary, summary.read_text())
                self.assertIn(result[1][0], summary.read_text())
                if result[0] is not None:
                    self.assertIn(selected["run_url"], github_output.read_text())
                    self.assertIn(selected["pages_url"], summary.read_text())
                    self.assertIn(selected["run_url"], summary.read_text())

    def test_private_selection_refuses_older_fallback(self) -> None:
        validate = mock.Mock(side_effect=[MODULE.CandidateRejected("stale head"), {"run": run(100)}])
        with self.assertRaisesRegex(ValueError, "cannot fall back.*stale head"):
            MODULE.select_candidate([run(200), run(100)], None, validate, allow_fallback=False)
        self.assertEqual(validate.call_count, 1)

    def test_private_pages_rejects_invalid_url_and_api_failure(self) -> None:
        client = mock.Mock()
        for url in (None, "http://example.com/", "https://user:pass@example.com/", "https://example.com/?token=x", "https://example.com/\n"):
            with self.subTest(url=url):
                client.json.return_value = {"public": False, "html_url": url}
                with self.assertRaises(ValueError):
                    MODULE.publication_destination(REPOSITORY, {"visibility": "private"}, "private", client)
        client.json.side_effect = HTTPError("https://api.github.com/", 404, "missing", {}, None)
        with self.assertRaises(HTTPError):
            MODULE.publication_destination(REPOSITORY, {"visibility": "private"}, "private", client)

    def test_publication_access_matrix(self) -> None:
        for visibility in ("public", "private", "internal", None, "unexpected"):
            for access in ("", "public", "private", "invalid"):
                for public in (True, False, None, "false", 0):
                    with self.subTest(visibility=visibility, access=access, public=public):
                        client = mock.Mock()
                        client.json.return_value = {"public": public, "html_url": "https://private.pages.github.io/"}
                        allowed = visibility in {"public", "private", "internal"} and (
                            (visibility == "public" and access in {"", "public"})
                            or (access == "private" and public is False)
                        )
                        if allowed:
                            url, private = MODULE.publication_destination(REPOSITORY, {"visibility": visibility}, access, client)
                            self.assertEqual(private, access == "private")
                            self.assertTrue(url.startswith("https://"))
                        else:
                            with self.assertRaises(ValueError):
                                MODULE.publication_destination(REPOSITORY, {"visibility": visibility}, access, client)

    def test_nonpublic_reconcile_blocks_before_evidence_or_public_fetch(self) -> None:
        client = mock.Mock()
        client.json.return_value = {"default_branch": "main", "visibility": "private"}
        loader = mock.Mock()
        with self.assertRaisesRegex(ValueError, "nonpublic"):
            MODULE.reconcile(REPOSITORY, "token", ROOT, SCRIPT, ROOT / "unused",
                             client=client, published_loader=loader)
        self.assertEqual(client.json.call_count, 1)
        loader.assert_not_called()

    def test_private_reconcile_never_fetches_public_site(self) -> None:
        client = mock.Mock()
        client.json.side_effect = [
            {"default_branch": "main", "visibility": "private"},
            {"public": False, "html_url": "https://private.pages.github.io/"},
        ]
        loader = mock.Mock()
        with mock.patch.object(MODULE, "select_candidate", side_effect=MODULE.StalePublication("no candidates")):
            result = MODULE.reconcile(REPOSITORY, "token", ROOT, SCRIPT, ROOT / "unused",
                                      pages_access="private", client=client, published_loader=loader)
        self.assertFalse(result[2])
        loader.assert_not_called()

    def test_cli_normalizes_missing_token_to_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = [
                str(SCRIPT),
                "--repository",
                REPOSITORY,
                "--output-dir",
                str(root / "site"),
                "--github-output",
                str(root / "github-output"),
                "--job-summary",
                str(root / "summary.md"),
            ]
            with (
                mock.patch.object(sys, "argv", argv),
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch("builtins.print") as output,
            ):
                self.assertEqual(MODULE.main(), 2)
            output.assert_called_once_with(
                "ERROR: GitHub token is required", file=sys.stderr
            )

    def test_artifact_name_is_exact_for_run_attempt(self) -> None:
        listing = {
            "total_count": 3,
            "artifacts": [
                {"id": 1, "name": "proof-scorecard-123-1", "expired": False},
                {"id": 2, "name": "proof-scorecard-123-2", "expired": False},
                {"id": 3, "name": "proof-scorecard-123-2-extra", "expired": False},
            ],
        }
        self.assertEqual(MODULE.exact_artifact(listing, run())["id"], 2)
        duplicate = {
            **listing,
            "artifacts": [
                *listing["artifacts"],
                {"id": 4, "name": "proof-scorecard-123-2", "expired": False},
            ],
        }
        with self.assertRaises(ValueError):
            MODULE.exact_artifact(duplicate, run())
        with self.assertRaises(MODULE.CandidateRejected):
            MODULE.exact_artifact({"total_count": 0, "artifacts": []}, run())
        with self.assertRaises(ValueError):
            MODULE.GitHubClient("")


class HttpDiagnosticsTests(unittest.TestCase):
    def test_api_failure_reports_safe_rate_context_and_preserves_exception(self):
        failure = HTTPError("https://api.github.com/repos/owner/repo?token=secret", 403, "secret reason",
                            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1234567890",
                             "X-GitHub-Request-Id": "ABCD:1234", "Authorization": "secret"},
                            io.BytesIO(b'{"message":"API rate limit exceeded for secret"}'))
        self.addCleanup(failure.close)
        with mock.patch.object(MODULE, "urlopen", side_effect=failure) as request, self.assertRaises(HTTPError) as caught:
            MODULE.GitHubClient("secret-token").json(failure.url)
        request.assert_called_once()
        self.assertIs(caught.exception, failure)
        message = str(failure)
        for expected in ("403", "repository metadata", "primary-rate-limit", "ABCD:1234", "1234567890"):
            self.assertIn(expected, message)
        self.assertNotIn("secret", message)

    def test_known_messages_classify_without_logging_arbitrary_body(self):
        cases = ((403, "You have exceeded a secondary rate limit.", "secondary-rate-limit"),
                 (403, "Resource not accessible by integration", "permission-denied"),
                 (401, "Bad credentials", "authentication-failed"),
                 (403, "private candidate payload", "forbidden-unknown"),
                 (404, "Not Found", "not-found"))
        for code, body, classification in cases:
            with self.subTest(code=code, classification=classification):
                failure = HTTPError("https://api.github.com/repos/o/r/pages", code, body,
                                    {"X-GitHub-Request-Id": "bad\nheader", "Retry-After": "20"},
                                    io.BytesIO(json.dumps({"message": body}).encode()))
                self.addCleanup(failure.close)
                with mock.patch.object(MODULE, "urlopen", side_effect=failure), self.assertRaises(HTTPError) as caught:
                    MODULE.GitHubClient("token").json(failure.url)
                self.assertIs(caught.exception, failure)
                self.assertIn(classification, str(failure))
                self.assertIn("retry-after=20", str(failure))
                self.assertNotIn(body, str(failure))
                self.assertNotIn("bad", str(failure))

    def test_incomplete_error_body_preserves_original_404(self):
        body = mock.Mock()
        body.read.side_effect = IncompleteRead(b"secret partial response", 100)
        failure = HTTPError("https://api.github.com/repos/o/r/pulls/1?token=secret", 404,
                            "secret server reason", {"X-GitHub-Request-Id": "ABCD:5678"}, body)
        self.addCleanup(failure.close)
        with mock.patch.object(MODULE, "urlopen", side_effect=failure), self.assertRaises(HTTPError) as caught:
            MODULE.GitHubClient("secret").json(failure.url)
        self.assertIs(caught.exception, failure)
        self.assertEqual(caught.exception.code, 404)
        self.assertIn("pull request metadata; not-found; request-id=ABCD:5678", str(failure))
        self.assertNotIn("secret", str(failure))

    def test_operation_labels_and_malformed_response_are_safe(self):
        paths = {"": "repository metadata", "/pages": "Pages configuration",
                 "/actions/workflows/secret/runs": "completed scorecard runs",
                 "/actions/runs/secret/artifacts": "run artifact listing",
                 "/actions/artifacts/secret/zip": "artifact redirect", "/pulls/secret": "pull request metadata",
                 "/unknown/secret": "GitHub API request"}
        for suffix, expected in paths.items():
            self.assertEqual(MODULE.github_request_context("https://api.github.com/repos/secret/private" + suffix
                                                           + "?credential=secret"), expected)
        failure = HTTPError("https://api.github.com/secret", 503, "sensitive reason",
                            {"X-RateLimit-Remaining": "secret", "X-GitHub-Request-Id": "x" * 129},
                            io.BytesIO(b"not json secret"))
        self.addCleanup(failure.close)
        MODULE.describe_http_failure(failure, "GitHub API request")
        self.assertEqual(str(failure), "HTTP Error 503: GitHub API request; http-failure")

    def test_signed_artifact_failure_hides_url_and_limits_body_read(self):
        redirect = HTTPError("api", 302, "redirect", {"Location": "https://blob.example/a?sig=secret"}, None)
        self.addCleanup(redirect.close)
        opener = mock.Mock()
        opener.open.side_effect = redirect
        body = mock.Mock()
        body.read.return_value = b'x' * 4096
        failure = HTTPError("https://blob.example/a?sig=secret", 403, "secret", {}, body)
        self.addCleanup(failure.close)
        with self.assertRaises(HTTPError) as caught:
            MODULE.download_artifact("https://api.github.com/repos/o/r/actions/artifacts/1/zip", "token",
                                     opener=opener, unsigned_open=mock.Mock(side_effect=failure))
        self.assertIs(caught.exception, failure)
        self.assertIn("artifact download", str(failure))
        self.assertNotIn("secret", str(failure))
        body.read.assert_called_once_with(4096)


if __name__ == "__main__":
    unittest.main()
