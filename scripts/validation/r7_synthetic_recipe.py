"""Create a read-only Snakemake parse fixture under an isolated scratch root."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_fixture(repo: Path):
    """Load the pinned repository fixture from its exact file path."""
    path = repo / "tests/canonical_v2_fresh_raw_fixture.py"
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Missing physical raw fixture module: {path}")
    spec = importlib.util.spec_from_file_location(
        "canonical_v2_fresh_raw_fixture", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import raw fixture module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_raw_fixture


def main() -> None:
    source = Path(sys.argv[1]).resolve(strict=True)
    root = Path(sys.argv[2]).resolve(strict=True)
    destination = root / "synthetic"
    recipe = _load_fixture(source)(
        repo=source,
        run=destination,
        dp_binary=source / ".pixi/build/progeny-native-release-gcc14.4/"
        "progeny-directional-glocal-bounded-dp-v2",
    )
    print(str(recipe))


if __name__ == "__main__":
    main()
