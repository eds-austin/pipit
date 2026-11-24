"""``pipit-build-pack``: build or validate a data pack from a Scythebill checkout.

pipit-build-pack --scythebill ~/Projects/scythebill-birdlist --out datapacks
pipit-build-pack --validate datapacks/pipit-pack-2026.1.sqlite --scythebill ...
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from pipit.packbuild.build import build_pack
from pipit.packbuild.sources import ScythebillSources, SourceError
from pipit.packbuild.validate import format_report, validate

DEFAULT_SCYTHEBILL = Path.home() / "Projects" / "scythebill-birdlist"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipit-build-pack", description=__doc__.split("\n")[0])
    parser.add_argument("--scythebill", type=Path, default=DEFAULT_SCYTHEBILL,
                        help="Scythebill checkout (default: %(default)s)")  # fmt: skip
    parser.add_argument("--out", type=Path, default=Path("datapacks"), help="output folder")
    parser.add_argument("--revision", type=int, default=1, help="pack revision within the year")
    parser.add_argument("--validate", type=Path, metavar="PACK", help="only validate PACK")
    parser.add_argument(
        "--no-sources",
        action="store_true",
        help="validate the pack on its own, without the Scythebill checkout",
    )
    args = parser.parse_args(argv)

    sources = None if args.no_sources else ScythebillSources(args.scythebill.expanduser())
    try:
        if args.validate:
            pack = args.validate
        else:
            assert sources is not None
            started = time.perf_counter()
            pack = build_pack(sources, args.out, args.revision)
            print(f"built {pack} in {time.perf_counter() - started:.1f}s")
        report = validate(pack, sources)
    except SourceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
