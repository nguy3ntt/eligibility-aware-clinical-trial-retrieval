# Contributing

Keep each change narrow, testable, and connected to an explicit research or engineering requirement.

## Workflow

1. Confirm the intended scope in an issue or design document.
2. Create a focused branch.
3. Add or update tests with the implementation.
4. Run formatting, linting, compilation, and tests.
5. Update relevant documentation and architecture decisions.
6. Keep generated datasets, model weights, indexes, and secrets out of Git.

## Publishing boundary

Local instructions and planning state, virtual environments, credentials, scratch files, downloaded benchmark files, and generated data/reports are intentionally Git-ignored. Keep `.env.example`, source code, tests with tiny invented synthetic fixtures, and reviewed technical documentation publishable. Do not use `git add -f` to bypass these boundaries.

Before committing, run `git status --short` and inspect the staged diff. `.gitignore` does not remove files that were already tracked, so verify the repository index when adopting these rules in an existing clone.

## Commit guidance

Prefer focused commits such as:

```text
feat(ingestion): add paginated study fetcher
test(criteria): cover negated exclusion clauses
docs(eval): define eligible-trial recall
```

## Pull request checklist

- [ ] The change stays within its documented scope.
- [ ] No real patient information is present.
- [ ] Tests cover important behavior.
- [ ] Data and model provenance are preserved.
- [ ] Documentation reflects the new behavior.
- [ ] Generated or large artifacts are not committed.
- [ ] Medical limitations are not overstated.
