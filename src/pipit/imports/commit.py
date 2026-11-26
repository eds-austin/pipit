"""Storing a finished import in the list: one undoable action, checked to export exactly as
the import's result, else nothing is stored."""

from __future__ import annotations

from pipit.bsxm.writer import write_bsxm
from pipit.imports.session import ImportOutcome, ImportRun
from pipit.storage.database import ListDatabase
from pipit.storage.import_ops import store_import
from pipit.storage.repository import load_report


class ImportStoreError(RuntimeError):
    """The stored list didn't come out as the import's result; nothing was changed."""


def store(database: ListDatabase, run: ImportRun, outcome: ImportOutcome, label: str) -> None:
    expected = write_bsxm(run.report)
    with database.action(label) as connection:
        store_import(connection, run.report, run.original_sightings, outcome.removed,
                     outcome.added)  # fmt: skip
        if write_bsxm(load_report(connection)) != expected:
            raise ImportStoreError("the stored list does not export as the import made it")
