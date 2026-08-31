# Contributing

The project is developed milestone by milestone. Keep each change narrow, testable, and connected to an explicit research or engineering requirement.

## Workflow

1. Confirm the active milestone in `docs/milestones.md`.
2. Create a focused branch.
3. Add or update tests with the implementation.
4. Run formatting, linting, compilation, and tests.
5. Update relevant documentation and architecture decisions.
6. Keep generated datasets, model weights, indexes, and secrets out of Git.

## Publishing boundary

`AGENTS.md`, local agent state, virtual environments, credentials, scratch files, downloaded benchmark files, and generated data/reports are intentionally Git-ignored. Keep `.env.example`, source code, tests with tiny invented synthetic fixtures, and reviewed documentation publishable. Do not use `git add -f` to bypass these boundaries.

Before your manual commit, run `git status --short` and inspect the staged diff. `.gitignore` does not untrack previously committed files; check `git ls-files AGENTS.md` if starting from another clone. Local instructions must not be linked as if they were a published documentation file.

## Commit guidance

Prefer focused commits such as:

```text
feat(ingestion): add paginated study fetcher
test(criteria): cover negated exclusion clauses
docs(eval): define eligible-trial recall
```

## Pull request checklist

- [ ] The change belongs to the active milestone.
- [ ] No real patient information is present.
- [ ] Tests cover important behavior.
- [ ] Data and model provenance are preserved.
- [ ] Documentation reflects the new behavior.
- [ ] Generated or large artifacts are not committed.
- [ ] Medical limitations are not overstated.
