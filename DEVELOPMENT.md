# Development

English | [日本語](DEVELOPMENT_JA.md)

This guide is for maintainers working from source. For installation and usage, see [README](README.md).

- [Build, tests, CI and distribution](docs/BUILD.md)

The API reference `api.md` is generated from docstrings using `python scripts/gen_api_doc.py`. Its introduction comes from the package module docstring in `contactglovesdk/__init__.py`; the reference comes from class, enum, exception and method docstrings. The generator uses Python's standard library, not pdoc. Run `python scripts/gen_api_doc.py --check` to verify it; CI fails if it is missing or stale.
