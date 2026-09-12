from __future__ import annotations

from stepnx.importers.ssc import parse_ssc


def test_importer_accepts_exporter_escaped_tag_values() -> None:
    data = rb"""#VERSION:0.83 xSanity;
#TITLE:Song\: The\; Remix;
#ARTIST:A\//B;
#MUSIC:a\#b.mp3;
#BPMS:0=120;
#NOTEDATA:;
#STEPSTYPE:pump-single;
#DESCRIPTION:S\;1;
#METER:1;
#NOTES:
10000
00000
00000
00000
;
"""
    result = parse_ssc(data, source="escaped.ssc")
    assert len(result.charts) == 1
    chart = result.charts[0]
    assert chart.default_filename == "S;1.NX"
    assert "S;1" in chart.label
