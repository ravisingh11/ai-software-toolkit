# GitHub Actions workflows

Generate both files only after CI is requested. Fill placeholders and resolve
every action tag below to a reviewed full commit SHA. Preserve existing QA
workflows unless the user approved replacement.

The PR-editable workflow has read-only permissions throughout. Its `QA / report`
job is an advisory result check and always runs, including when execution was skipped.
Its PR-editable definition cannot enforce a tamper-resistant merge decision; do
not require it in branch protection or promote functional-qa to enforced.
The separate `workflow_run` reporter runs its definition from the default branch;
it never checks out or executes PR code. Its only inputs from QA are validated,
run-bound artifacts treated as untrusted data.

Both jobs load the result validator from the default branch. Publish the generated
scripts there before expecting a successful gate; the initial bootstrap PR may
fail for a missing validator. Keep the new check advisory until a subsequent
representative run validates the installed producer.

## `.github/workflows/qa.yml`: execution and advisory result

```yaml
name: QA
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      pr_number:
        description: PR number for an informational manual run
        required: true
      head_sha:
        description: Exact reviewed commit; this does not satisfy a fork-head check
        required: true
permissions: {}
concurrency:
  group: qa-${{ github.event_name }}-${{ github.event.pull_request.number || inputs.pr_number }}
  cancel-in-progress: true
env:
  PR_NUMBER: ${{ github.event.pull_request.number || inputs.pr_number }}
jobs:
  qa:
    name: QA execution
    # Unreviewed fork code receives no agent key or app credentials.
    if: github.event_name == 'workflow_dispatch' || github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    timeout-minutes: 25
    permissions:
      contents: read
      pull-requests: read
      deployments: read                   # omit unless polling previews
    outputs:
      execution_outcome: ${{ steps.qa.outcome }}
    steps:
      - name: Resolve and validate the PR revision
        id: pr
        env:
          GH_TOKEN: ${{ github.token }}
          REQUESTED_SHA: ${{ inputs.head_sha || github.event.pull_request.head.sha }}
        run: |
          [[ "$PR_NUMBER" =~ ^[0-9]+$ ]] || { echo "invalid PR number"; exit 1; }
          [[ "$REQUESTED_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "an exact commit SHA is required"; exit 1; }
          pr=$(gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json headRefOid,baseRefOid,state)
          [[ $(jq -r .state <<<"$pr") = OPEN ]] || exit 1
          [[ $(jq -r .headRefOid <<<"$pr") = "$REQUESTED_SHA" ]] || { echo "PR head changed; review the current revision"; exit 1; }
          echo "head_sha=$REQUESTED_SHA" >> "$GITHUB_OUTPUT"
          echo "base_sha=$(jq -r .baseRefOid <<<"$pr")" >> "$GITHUB_OUTPUT"

      - uses: actions/checkout@v4
        with:
          ref: ${{ steps.pr.outputs.head_sha }}
          fetch-depth: 0                   # full history, for the merge-base diff
          persist-credentials: false       # PR code must not inherit a git token

      # ── Preview URL (only if the user chose to wait for previews) ──────
      # <Poll the deployments API for the head SHA until the deployment from the
      #  expected creator succeeds; write QA_PREVIEW_URL to $GITHUB_ENV. On failure
      #  or timeout, leave it unset so web tests report BLOCKED. Trust only
      #  statuses/comments authored by the deploy bot.>

      # ── Toolchain ──────────────────────────────────────────────────────
      # <setup-node / setup-python etc. matching the project's version files>
      - name: Install project dependencies
        run: <install command>
      - name: QA Bootstrap tooling
        run: |
          # <browser automation tool + browser; ffmpeg if the tool needs it for video>
          # <terminal driver + asciinema, for CLI/TUI apps>
          # Install video prerequisites whenever an interactive app exists, so
          # toggling evidence.video in config.yaml needs no workflow change.
      - name: Install agent CLI
        run: <agent.install>               # no secrets in this step's environment

      # ── Run ────────────────────────────────────────────────────────────
      - name: Run QA
        id: qa
        timeout-minutes: 20
        env:
          CI: 'true'
          QA_RUN_ID: ${{ github.run_id }}-${{ github.run_attempt }}
          QA_DIFF_BASE: ${{ steps.pr.outputs.base_sha }}
          <AGENT_API_KEY_SECRET>: ${{ secrets.<AGENT_API_KEY_SECRET> }}
          # <one line per app test credential referenced in config.yaml>
        run: |
          set -o pipefail
          mkdir -p qa-results/evidence
          <agent.headless_command> "$(cat <skills-dir>/qa/ci-prompt.md)" 2>&1 | tee qa-results/agent-output.txt

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: qa-results-${{ github.run_attempt }}
          path: qa-results/
          retention-days: 14

  report:
    name: QA / report
    needs: qa
    if: always()
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      actions: read
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          path: trusted
          sparse-checkout: <skills-dir>/qa/scripts
          persist-credentials: false
      - uses: actions/download-artifact@v4
        continue-on-error: true
        with:
          name: qa-results-${{ github.run_attempt }}
          path: qa-results

      - name: Validate artifact paths
        run: |
          [ ! -L qa-results ] || { echo "artifact root must not be a symlink"; exit 1; }
          mkdir -p qa-results
          if find qa-results -type l -print -quit | grep -q .; then
            echo "artifact symlinks are not allowed"
            exit 1
          fi
          for file in summary.json evidence.json skill-updates.json; do
            [ ! -f "qa-results/$file" ] || [ "$(wc -c < "qa-results/$file")" -le 65536 ] || exit 1
          done
          [ ! -f qa-results/report.md ] || [ "$(wc -c < qa-results/report.md)" -le 60000 ] || exit 1

      - name: Apply result policy
        env:
          QA_EXECUTION_OUTCOME: ${{ needs.qa.outputs.execution_outcome }}
        run: |
          # Missing, crashed, malformed, blocked, and inconclusive evidence cannot pass.
          [[ "$QA_EXECUTION_OUTCOME" = success ]] || { echo "QA did not complete successfully"; exit 1; }
          python3 trusted/<skills-dir>/qa/scripts/validate_results.py qa-results
```

## `.github/workflows/qa-report.yml`: trusted reporting only

Install this workflow on the default branch before expecting comments. Do not add
`pull_request` or manual triggers here. Do not checkout the upstream run's SHA,
load its scripts, restore its caches, install its dependencies, or run app code.

```yaml
name: QA Report
on:
  workflow_run:
    workflows: [QA]
    types: [completed]
permissions: {}
concurrency:
  group: qa-report-${{ github.event.workflow_run.pull_requests[0].number || github.event.workflow_run.id }}
  cancel-in-progress: false
jobs:
  publish:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      actions: read
      contents: read
      pull-requests: write
    steps:
      - name: Validate originating run and current PR
        id: origin
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_ID: ${{ github.event.workflow_run.id }}
          RUN_ATTEMPT: ${{ github.event.workflow_run.run_attempt }}
        run: |
          [[ "$RUN_ID" =~ ^[0-9]+$ && "$RUN_ATTEMPT" =~ ^[0-9]+$ ]] || exit 1
          run=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$RUN_ID")
          workflow=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/qa.yml")
          # Validate server-side identity; no identity comes from artifact contents.
          jq -e --arg repo "$GITHUB_REPOSITORY" --argjson repo_id "$GITHUB_REPOSITORY_ID" \
            --argjson id "$RUN_ID" --argjson attempt "$RUN_ATTEMPT" \
            --argjson workflow_id "$(jq .id <<<"$workflow")" '
            .id == $id and .run_attempt == $attempt and .status == "completed" and
            .event == "pull_request" and .repository.id == $repo_id and
            .repository.full_name == $repo and .head_repository.id == $repo_id and
            .head_repository.full_name == $repo and .workflow_id == $workflow_id and
            .path == ".github/workflows/qa.yml" and .name == "QA" and
            (.head_sha | test("^[0-9a-f]{40}$")) and (.pull_requests | length == 1)
          ' <<<"$run" >/dev/null
          pr_number=$(jq -r '.pull_requests[0].number' <<<"$run")
          sha=$(jq -r .head_sha <<<"$run")
          [[ "$pr_number" =~ ^[0-9]+$ ]] || exit 1
          pr=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$pr_number")
          jq -e --arg sha "$sha" --argjson repo_id "$GITHUB_REPOSITORY_ID" '
            .state == "open" and .head.sha == $sha and
            .base.repo.id == $repo_id and .head.repo.id == $repo_id
          ' <<<"$pr" >/dev/null
          jobs=$(gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/actions/runs/$RUN_ID/attempts/$RUN_ATTEMPT/jobs")
          outcome=failure
          if [[ $(jq -r .conclusion <<<"$run") = success ]] && jq -e '
            ([.[].jobs[] | select(.name == "QA / report")] |
              length == 1 and .[0].status == "completed" and .[0].conclusion == "success") and
            ([.[].jobs[] | select(.name == "QA execution")] |
              length == 1 and (.[0] | .status == "completed" and .conclusion == "success" and
              ([.steps[] | select(.name == "Run QA")] | length == 1 and .[0].conclusion == "success")))' \
            <<<"$jobs" >/dev/null; then outcome=success; fi
          echo "pr_number=$pr_number" >> "$GITHUB_OUTPUT"
          echo "head_sha=$sha" >> "$GITHUB_OUTPUT"
          echo "execution_outcome=$outcome" >> "$GITHUB_OUTPUT"
          echo "run_id=$RUN_ID" >> "$GITHUB_OUTPUT"
          echo "run_attempt=$RUN_ATTEMPT" >> "$GITHUB_OUTPUT"

      - name: Validate run artifact metadata
        id: artifact
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_ID: ${{ steps.origin.outputs.run_id }}
          RUN_ATTEMPT: ${{ steps.origin.outputs.run_attempt }}
          TESTED_SHA: ${{ steps.origin.outputs.head_sha }}
        run: |
          echo 'available=false' >> "$GITHUB_OUTPUT"
          artifacts=$(gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/actions/runs/$RUN_ID/artifacts") || exit 0
          selected=$(jq --arg name "qa-results-$RUN_ATTEMPT" '[.[].artifacts[] | select(.name == $name)]' <<<"$artifacts")
          if [[ $(jq length <<<"$selected") = 0 ]]; then exit 0; fi
          jq -e --argjson run_id "$RUN_ID" --argjson repo_id "$GITHUB_REPOSITORY_ID" --arg sha "$TESTED_SHA" '
            length == 1 and (.[0] | .expired == false and .size_in_bytes <= 104857600 and
            .workflow_run.id == $run_id and .workflow_run.repository_id == $repo_id and
            .workflow_run.head_repository_id == $repo_id and .workflow_run.head_sha == $sha)
          ' <<<"$selected" >/dev/null || exit 0
          echo 'available=true' >> "$GITHUB_OUTPUT"

      - name: Check out trusted scripts from the default branch
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          path: trusted
          sparse-checkout: <skills-dir>/qa/scripts
          persist-credentials: false

      - uses: actions/download-artifact@v4
        id: download
        if: steps.artifact.outputs.available == 'true'
        continue-on-error: true
        with:
          name: qa-results-${{ steps.origin.outputs.run_attempt }}
          run-id: ${{ steps.origin.outputs.run_id }}
          github-token: ${{ github.token }}
          repository: ${{ github.repository }}
          path: qa-results

      - name: Validate artifact paths
        id: paths
        continue-on-error: true
        run: |
          [ ! -L qa-results ] || { echo "artifact root must not be a symlink"; exit 1; }
          mkdir -p qa-results
          if find qa-results -type l -print -quit | grep -q .; then
            echo "artifact symlinks are not allowed"
            exit 1
          fi
          for file in summary.json evidence.json skill-updates.json; do
            [ ! -f "qa-results/$file" ] || [ "$(wc -c < "qa-results/$file")" -le 65536 ] || exit 1
          done
          [ ! -f qa-results/report.md ] || [ "$(wc -c < qa-results/report.md)" -le 60000 ] || exit 1

      - name: Validate result before publishing
        id: policy
        env:
          QA_EXECUTION_OUTCOME: ${{ steps.origin.outputs.execution_outcome }}
          ARTIFACT_PATHS_OUTCOME: ${{ steps.paths.outcome }}
          ARTIFACT_DOWNLOAD_OUTCOME: ${{ steps.download.outcome }}
        run: |
          echo 'validated=false' >> "$GITHUB_OUTPUT"
          printf '## QA Report\n\n**Result: FAILED / INCOMPLETE.** QA execution or evidence validation failed. The agent report is withheld; inspect the run logs and artifacts.\n' > validated-report.md
          if [[ "$QA_EXECUTION_OUTCOME" = success && "$ARTIFACT_PATHS_OUTCOME" = success && "$ARTIFACT_DOWNLOAD_OUTCOME" = success ]] &&
             python3 trusted/<skills-dir>/qa/scripts/validate_results.py qa-results; then
            cp qa-results/report.md validated-report.md
            echo 'validated=true' >> "$GITHUB_OUTPUT"
          fi

      - name: Upload inline evidence
        continue-on-error: true            # optional media must not suppress the current report
        if: steps.policy.outputs.validated == 'true'
        env:
          QA_EVIDENCE_TOKEN: ${{ secrets.QA_EVIDENCE_TOKEN }}
          REPO_ID: ${{ github.event.repository.id }}
        run: |
          mkdir -p qa-results
          echo '{}' > qa-results/uploads.json
          [ -n "$QA_EVIDENCE_TOKEN" ] && [ -f qa-results/evidence.json ] || exit 0
          if ! jq -e 'type == "array"' qa-results/evidence.json >/dev/null 2>&1; then
            echo "Inline evidence metadata is unavailable or malformed; continuing without uploads"
            exit 0
          fi
          jq -c '.[] | select(type == "object") | select((.id | type) == "string" and (.file | type) == "string")' qa-results/evidence.json | while read -r e; do
            id=$(jq -r '.id // empty' <<<"$e"); file=$(basename "$(jq -r '.file // empty' <<<"$e")")
            [[ "$id" =~ ^[a-z0-9-]{1,64}$ ]] || continue
            case "$file" in
              *.webm) ct=video/webm ;; *.mp4) ct=video/mp4 ;; *.png) ct=image/png ;; *) continue ;;
            esac
            [[ "$file" =~ ^[a-z0-9-]+\.(png|webm|mp4)$ ]] || continue
            path="qa-results/evidence/$file"
            [ ! -L qa-results ] && [ ! -L qa-results/evidence ] && [ ! -L "$path" ] && [ -s "$path" ] || continue
            url=$(curl -sS --fail-with-body -X POST \
              -H "Authorization: Bearer $QA_EVIDENCE_TOKEN" -H "Content-Type: application/octet-stream" \
              -H "Accept: application/json" -H "X-GitHub-Api-Version: 2022-11-28" \
              --data-binary "@$path" \
              "https://uploads.github.com/user-attachments/assets?name=$file&content_type=${ct/\//%2F}&repository_id=$REPO_ID" \
              | jq -er '.url') || { echo "upload failed: $file"; continue; }
            # Videos: bare URL alone on its line renders a player. Images: image markdown.
            if [ "$ct" = image/png ]; then embed="![${id}]"; embed+="(${url})"; else embed="$url"; fi
            jq --arg k "$id" --arg v "$embed" '.[$k]=$v' qa-results/uploads.json > u.tmp && mv u.tmp qa-results/uploads.json
          done

      - name: Embed evidence
        if: steps.policy.outputs.validated == 'true'
        run: |
          s=trusted/<skills-dir>/qa/scripts/embed_evidence.py
          if [ -f "$s" ]; then
            python3 "$s" qa-results
            cp qa-results/report.md validated-report.md
          else
            echo "embed script not on default branch yet; skipping"
          fi

      - name: Post or update the QA comment
        env:
          GH_TOKEN: ${{ github.token }}
          PR_NUMBER: ${{ steps.origin.outputs.pr_number }}
          TESTED_SHA: ${{ steps.origin.outputs.head_sha }}
          RUN_ID: ${{ steps.origin.outputs.run_id }}
          RUN_ATTEMPT: ${{ steps.origin.outputs.run_attempt }}
        run: |
          # Recheck just before writing: stale results must not overwrite a newer report.
          pr=$(gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER")
          jq -e --arg sha "$TESTED_SHA" '.state == "open" and .head.sha == $sha' <<<"$pr" >/dev/null
          runs=$(gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/actions/workflows/qa.yml/runs?event=pull_request&head_sha=$TESTED_SHA&per_page=100")
          jq -e --arg sha "$TESTED_SHA" --argjson pr "$PR_NUMBER" --argjson id "$RUN_ID" --argjson attempt "$RUN_ATTEMPT" '
            [.[].workflow_runs[] | select(.event == "pull_request" and .head_sha == $sha and
              any(.pull_requests[]; .number == $pr))] | max_by(.run_number) |
            .id == $id and .run_attempt == $attempt
          ' <<<"$runs" >/dev/null
          {
            echo '<!-- qa-report -->'
            printf 'Tested commit: `%s`\n\n' "$TESTED_SHA"
            cat validated-report.md
            printf '\n---\n[Run log]'; printf '(%s/%s/actions/runs/%s) · raw evidence in the run artifacts\n' "$GITHUB_SERVER_URL" "$GITHUB_REPOSITORY" "$RUN_ID"
          } > body.md
          # Bound the final payload after attachment URLs and metadata were added.
          if [ "$(wc -c < body.md)" -gt 60000 ]; then
            {
              echo '<!-- qa-report -->'
              printf '## QA Report\n\n**Result: INCOMPLETE REPORT.** The embedded report exceeded the comment size limit; inspect the run artifacts.\n\n'
              printf 'Tested commit: `%s`\n\n' "$TESTED_SHA"
              printf 'Run: %s/%s/actions/runs/%s\n' "$GITHUB_SERVER_URL" "$GITHUB_REPOSITORY" "$RUN_ID"
            } > body.md
          fi
          id=$(gh api --paginate "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" \
            --jq '.[] | select(.user.login == "github-actions[bot]" and (.body | startswith("<!-- qa-report -->"))) | .id' | head -n1)
          if [ -n "$id" ]; then
            gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$id" -F body=@body.md > /dev/null
          else
            gh api -X POST "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" -F body=@body.md > /dev/null
          fi
```

## Generation rules

- `QA / report` is the read-only PR check. Keep `if: always()` and never skip the
  job when QA was skipped: absent execution evidence must fail. This control is
  advisory-only: PR authors can edit this job, so it must not be required for
  merging. Enforcement needs a separately reviewed protected producer.
- Fork QA is BLOCKED by this template: automatic execution is skipped and the
  gate fails. Manual dispatch is informational and cannot satisfy a fork-head
  check. Do not claim fork support until a separately reviewed authorized route
  produces exact-head evidence. The privileged reporter rejects fork and manual
  origins and never accepts a PR number supplied by an artifact.
- Both workflows use fresh GitHub-hosted runners. The reporter workflow and its
  scripts must exist on the trusted default branch; first-install PRs do not
  activate reporting. PR changes to the reporter are not executed by the
  `workflow_run` event until merged.
- The reporter validates source workflow ID/path, repository IDs, run attempt,
  current PR SHA, artifact provenance/size, and execution results using GitHub
  APIs. It consumes artifacts only as data, never as scripts, command arguments,
  workflow output files, caches, or dependency manifests.
- Preview polling belongs only in the read-only QA job, for the resolved SHA and
  expected deployment creator. Timeout/failure is BLOCKED. Never use a privileged
  `workflow_run` job to launch PR code. Never use `pull_request_target`.
- `QA_EVIDENCE_TOKEN` exists only in the trusted reporter. Inline uploads run only after result validation. Failed/incomplete evidence produces
  an explicit replacement comment, never the agent's optimistic PASS report.
- Failure learning is suggestion-only. Put reviewed suggestions in the structured
  result's `action_required` list. This workflow does not push commits or open PRs.
- Full action SHA pins are required in generated files. Run actionlint on both
  workflows after replacing placeholders, then exercise passing, crashed,
  missing-artifact, and fork cases before enabling advisory evidence.
