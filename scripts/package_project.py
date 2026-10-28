"""Create a portable source-and-evidence archive without environments or logs."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from modelshield.config import ROOT


def package():
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / "ModelShield-hackathon.zip"
    files = [
        ROOT / name
        for name in [
            "enthi.py",
            "README.md",
            "LICENSE",
            "start.ps1",
            "start.sh",
            "requirements.txt",
            "requirements-dev.txt",
            "requirements.in",
            "requirements-dev.in",
            "pytest.ini",
            ".gitignore",
        ]
    ]
    for directory in ["modelshield", "web", "scripts", "tests", "docs", "reports"]:
        files.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file()
            and "__pycache__" not in p.parts
            and p.suffix not in {".pyc", ".pyo"}
        )
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        for path in sorted(files):
            output.write(path, Path("ModelShield") / path.relative_to(ROOT))
    with ZipFile(archive) as check:
        assert check.testzip() is None
        assert all(
            "/.venv/" not in name and "/data/" not in name for name in check.namelist()
        )
    print(f"Created {archive} ({archive.stat().st_size:,} bytes; {len(files)} files)")


if __name__ == "__main__":
    package()
