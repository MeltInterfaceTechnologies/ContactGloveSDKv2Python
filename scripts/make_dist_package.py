"""Script that produces the zip package for distribution.

It builds the contactglovesdk wheel and bundles `README.md` and
`README_JA.md` (the Getting Started aimed at the distributed
package, in English and Japanese), `api.md`, the license documents and
`examples/` into a single zip for distribution, including through GitHub.

Usage::

    python scripts/make_dist_package.py
    python scripts/make_dist_package.py --skip-build   # use an existing dist/*.whl
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT / "dist"
PACKAGE_NAME = "ContactGloveSDKv2Python"

# Files and folders under examples that are left out of the distributed
# package (they are internal or CI only).
EXAMPLES_EXCLUDE_NAMES = {"test_smoke.py", "__pycache__", ".venv"}
EXAMPLES_EXCLUDE_SUFFIXES = (".pyc",)


def copy_bundle_readmes(stage_dir: Path) -> None:
    """Keep repository/PyPI URLs absolute, but make bundled navigation local."""
    source_base = "https://github.com/MeltInterfaceTechnologies/ContactGloveSDKv2Python/blob/main/"
    targets = {
        "README.md": "README.md",
        "README_JA.md": "README_JA.md",
        "LICENSE.md": "doc/LICENSE.md",
        "NOTICE.md": "doc/NOTICE.md",
        "THIRD_PARTY_NOTICES.md": "doc/THIRD_PARTY_NOTICES.md",
    }
    for locale, filename in (("en", "README.md"), ("ja", "README_JA.md")):
        text = (ROOT / filename).read_text(encoding="utf-8")
        # Maintainer guides are intentionally not included in customer bundles.
        text = "".join(
            line for line in text.splitlines(keepends=True)
            if source_base + "DEVELOPMENT" not in line
        )
        for source, target in targets.items():
            text = text.replace(f"({source_base}{source})", f"({target})")
        api_url = f"https://docs.melt-interface-technologies.com/{locale}/docs/contact/sdks/contact-glove-v2-python/api"
        text = text.replace(f"({api_url})", "(doc/api.md)")
        (stage_dir / filename).write_text(text, encoding="utf-8")


def run_check(args: list, *, cwd: Path) -> None:
    result = subprocess.run([sys.executable, *args], cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def check_api_doc_up_to_date() -> None:
    print("Checking api.md is up to date...")
    result = subprocess.run(
        [sys.executable, "scripts/gen_api_doc.py", "--check"], cwd=ROOT
    )
    if result.returncode != 0:
        print(
            "api.md is out of date. Run 'python scripts/gen_api_doc.py' and commit "
            "the result before packaging.",
            file=sys.stderr,
        )
        raise SystemExit(result.returncode)


def build_wheel() -> None:
    print("Building wheel...")
    try:
        run_check(["-m", "build", "--wheel"], cwd=ROOT)
    except FileNotFoundError:
        print(
            "'build' package not found. Install it with: "
            "python -m pip install --upgrade build",
            file=sys.stderr,
        )
        raise


def find_wheel() -> Path:
    wheels = sorted(DIST_DIR.glob("contactglovesdk-*-py3-none-any.whl"))
    if not wheels:
        raise SystemExit(
            f"No wheel found in {DIST_DIR}. Build it first "
            "(omit --skip-build, or run 'python -m build --wheel')."
        )
    if len(wheels) != 1:
        raise SystemExit(
            "Expected exactly one contactglovesdk wheel in dist/. "
            "Remove stale wheels before packaging."
        )
    return wheels[0]


def parse_version(wheel_path: Path) -> str:
    match = re.match(r"contactglovesdk-([^-]+)-py3-none-any\.whl", wheel_path.name)
    if not match:
        raise SystemExit(f"Could not parse version from wheel name: {wheel_path.name}")
    return match.group(1)


def copy_examples(stage_dir: Path) -> None:
    dest = stage_dir / "examples"

    def ignore(dir_: str, names: list) -> set:
        skip = set()
        for name in names:
            if name in EXAMPLES_EXCLUDE_NAMES or name.endswith(EXAMPLES_EXCLUDE_SUFFIXES):
                skip.add(name)
        return skip

    shutil.copytree(ROOT / "examples", dest, ignore=ignore)


def copy_doc(stage_dir: Path) -> None:
    doc_dir = stage_dir / "doc"
    doc_dir.mkdir(parents=True, exist_ok=True)
    for name in ("api.md", "LICENSE.md", "NOTICE.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, doc_dir / name)


def make_zip(stage_dir: Path, package_root_name: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(stage_dir.rglob("*")):
            if path.is_dir():
                continue
            arcname = (Path(package_root_name) / path.relative_to(stage_dir)).as_posix()
            # Stable timestamps and permissions make identical inputs byte-identical.
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())


def write_checksum(output_path: Path) -> Path:
    """Hash the customer ZIP, not the outer GitHub Actions artifact archive."""
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    checksum_path = output_path.with_suffix(output_path.suffix + ".sha256")
    checksum_path.write_bytes(f"{digest}  {output_path.name}\n".encode("ascii"))
    return checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="use an existing wheel in dist/ instead of rebuilding it",
    )
    parser.add_argument(
        "--skip-doc-check",
        action="store_true",
        help="skip the check that verifies api.md is up to date",
    )
    args = parser.parse_args()

    if not args.skip_doc_check:
        check_api_doc_up_to_date()

    if not args.skip_build:
        build_wheel()

    wheel_path = find_wheel()
    version = parse_version(wheel_path)
    package_root_name = f"{PACKAGE_NAME}-{version}"

    with tempfile.TemporaryDirectory(prefix="contactglovesdk-package-") as tmp:
        stage_dir = Path(tmp) / package_root_name
        stage_dir.mkdir()

        copy_bundle_readmes(stage_dir)
        shutil.copy2(wheel_path, stage_dir / wheel_path.name)
        copy_examples(stage_dir)
        copy_doc(stage_dir)

        output_path = DIST_DIR / f"{package_root_name}.zip"
        make_zip(stage_dir, package_root_name, output_path)

    checksum_path = write_checksum(output_path)
    print(f"Wrote {output_path}")
    print(f"Wrote {checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
