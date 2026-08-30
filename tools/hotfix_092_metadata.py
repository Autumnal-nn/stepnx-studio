from pathlib import Path


def repl(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if s.count(old) != count:
        raise SystemExit(f"unexpected source shape in {path}: {old[:60]!r}")
    p.write_text(s.replace(old, new), encoding="utf-8")

registry = "src/stepnx/authoring/trailer_registry.py"
repl(registry, '    TrailerFieldDefinition(1100, "Trailer string field 1100", TrailerEvidence.OFFICIAL_CORPUS),\n', '''    TrailerFieldDefinition(\n        1100,\n        "Localized mission text",\n        TrailerEvidence.OFFICIAL_CORPUS,\n        localized=True,\n    ),\n''')

profiles = "src/stepnx/core/profiles.py"
repl(profiles, '        (1100, "Trailer string field 1100", Evidence.OFFICIAL_CORPUS),\n', '        (1100, "Localized mission text", Evidence.OFFICIAL_CORPUS),\n')
repl(profiles, '        and base_id in (1103, 1203, 1303, 1403)\n', '        and base_id in (1100, 1103, 1203, 1303, 1403)\n')
repl(profiles, '''PRIME2_METADATA = (\n    *_direct_noteskin_metadata(32, "Prime 2"),\n''', '''PRIME2_METADATA = (\n    *_direct_noteskin_metadata(32, "Prime 2"),\n    MetadataDefinition(\n        20,\n        "BGA video resource (.V)",\n        _HEADER,\n        ValueKind.TRAILER_OFFSET,\n        Evidence.RUNTIME_CONFIRMED,\n        description=(\n            "Prime uses the same later-generation trailer-relative .V resource "\n            "reference as Fiesta. This explicit override prevents fallback to "\n            "NXA Header 20 (BGA OFF / COSMOS), which is a different semantic."\n        ),\n        authorable=False,\n    ),\n''')

print("metadata patch applied")