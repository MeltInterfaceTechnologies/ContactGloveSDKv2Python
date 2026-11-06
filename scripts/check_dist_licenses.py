"""Verify license metadata and documents in the built wheel, sdist and ZIP."""

from email.parser import BytesParser
from pathlib import Path
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = ("LICENSE.md", "NOTICE.md", "THIRD_PARTY_NOTICES.md")


def check_no_old_legal(names):
    for name in names:
        lowered = name.lower()
        assert "/legal/" not in lowered, name
        assert "privacypolicy" not in lowered, name
        assert "termofuse" not in lowered, name
        assert "divingstationprotocolspecs" not in lowered, name


def check_metadata(data):
    metadata = BytesParser().parsebytes(data)
    assert metadata["License-Expression"] == "Apache-2.0"
    assert set(metadata.get_all("License-File", [])) == set(DOCUMENTS)


def check_documents(read, prefix):
    for name in DOCUMENTS:
        assert read(prefix + name) == (ROOT / name).read_bytes(), name


def main():
    dist = ROOT / "dist"
    wheels = list(dist.glob("contactglovesdk-*-py3-none-any.whl"))
    sdists = list(dist.glob("contactglovesdk-*.tar.gz"))
    bundles = list(dist.glob("ContactGloveSDKv2Python-*.zip"))
    assert len(wheels) == len(sdists) == len(bundles) == 1, (
        "Build exactly one wheel, sdist and distribution ZIP in dist/ first"
    )
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        check_no_old_legal(names)
        metadata_path, = [name for name in names if name.endswith(".dist-info/METADATA")]
        prefix = metadata_path.removesuffix("METADATA")
        check_metadata(wheel.read(metadata_path))
        check_documents(wheel.read, prefix + "licenses/")
    with tarfile.open(sdists[0]) as sdist:
        check_no_old_legal(sdist.getnames())
        prefix = sdists[0].name.removesuffix(".tar.gz") + "/"

        def read(name):
            return sdist.extractfile(name).read()

        check_metadata(read(prefix + "PKG-INFO"))
        check_documents(read, prefix)
    with zipfile.ZipFile(bundles[0]) as bundle:
        check_no_old_legal(bundle.namelist())
        prefix = bundles[0].stem + "/"
        check_documents(bundle.read, prefix + "doc/")
        assert bundle.read(prefix + wheels[0].name) == wheels[0].read_bytes()
    print("Verified Apache-2.0 metadata, preserved notices and no old legal files in wheel, sdist and ZIP")


if __name__ == "__main__":
    main()
