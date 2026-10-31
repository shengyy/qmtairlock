"""Check source size, current documentation links and repository entry points."""

import re
import subprocess
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "README.md",
    "README.zh-CN.md",
    "PRODUCT.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
    ".gitattributes",
}
DIRECTORIES = {"src", "scripts", "tests", "docs", ".github"}


def check():
    errors = []
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True
    ).splitlines()
    for name in paths:
        path = Path(name)
        if len(path.parts) == 1 and name not in ROOT_FILES:
            errors.append("unexpected root file: " + name)
        if len(path.parts) > 1 and path.parts[0] not in DIRECTORIES:
            errors.append("unexpected directory: " + name)
    sizes = {}
    for directory in ("src", "scripts", "tests"):
        for path in (ROOT / directory).rglob("*.py"):
            count = len(path.read_text().splitlines())
            sizes[str(path.relative_to(ROOT))] = count
            if count > 800:
                errors.append("%s has %d lines; split by responsibility" % (path, count))
    if len((ROOT / "AGENTS.md").read_text().splitlines()) > 60:
        errors.append("AGENTS.md must have at most 60 lines")
    for path in (ROOT / "docs").glob("*"):
        if path.name != "README.md" and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md", path.name):
            errors.append("invalid docs name: " + path.name)
    for path in list(ROOT.glob("*.md")) + list((ROOT / "docs").rglob("*.md")):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if ":" in target or target.startswith("#"):
                continue
            if not (path.parent / target.split("#")[0]).exists():
                errors.append("broken link in %s: %s" % (path.name, target))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    declared = (ROOT / "src/qmtairlock/version.py").read_text()
    if not re.search(r'__version__\s*=\s*[\'"]' + re.escape(version) + r'[\'"]', declared):
        errors.append("package versions differ")
    if errors:
        raise SystemExit("\n".join(errors))
    largest = max(sizes, key=sizes.get)
    print(
        "%d Python files; largest %s: %d lines; repository and documentation checks passed"
        % (len(sizes), largest, sizes[largest])
    )


if __name__ == "__main__":
    check()
