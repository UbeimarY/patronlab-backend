"""PatronLab: pattern editor API for artisans."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version() -> str:
    try:
        return version("patronlab")
    except PackageNotFoundError:
        # Running from source (CI and the Docker image): read it from pyproject.toml.
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        return str(tomllib.loads(pyproject.read_text())["project"]["version"])


__version__ = _version()
