# Repository rename: AI Software Toolkit

The canonical repository is now
[ravisingh11/ai-software-toolkit](https://github.com/ravisingh11/ai-software-toolkit),
formerly `ravisingh11/engineering-standards`.

This changes the repository address, not the Guardrails runtime, policy
schemas, skill names, or Spec Kit preset identifiers. Existing tags and Git
history remain in the same repository. Local directories do not need renaming.

## Clones and forks

Existing forks remain connected and keep their own names. For a direct clone,
update the origin remote:

```sh
git remote set-url origin https://github.com/ravisingh11/ai-software-toolkit.git
git fetch origin
```

For a clone of your own fork, keep `origin` pointing to that fork. If its
upstream remote is named `upstream`, update that remote instead:

```sh
git remote set-url upstream https://github.com/ravisingh11/ai-software-toolkit.git
git fetch upstream
```

Inspect `git remote -v` first and use your actual remote name. GitHub redirects
ordinary Git operations and repository links from the old address. Do not
create a new repository at the old address: that would remove the redirect.
See [GitHub's rename guidance](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).

## Workflows and installations

Search your repository, scripts, and CI configuration for the old owner/name.
Update direct `uses:` references to the new repository path, retaining the
intended tag or commit pin. GitHub Actions does not follow repository redirects
for actions or reusable workflows, including references pinned to a commit.
See [GitHub's workflow reference](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations).

Review explicit checkout repositories, download URLs, provider project
bindings, and repository allowlists too. Copied `.guardrails/` runtime files
and installed skills do not need replacing merely because of this rename;
update any embedded references that actually address the upstream repository.
The runtime's evidence remains tied to its original subject and provenance.

## Pages and badges

The canonical scorecard site is
[AI Software Toolkit scorecard](https://ravisingh11.github.io/ai-software-toolkit/)
and its badge is
[guardrails-badge.svg](https://ravisingh11.github.io/ai-software-toolkit/guardrails-badge.svg).
Update bookmarks and embedded badges. The old project Pages URL is not covered
by repository redirects. Fork-owned Pages sites keep their own repository URLs.

The latest-PR badge requires a successful publisher run after the rename.
Existing evidence containing the old repository identity must not be relabeled
or treated as fresh proof for the renamed repository; allow trusted workflows
to collect and publish new evidence.
