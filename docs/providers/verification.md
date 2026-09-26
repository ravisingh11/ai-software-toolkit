# Live verification ledger

Fixtures prove that an adapter maps exit codes and output correctly. Only a
run against the real service proves that the credential handling, project
configuration, and check identity work end to end. An adapter is labelled
**verified** only in the pull request that adds its row here; the row must
name the toolkit revision that was exercised. A row is stale once the
adapter's source (`tooling/provider_adapter.py` or its workflow template)
changes after that revision.

| Provider | Verified | Date | Toolkit revision | Account owner | Project | Outcome observed | Run |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SonarQube | no | — | — | — | — | — | — |
| Snyk Code | no | — | — | — | — | — | — |
| Snyk Open Source | no | — | — | — | — | — | — |
| FOSSA | no | — | — | — | — | — | — |

To add a row: run the provider's workflow on a representative pull request of
a repository you own, confirm the check binds to the head commit and the
scorecard shows its evidence, then record the date, `git describe` of the
toolkit revision, who holds the service account, the project identifier, the
outcome the check reported, and a link to the workflow run. Never record
credential values.
