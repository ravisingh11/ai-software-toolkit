# SonarQube

| | |
| --- | --- |
| Provider id | `sonarqube` |
| Capabilities | `static-quality`, `changed-code-coverage` |
| Check name | `SonarQube Quality Gate` |
| Workflow | `SonarQube` (`.github/workflows/sonar.yml`) |
| Commands | `SonarSource/sonarqube-scan-action` then `SonarSource/sonarqube-quality-gate-action` (waits for the asynchronous gate) |
| Credential | `SONAR_TOKEN` (GitHub secret) |
| Settings | `SONAR_HOST_URL`, `SONAR_PROJECT_KEY` (or `sonar-project.properties`), optional `SONAR_ARGS`, `SONAR_PROJECT_BASE_DIRECTORY` repository variables |

## Completed analysis

SonarQube computes the quality gate asynchronously after the scanner uploads.
The template waits for the gate with a ten-minute timeout, so the check
reflects a completed analysis of the exact head commit, not an upload. A gate
timeout fails the job (`failed` at the check-run surface). Parameters that
cannot be set in the UI are documented in the
[SonarQube analysis parameters reference](https://docs.sonarsource.com/sonarqube-cloud/analyzing-source-code/analysis-parameters/parameters-not-settable-in-ui).

## Install

```sh
cp <toolkit>/workflows/sonar.yml .github/workflows/sonar.yml
python3 .guardrails/configure.py --select-provider changed-code-coverage=sonarqube --set changed-code-coverage=advisory
```

Selecting SonarQube for `changed-code-coverage` replaces the repository
coverage command as the authoritative provider; keep the command provider if
you want a local result and add SonarQube as supplemental instead.

## Verify

Open a pull request, confirm `SonarQube Quality Gate` appears for the head
commit, and record the run in the [verification ledger](verification.md).
