# Build, test and CI

English | [日本語](BUILD_JA.md)

Install Python 3.10 or later and build tools, then run:

```sh
python -m pip install --upgrade build wheel twine
python -m pip install python-osc matplotlib
python scripts/gen_api_doc.py --check
python -m unittest discover -s tests
python -m build
python -m twine check --strict dist/*.whl dist/*.tar.gz
python -m pip install dist/contactglovesdk-X.Y.Z-py3-none-any.whl
python examples/test_smoke.py
python scripts/make_dist_package.py --skip-build
python scripts/check_dist_licenses.py
```

Replace `X.Y.Z` with the built version. The smoke test does not require DivingStation. `examples/basic_usage.py` and `examples/simple_receive.py` require a running DivingStation and connected glove. See the viewer README for its setup.

Alternatively, use `uv sync` to install dependencies. To build only the wheel, run `python -m build --wheel`; it produces `dist/contactglovesdk-X.Y.Z-py3-none-any.whl`.

CI runs these checks, builds a wheel and sdist, and retains the customer ZIP and its SHA-256 file as an Actions artifact; it does not publish a release. The ZIP contains the wheel, both root READMEs, examples, generated API reference and license documents. `--skip-build` requires exactly one matching wheel in `dist/`. Without that option the script builds the wheel after checking the API reference.

The files are `dist/ContactGloveSDKv2Python-X.Y.Z.zip` and its `.zip.sha256`. CI names the artifact `ContactGloveSDKv2Python-<commit SHA>`; retention follows repository Actions settings. The artifact does not include the sdist or the full repository. The ZIP excludes internal or CI-only material including `examples/test_smoke.py`; the pure Python wheel contains the code needed at runtime.

When staging the ZIP, README language, license and API links are rewritten to bundled files for offline use. The development-guide link is omitted because maintainer documentation is not bundled. Repository READMEs and wheel metadata retain absolute URLs for PyPI.

ZIP timestamps, permissions and order are normalized. For reproducible wheel and ZIP comparisons, use the same OS, Python, zlib and build tool versions and set `SOURCE_DATE_EPOCH` to the same value. The checksum file refers to the customer ZIP itself, not the enclosing Actions artifact.
