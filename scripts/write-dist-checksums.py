"""Write deterministic SHA-256 checksums for release distributions."""

from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"))
    return parser.parse_args()


def write_checksums(dist: Path) -> Path:
    """Write checksums for the release wheel and source distribution."""
    wheels = sorted(dist.glob("marimo_studio-*.whl"))
    sdists = sorted(dist.glob("marimo_studio-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError(f"Expected one wheel and one source distribution in {dist}")
    output = dist / "SHA256SUMS"
    distributions = sorted((*wheels, *sdists), key=lambda path: path.name)
    lines = [
        f"{sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in distributions
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> None:
    print(write_checksums(_arguments().dist))


if __name__ == "__main__":
    main()
