# GitHub Actions workflow

Template for Phase 4g of `qa-bootstrap`. Generate only if the user said yes in question 3.1.

If the user approved replacing existing QA workflows, remove them and list them in the Phase 5 summary. Otherwise leave them alone.

Generate `.github/workflows/qa.yml`, filling the `<...>` placeholders from the analysis:

```yaml
# QA: runs the qa skill against PR code, then posts one sticky comment.
#
# Two jobs on purpose:
#   qa      executes the agent on the PR's code with READ-ONLY permissions
#   report  has write permissions but never runs PR code; its scripts come
#           from the default branch
name: QA

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:                       # manual run, e.g. for a reviewed fork PR
    inputs:
      pr_number:
        description: PR number
        required: true
      head_sha:
        description: Exact commit you reviewed (required for fork PRs)
        required: true

permissions: {}                            # each job declares exactly what it needs

concurrency:                               # one run per PR; new pushes cancel old runs
  group: qa-${{ github.event.pull_request.number || inputs.pr_number }}
  cancel-in-progress: true

env:
  PR_NUMBER: ${{ github.event.pull_request.number || inputs.pr_number }}

jobs:
  # ─────────────────────────────────────────────────────────────────────
  # Job 1: run QA (read-only)
  # ─────────────────────────────────────────────────────────────────────
  qa:
    # Fork PRs never run automatically; a maintainer dispatches them after review.
    if: github.event_name == 'workflow_dispatch' || github.event.pull_request.head.repo.full_name == github.repository
    runs-on: ubuntu-latest
    timeout-minutes: 25
    permissions:
      contents: read
      pull-requests: read
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
        continue-on-error: true            # the report job decides pass/fail
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
          name: qa-results
          path: qa-results/
          retention-days: 14

  # ─────────────────────────────────────────────────────────────────────
  # Job 2: report (write permissions, trusted code only)
  # ─────────────────────────────────────────────────────────────────────
  report:
    name: QA / report
    needs: qa
    if: always() && needs.qa.result != 'skipped'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read                       # write only for auto_commit / open_pr
      pull-requests: write
    steps:
      - name: Check out trusted scripts from the default branch
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.repository.default_branch }}
          path: trusted
          sparse-checkout: <skills-dir>/qa/scripts
          persist-credentials: false

      - uses: actions/download-artifact@v4
        continue-on-error: true            # a crashed qa job still gets a comment
        with:
          name: qa-results
          path: qa-results

      - name: Validate artifact paths
        run: |
          [ ! -L qa-results ] || { echo "artifact root must not be a symlink"; exit 1; }
          mkdir -p qa-results
          if find qa-results -type l -print -quit | grep -q .; then
            echo "artifact symlinks are not allowed"
            exit 1
          fi

      # ── Inline evidence (no-op unless QA_EVIDENCE_TOKEN is set) ────────
      - name: Upload inline evidence
        env:
          QA_EVIDENCE_TOKEN: ${{ secrets.QA_EVIDENCE_TOKEN }}
          REPO_ID: ${{ github.event.repository.id }}
        run: |
          mkdir -p qa-results
          echo '{}' > qa-results/uploads.json
          [ -n "$QA_EVIDENCE_TOKEN" ] && [ -f qa-results/evidence.json ] || exit 0
          jq -c '.[]?' qa-results/evidence.json | while read -r e; do
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
        run: |
          s=trusted/<skills-dir>/qa/scripts/embed_evidence.py
          if [ -f "$s" ]; then
            python3 "$s" qa-results
          else
            echo "embed script not on default branch yet; skipping"
          fi

      # ── Sticky comment: one per PR, updated in place ───────────────────
      - name: Post or update the QA comment
        env:
          GH_TOKEN: ${{ github.token }}
          TESTED_SHA: ${{ inputs.head_sha || github.event.pull_request.head.sha }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          {
            echo '<!-- qa-report -->'
            printf 'Tested commit: `%s`\n\n' "$TESTED_SHA"
            if [ -s qa-results/report.md ]; then
              grep -q '^## QA Report' qa-results/report.md || echo '## QA Report'
              cat qa-results/report.md
            else
              printf '## QA Report\n\n:no_entry: QA produced no report. See the run log.\n'
            fi
            printf '\n---\n[Run log]'; printf '(%s) · raw evidence in the `qa-results` artifact\n' "$RUN_URL"
          } > body.md
          id=$(gh api --paginate "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" \
            --jq '.[] | select(.user.login == "github-actions[bot]" and (.body | startswith("<!-- qa-report -->"))) | .id' | head -n1)
          if [ -n "$id" ]; then
            gh api -X PATCH "repos/$GITHUB_REPOSITORY/issues/comments/$id" -F body=@body.md > /dev/null
          else
            gh api -X POST "repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments" -F body=@body.md > /dev/null
          fi

      # ── Failure learning (open_pr / auto_commit only; see notes) ───────

      # ── Pass/fail for the check ────────────────────────────────────────
      - name: Apply result policy
        env:
          QA_EXECUTION_OUTCOME: ${{ needs.qa.outputs.execution_outcome }}
        run: |
          # Missing, crashed, malformed, blocked, and inconclusive evidence cannot pass.
          [[ "$QA_EXECUTION_OUTCOME" = success ]] || { echo "QA did not complete successfully"; exit 1; }
          jq -e '
            type == "object" and .overall == "pass" and
            (.counts | type == "object") and
            ([.counts.pass, .counts.fail, .counts.blocked, .counts.flaky, .counts.inconclusive] |
              all(type == "number" and . >= 0 and . == floor)) and
            .counts.fail == 0 and .counts.blocked == 0 and .counts.inconclusive == 0 and
            (.counts.pass + .counts.flaky > 0)
          ' qa-results/summary.json >/dev/null
```

Notes for generating this workflow:

- **Required check.** The explicit report job name creates `QA / report`. Require that check only after a representative run verifies it. An advisory check can fail without blocking merges; never turn missing or blocked evidence into a successful check.
- **Manual fork runs.** Dispatch from the trusted default branch. The preflight requires a 40-character SHA matching the open PR head; a moving branch name or stale reviewed SHA is rejected before checkout. A manual run checks the dispatch revision, so do not present it as a required check bound to the fork commit; its comment must identify the tested SHA.
- **Runner isolation.** Use a fresh GitHub-hosted runner for both jobs. Never reuse a persistent self-hosted runner between PR code and the privileged report job.
- **Action pinning.** Resolve every action version shown here to a reviewed full commit SHA before generating the workflow.
- **Waiting for previews** (if requested): keep the existing PR/manual triggers and poll deployment statuses for `steps.pr.outputs.head_sha` in the read-only QA job. Verify the expected deployment creator and exact commit; timeout or failure means BLOCKED. Do not introduce a privileged `workflow_run` trigger to execute PR code.
- **Never use `pull_request_target`.**
- **Failure learning, `open_pr`:** in the report job, check out the default branch with credentials into `repo/`; run `python3 trusted/<skills-dir>/qa/scripts/apply_skill_updates.py qa-results/skill-updates.json repo <skills-dir>`; if `git -C repo diff --quiet <skills-dir>` shows changes, commit to `qa/learned-${{ github.run_id }}` and `gh pr create --draft --base <default-branch>`. Needs `contents: write`.
- **Failure learning, `auto_commit`:** only when the PR head repo equals this repo. Check out the PR head branch with credentials, apply with the same trusted script, commit and push. Pushes made with `GITHUB_TOKEN` do not retrigger the workflow. Needs `contents: write`.
- **`QA_EVIDENCE_TOKEN`** is referenced only in the report job; the agent job never sees it.
