# Contributing to Edison

Thanks for your interest in contributing!

## Getting started

1. Fork and clone the repository.
2. Install the tooling:

   ```bash
   uv tool install tox --with tox-uv
   uv tool install prek==0.4.10
   ```

## Making changes

- Create a branch for your change.
- Add or update tests in `tests/` for any behavior change.
- Update `CHANGELOG.md` for user-visible changes.
- Follow the existing code style (`ruff` and `black`, line length 88).

## Checks

Run the tests and the pre-commit suite before opening a pull request:

```bash
tox -e py
prek run --all-files
```

Coverage is enforced at 90% minimum; run `tox -e coverage` to see a report.

## Pull requests

- Keep pull requests focused on a single change.
- Describe what changed and why.
- Make sure CI passes (tests on CPython 3.12 and 3.14 across Linux, Windows, and macOS).

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
