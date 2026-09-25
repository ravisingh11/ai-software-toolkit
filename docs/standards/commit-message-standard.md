# Commit Message Standard

Use concise, auditable commit messages that explain the business or engineering
outcome without turning every change into heavyweight process.

## Format

```text
<type>: <imperative summary>
```

Examples:

```text
fix: preserve document ownership on admin edits
feat: add tenant-level billing controls
chore: mark repo private
docs: document deployment rollback path
```

## Types

- `fix`: Corrects a bug, regression, security issue, or data integrity issue.
- `feat`: Adds or expands product capability.
- `chore`: Maintenance, dependency, repository, or operational cleanup.
- `docs`: Documentation-only changes.
- `test`: Test-only changes.
- `refactor`: Internal restructuring with no intended behavior change.
- `ci`: CI, automation, or workflow changes.
- `revert`: Reverts a previous commit.

## Rules

- Use imperative voice: `fix`, `add`, `remove`, `document`.
- Keep the subject under 72 characters when practical.
- Mention the user-visible or operational outcome, not just the file changed.
- Prefer one coherent reason per commit.
- Do not include secrets, credentials, tokens, customer data, or private incident
  detail in commit messages.
- If the change closes an issue, include `Closes #123` in the commit body, issue
  update, or PR when the repository chooses to use PRs.

## Optional Body

Use a body when the reason is not obvious:

```text
fix: hide private user progress from public profile routes

Public handle routes previously returned progress for users marked private.
This adds the same privacy gate used by profile lookup and verifies the 404
behavior in route tests.
```
