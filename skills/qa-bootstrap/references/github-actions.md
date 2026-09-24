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
    runs-on: <runner label used by this repo's workflows>
    timeout-minutes: 25
    permissions:
      contents: read
      pull-requests: read
    steps:
      - name: Resolve base branch
        id: pr
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          [[ "$PR_NUMBER" =~ ^[0-9]+$ ]] || { echo "invalid PR number"; exit 1; }
          echo "base_ref=$(gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json baseRefName --jq .baseRefName)" >> "$GITHUB_OUTPUT"

      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.head_sha || github.event.pull_request.head.sha }}
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
          QA_DIFF_BASE: origin/${{ steps.pr.outputs.base_ref }}
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
    needs: qa
    if: always() && needs.qa.result != 'skipped'
    runs-on: <runner label>
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

      # ── Inline evidence (no-op unless QA_EVIDENCE_TOKEN is set) ────────
      - name: Upload inline evidence
        env:
          QA_EVIDENCE_TOKEN: ${{ secrets.QA_EVIDENCE_TOKEN }}
          REPO_ID: ${{ github.event.repository.id }}
        run: |
          echo '{}' > qa-results/uploads.json
          [ -n "$QA_EVIDENCE_TOKEN" ] && [ -f qa-results/evidence.json ] || exit 0
          jq -c '.[]?' qa-results/evidence.json | while read -r e; do
            id=$(jq -r '.id // empty' <<<"$e"); file=$(basename "$(jq -r '.file // empty' <<<"$e")")
            [[ "$id" =~ ^[a-z0-9-]{1,64}$ ]] || continue
            case "$file" in
              *.webm) ct=video/webm ;; *.mp4) ct=video/mp4 ;; *.png) ct=image/png ;; *) continue ;;
            esac
            path="qa-results/evidence/$file"; [ -s "$path" ] || continue
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
          [ -f "$s" ] && python3 "$s" qa-results || echo "embed script not on default branch yet; skipping"

      # ── Sticky comment: one per PR, updated in place ───────────────────
      - name: Post or update the QA comment
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        run: |
          {
            echo '<!-- qa-report -->'
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
          FAIL_ON: '<from ci.fail_on, space-separated, e.g. "fail">'   # the one config value copied here
        run: |
          overall=$(jq -r '.overall // "blocked"' qa-results/summary.json 2>/dev/null || echo blocked)
          echo "QA overall: $overall"
          case " $FAIL_ON " in *" $overall "*) exit 1 ;; esac
```

Notes for generating this workflow:

- **Required check.** If QA should block merges, the check to require is `QA / report`.
- **Waiting for previews** (if requested): add a `workflow_run` trigger on every deployment workflow that produces a preview (frontend and backend may deploy separately). Then gate the job on `github.event.workflow_run.head_repository.full_name == github.repository` (`workflow_run` runs with secrets even for fork PRs), check out `github.event.workflow_run.head_sha`, take the PR number from `github.event.workflow_run.pull_requests[0].number`, and keep `pull_request` as a fallback. If a deployment failed, run anyway and let that app report BLOCKED.
- **Never use `pull_request_target`.**
- **Failure learning, `open_pr`:** in the report job, check out the default branch with credentials into `repo/`; run `python3 trusted/<skills-dir>/qa/scripts/apply_skill_updates.py qa-results/skill-updates.json repo <skills-dir>`; if `git -C repo diff --quiet <skills-dir>` shows changes, commit to `qa/learned-${{ github.run_id }}` and `gh pr create --draft --base <default-branch>`. Needs `contents: write`.
- **Failure learning, `auto_commit`:** only when the PR head repo equals this repo. Check out the PR head branch with credentials, apply with the same trusted script, commit and push. Pushes made with `GITHUB_TOKEN` do not retrigger the workflow. Needs `contents: write`.
- **`QA_EVIDENCE_TOKEN`** is referenced only in the report job; the agent job never sees it.
