## What does this change?

<!-- The why, not just the what. Link any related issue. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Refactor / internal

## Checklist

- [ ] `ruff check src tests` passes
- [ ] `mypy` passes
- [ ] `pytest --cov` passes, and new behaviour is covered by tests
- [ ] No test touches the real network
- [ ] Docs updated (`README.md` / `docs/`) if behaviour changed
- [ ] `CHANGELOG.md` updated
- [ ] No secret, token or personal hostname appears in the diff

## Security impact

<!-- Does this touch the SSRF guard, redaction, auth or the alert channels?
     If yes, explain the reasoning. If no, say "none". -->
