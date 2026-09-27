# Licensing and attribution

## Repository license

First-party source, documentation, policies, workflow templates, schemas,
prompts, rules, and agent skills in this repository are released under the
[MIT License](../LICENSE). Preserve the copyright and license notice when
redistributing substantial portions. [NOTICE](../NOTICE) records attribution
and does not grant trademark or endorsement rights.

## Core scanner boundary

Proof invokes third-party scanner containers; it does not relicense them.

| Component used by Core | Upstream license boundary | Proof usage |
| --- | --- | --- |
| [Semgrep Community Edition](https://github.com/semgrep/semgrep/blob/develop/LICENSE) | LGPL-2.1 | Pinned CLI container, local `semgrep scan`, repository-owned tested rules, no platform token |
| [Gitleaks CLI](https://github.com/gitleaks/gitleaks/blob/master/LICENSE) | MIT | Pinned CLI container, local Git-history scan |
| [Gitleaks Action](https://github.com/gitleaks/gitleaks-action/blob/master/LICENSE.txt) | Separate Gitleaks Action EULA | Not used by Core |

The Gitleaks CLI and Gitleaks Action are different products with different
license terms. Core invokes the CLI directly and does not require an Action
license key.

Semgrep rules can have licenses independent of the Semgrep engine. The bundled
rules are first-party MIT content. Review and preserve the license of any rule
pack copied from another source.

## Optional integrations

GitHub Actions, CodeQL, Dependency Review, Artifact Attestations, SonarQube,
Snyk, Semgrep AppSec Platform, FOSSA, and other services retain their own terms.
Provider definitions and links in this repository do not grant service access
or replace a consuming organization's legal and procurement review.

Pinning an Action or container makes execution reproducible; it does not change
the component's license.

## Contributions and generated copies

Contributors must have the right to license submitted material and must retain
third-party notices. Installed Proof files remain under their applicable
source licenses. Generated evidence and scorecards may contain provider output;
review that provider's terms before redistributing reports.

This document describes repository practice and is not legal advice.
