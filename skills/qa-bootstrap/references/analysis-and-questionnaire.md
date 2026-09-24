# Analysis and questionnaire

Detail for Phases 2 and 3 of `qa-bootstrap`.

## Phase 2: Analyze the codebase

Detect everything below without asking. Then present a structured summary, grouped the same way, before the first question.

### 2a. What the product is

**Apps.** Monorepo or single app (workspace configs, top-level directories). For each app: type (web, API, CLI/TUI, desktop, mobile), framework and language, the path patterns that belong to it, and its build, start, and readiness commands.

**Shared code.** Packages or directories imported by more than one app, root dependency manifests and lockfiles, shared config (base tsconfig, env schemas, UI kits). A change here can break every app that depends on it. Record which apps each one affects.

**Critical user flows.** From routes, navigation, page and view components, API endpoints, forms, and CLI command definitions.

### 2b. How it runs

**Environments.** Every environment URL from `.env*` files, config, CI workflows, deployment manifests, and the README.

**Preview deployments.** Whether PRs get preview deployments (Vercel, Netlify, Render, Cloudflare Pages, custom). If so:

- Which backend, database, and third-party keys previews use: their own isolated stack, or a shared environment's.
- How the URL is exposed. Prefer the deployments/statuses API over bot comments.
- Whether previews sit behind deployment protection.
- Whether frontend and backend deploy separately.

**Authentication.** Login method (OAuth, email/password, magic link, OTP, SSO/SAML, API key), the auth library or provider, and session handling.

**Feature flags.** Provider (LaunchDarkly, Statsig, Unleash, Split, Flagsmith, GrowthBook, custom) and how flags are evaluated and overridden.

**External integrations.**

- Payments: Stripe, Braintree, PayPal.
- Email: providers such as SendGrid, SES, Postmark, Resend; test inboxes such as Mailpit, MailHog, Mailtrap, Mailosaur.
- SMS: Twilio, MessageBird.
- Other SaaS SDKs in the dependency manifests.

### 2c. How it is tested and shipped

**Existing tests.** Frameworks and E2E suites. Useful references for flows and selectors; QA does not run them.

**Automation tooling.** For each interactive app, what can drive it:

- Web or Electron: a browser automation tool available to this agent, such as Playwright.
- CLI/TUI: a terminal driver that can send keystrokes and read screen text (a pty-based tool, tmux, or expect).
- Desktop: a desktop automation tool.
- APIs: `curl`.

Note what is installed locally and what CI would need. An interactive app with no usable driver is a setup blocker; report it rather than generating flows that cannot run.

**CI/CD.** Existing QA/E2E workflows, runner labels, and whether the repo receives PRs from forks. This skill generates separate read-only QA and trusted reporting GitHub Actions workflows; if the repo is hosted elsewhere, say so and skip Part 3.

**Agent CLI in CI.** Whether existing workflows already run an agent CLI headlessly. If so, record its install step, its non-interactive invocation, and the secret it authenticates with.

## Phase 3: Questionnaire

Ask only what you could not detect, and frame each question around what you found. Use the agent's structured question tool if it has one. Ask one part at a time; after each part, save the answers to `.install-progress.yaml`.

Each question below gives the wording, the default where one exists, and (in italics) why it matters, so you can explain if the user asks.

### Part 1: What to test

**1.1 Default environment.** "I found these environments: [list]. When nobody specifies one, which should QA test against?"
*Most runs are triggered automatically, so this is the one QA will use most.*

**1.2 Environment limits.** "Is there anything QA must never do in some environments? Common examples: never create accounts in production, or treat staging as read-only." (Default: none.)

**1.3 Previews.** Only if previews were detected: "Preview deployments look like they use [dev]'s backend and database. Is that right?"
*Decides which test data QA uses on previews, for example sandbox payment cards. Never assume previews behave like dev.*

**1.4 User types.** Introduce it: "QA tests as different kinds of users, so permissions get checked both ways: an admin can change settings, a member can do their work, and a viewer really can't edit anything." Then, for each role: "What is it called? What can it do? What must it never be able to do? Is there a dedicated test account, and what is its email?"
*The "must never" answers become negative tests.*

**1.5 Missing accounts.** "For roles without a test account, should QA sign up a fresh user during the run, or will you provide accounts?"

**1.6 Where credentials live.** "Where are the test logins stored? An env var, a secrets manager key, a vault path, or will someone enter them by hand?"
*QA stores only the reference, never the value.*

**1.7 Flows.** "These look like the critical flows: [list]. Anything to add or drop?" Then for each: "How do you know it worked?" and "Should more than one user type run it?", "Does it leave data behind?", and "Is it part of a basic smoke check of the app?"

### Part 2: Test data and services

**2.1 Integrations.** Only for detected ones: "You use [service]. Does it have a sandbox or test mode, and which test credentials should QA use?"

**2.2 Test email.** Only if no test inbox was detected: "Some flows send email (signup, password reset). Where should QA look for those emails during a run?"

**2.3 Cleanup.** "QA will create users and data. How should it clean up afterwards?" Options: an API endpoint (which one), the admin panel, a database reset command, leave it for manual cleanup, or not needed because the tests are read-only.

### Part 3: Running it in CI

**3.1 Generate CI?** Ask this first; if the answer is no, skip the rest of Part 3 and questions 4.2 and 4.3. List existing QA/E2E workflows, then: "Should I add two GitHub Actions workflows: read-only QA on PRs and a separate default-branch reporter that keeps one QA comment per PR up to date? [If existing workflows:] Should it replace [names], or run alongside them?"
*This is the approval gate for posting to PRs. Generate nothing unless the answer is yes.*

**3.2 Agent CLI.** Confirm what was detected, or ask: "Which agent CLI should run QA in CI, how is it installed, what is its non-interactive command, and what is the name of the secret holding its API key?"
Recommend the narrowest permission mode that still lets it build and launch the app and use the automation tools. Prefer a scoped tool allowlist over any "skip all permissions" flag.

**3.3 Advisory status.** Explain that functional QA is advisory-only: the PR can edit the execution workflow and result source, so its check is not an enforceable security boundary. Do not offer a required-check or promotion option. A protected producer architecture is separate future work.
*Only completed PASS evidence succeeds. FAIL, BLOCKED, and INCONCLUSIVE remain unsuccessful advisory checks. BLOCKED means QA could not test, not that the app is broken.*

**3.4 Previews.** Only if previews were detected: "Should CI wait for the preview deployment before testing, so QA tests the branch's real code?" (Default: yes.)

**3.5 Fork PRs.** Explain, then confirm: "QA runs automatically only for PRs from branches in this repository. Fork PRs receive a failing BLOCKED advisory check. A reviewed manual run is informational and does not produce fork-head evidence; exact-head fork support needs a separately reviewed route. Is that acceptable?"
*Running an agent on unreviewed outside code with your secrets in scope is the classic CI attack.*

### Part 4: Evidence and learning

**4.1 Video.** Only if an interactive app exists: "Text snapshots and screenshots are always captured. Should QA also record one short video per flow?" (Default: no.)
*Browser tools produce WebM/MP4. Terminal sessions produce asciinema `.cast` files, which are downloadable but not playable inline.*

**4.2 Inline media.** Only if CI was requested: "Should screenshots and videos appear inline in the PR comment, or only as downloadable artifacts?" (Default: artifacts only.)
*Inline needs the `uploads.github.com/user-attachments` endpoint, which is undocumented and may change, and only accepts a classic PAT with `repo` scope (the workflow token and fine-grained PATs are rejected). The token is used only in the trusted default-branch reporting workflow and never reaches the PR workflow or agent.*

**4.3 Learning from failures.** Explain the supported mode: QA records proposed environment notes in the structured `action_required` strings for human review. Each suggestion names the affected skill and the proposed addition. Suggestions remain in the summary artifact when the run is incomplete or nonpassing; do not append freeform report Markdown that the trusted renderer discards.

Set `failure_learning: suggest_in_report`. Automatic PR creation and commits are not implemented and must not be offered.
