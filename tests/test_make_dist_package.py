import hashlib
import importlib.util
import os
import re
from pathlib import Path
from posixpath import normpath
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "make_dist_package", ROOT / "scripts" / "make_dist_package.py"
)
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class DistributionPackagingTests(unittest.TestCase):
    def test_requires_exactly_one_wheel(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            packaging, "DIST_DIR", Path(tmp)
        ):
            with self.assertRaises(SystemExit):
                packaging.find_wheel()
            wheel = Path(tmp) / "contactglovesdk-1.0.0-py3-none-any.whl"
            wheel.touch()
            self.assertEqual(packaging.find_wheel(), wheel)
            (Path(tmp) / "contactglovesdk-0.2.0-py3-none-any.whl").touch()
            with self.assertRaisesRegex(SystemExit, "exactly one"):
                packaging.find_wheel()

    def test_zip_is_reproducible_despite_input_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            stage.mkdir()
            for name in ("b.txt", "a.txt"):
                (stage / name).write_text(name, encoding="utf-8")
            first = Path(tmp) / "first.zip"
            second = Path(tmp) / "second.zip"
            packaging.make_zip(stage, "package", first)
            for path in stage.iterdir():
                os.utime(path, (1800000000, 1800000000))
                path.chmod(0o600)
            packaging.make_zip(stage, "package", second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(archive.namelist(), ["package/a.txt", "package/b.txt"])
                for info in archive.infolist():
                    self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(info.external_attr >> 16, 0o100644)

    def test_customer_bundle_allowlist_and_checksum(self):
        # An explicit list prevents new repository files from silently leaking.
        expected = {
            "README.md", "README_JA.md",
            "contactglovesdk-1.0.0-py3-none-any.whl",
            "examples/basic_usage.py", "examples/simple_receive.py",
            "examples/viewer/README.md", "examples/viewer/README_EN.md",
            "examples/viewer/server.py", "examples/viewer/viewer.py",
            "examples/viewer/fig1.png", "examples/viewer/fig2.png",
            "doc/api.md", "doc/LICENSE.md", "doc/NOTICE.md",
            "doc/THIRD_PARTY_NOTICES.md",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            packaging, "DIST_DIR", Path(tmp)
        ), patch.object(sys, "argv", ["make_dist_package.py", "--skip-build", "--skip-doc-check"]):
            wheel = Path(tmp) / "contactglovesdk-1.0.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel fixture")
            self.assertEqual(packaging.main(), 0)
            output = Path(tmp) / "ContactGloveSDKv2Python-1.0.0.zip"
            prefix = output.stem + "/"
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), {prefix + p for p in expected})
                self.assertEqual(archive.read(prefix + wheel.name), wheel.read_bytes())
                for path in ("examples/viewer/README.md", "examples/viewer/README_EN.md"):
                    self.assertNotIn(b"test_data", archive.read(prefix + path))
                    self.assertEqual(archive.read(prefix + path), (ROOT / path).read_bytes())
                for path in ("LICENSE.md", "NOTICE.md", "THIRD_PARTY_NOTICES.md"):
                    self.assertEqual(archive.read(prefix + "doc/" + path), (ROOT / path).read_bytes())
                self.assertIn("Python 3.10以上", archive.read(prefix + "README_JA.md").decode())
                self.assertIn(b"Python 3.10 or later", archive.read(prefix + "README.md"))
                for locale, filename in (("ja", "README_JA.md"), ("en", "README.md")):
                    readme = archive.read(prefix + filename).decode()
                    url = f"https://docs.melt-interface-technologies.com/{locale}/docs/contact/sdks/contact-glove-v2-python"
                    self.assertIn(url, readme)
                    self.assertIn("(doc/api.md)", readme)
                    self.assertIn("python -m pip install ./contactglovesdk-", readme)
                    contact_url = (
                        "https://melt-interface-technologies.com/en/contact/"
                        if locale == "en" else "https://melt-interface-technologies.com/contact/"
                    )
                    self.assertIn(contact_url, readme)
                    self.assertNotIn("github.com/", readme)
                    for target in re.findall(r"\]\(([^)]+)\)", readme):
                        if not target.startswith("https://"):
                            self.assertIn(prefix + normpath(target), archive.namelist())
                    other = "README_JA.md" if locale == "en" else "README.md"
                    self.assertIn(f"({other})", readme)
                    for legal in ("LICENSE.md", "NOTICE.md", "THIRD_PARTY_NOTICES.md"):
                        self.assertIn(f"(doc/{legal})", readme)
                    # Staging must not change the absolute links used by PyPI.
                    source = (ROOT / filename).read_text(encoding="utf-8")
                    self.assertIn("https://github.com/", source)
                    self.assertIn(url + "/api", source)
                self.assertIn(b"Python 3.10 or later", archive.read(prefix + "doc/api.md"))
            checksum = output.with_suffix(".zip.sha256").read_text(encoding="ascii")
            self.assertEqual(checksum, f"{hashlib.sha256(output.read_bytes()).hexdigest()}  {output.name}\n")


if __name__ == "__main__":
    unittest.main()
