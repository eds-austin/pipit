"""Importing sightings from other programs' files, as Scythebill does (M6).

Ported from Scythebill's ``ui/src/main/java/com/scythebill/birdlist/ui/imports``: the importer
reads a file into places, taxa and sightings in memory (``SightingsImporter`` and its
subclasses), the controller asks what to do with dates already in the list and with
duplicates, then adds everything and tidies up (``ImportController``). Pipit runs the same
steps on a list loaded into memory, shows what will change, and stores the result as one
undoable step.
"""
