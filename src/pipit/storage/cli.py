"""``pipit-list``: import, export, check, back up and undo lists from the command line.

pipit-list import List.bsxm ~/.local/share/pipit/lists/List.pipit
pipit-list export List.pipit Copy.bsxm
pipit-list check List.pipit
pipit-list backup List.pipit
pipit-list undo List.pipit            (and redo)
pipit-list restore List.pipit BACKUP.zip
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pipit.bsxm.upgrades import UpgradeRefusedError
from pipit.config import paths
from pipit.datapack.pack import DataPack, PackError
from pipit.domain.locations import PredefinedLocations
from pipit.storage import backup, integrity
from pipit.storage.database import ListDatabase
from pipit.storage.lists import ImportFailedError, export_bsxm, import_bsxm


def find_pack(explicit: Path | None) -> Path:
    """The pack to use: --pack, else the newest in the packs folder or ./datapacks."""
    if explicit is not None:
        return explicit
    candidates = sorted(paths.packs_dir().glob("pipit-pack-*.sqlite"))
    candidates += sorted(Path("datapacks").glob("pipit-pack-*.sqlite"))
    if not candidates:
        raise PackError("no data pack found; build one with pipit-build-pack or pass --pack")
    return candidates[-1]


def _base(pack_path: Path) -> tuple[str, set[str]]:
    with DataPack(pack_path) as pack:
        ids = {
            row[0]
            for row in pack.connection.execute(
                "SELECT id FROM taxa WHERE taxonomy_id = ?", (pack.base_taxonomy_id,)
            )
        }
        return pack.base_taxonomy_id, ids


def _predefined(pack_path: Path) -> PredefinedLocations:
    with DataPack(pack_path) as pack:
        return pack.predefined_locations()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipit-list", description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--pack", type=Path, help="data pack (default: the newest installed)")
    parser.add_argument("--backups", type=Path, default=None,
                        help="backups folder (default: ~/.local/share/pipit/backups)")  # fmt: skip
    commands = parser.add_subparsers(dest="command", required=True)
    imported = commands.add_parser("import", help="create a list from a Scythebill .bsxm")
    imported.add_argument("source", type=Path)
    imported.add_argument("target", type=Path)
    exported = commands.add_parser("export", help="write a list as a Scythebill .bsxm")
    exported.add_argument("list", type=Path)
    exported.add_argument("target", type=Path)
    simple_commands = (
        ("check", "run every integrity check"),
        ("backup", "make a backup now"),
        ("undo", "undo the last change"),
        ("redo", "redo the last undo"),
    )
    for name, help_text in simple_commands:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("list", type=Path)
    restored = commands.add_parser("restore", help="replace a list with a backup")
    restored.add_argument("list", type=Path)
    restored.add_argument("backup", type=Path)
    args = parser.parse_args(argv)
    backups_root = args.backups or paths.backups_dir()

    try:
        if args.command == "import":
            base_id, ids = _base(find_pack(args.pack))
            result = import_bsxm(
                args.source, args.target, base_id, ids, _predefined(find_pack(args.pack))
            )
            print(f"imported {result.sightings} sightings, {result.locations} locations and "
                  f"{result.visits} visits into {result.list_path}")  # fmt: skip
            for warning in result.warnings:
                print(f"  note: {warning}")
            return 0
        if args.command == "restore":
            if args.list.exists():
                with ListDatabase.open(args.list, read_only=True) as current:
                    kept = backup.snapshot(current.connection, args.list, backups_root, "restore")
                print(f"current list saved as {kept}")
            backup.restore(args.backup, args.list)
            print(f"restored {args.list} from {args.backup.name}")
            return 0
        read_only = args.command in ("export", "check")
        with ListDatabase.open(args.list, read_only=read_only) as database:
            if args.command == "export":
                size = export_bsxm(database, args.target)
                print(f"wrote {args.target} ({size} bytes)")
            elif args.command == "check":
                problems = integrity.check(database.connection, _base(find_pack(args.pack))[1],
                                           full=True)  # fmt: skip
                for problem in problems:
                    print(f"problem: {problem}")
                print("OK" if not problems else f"{len(problems)} problems")
                return 0 if not problems else 1
            elif args.command == "backup":
                made = backup.snapshot(database.connection, args.list, backups_root, "manual")
                print(f"backed up to {made}")
            else:
                label = database.undo() if args.command == "undo" else database.redo()
                print(f"{args.command}: {label}" if label else f"nothing to {args.command}")
        return 0
    except (
        ImportFailedError,
        UpgradeRefusedError,
        PackError,
        FileExistsError,
        FileNotFoundError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
