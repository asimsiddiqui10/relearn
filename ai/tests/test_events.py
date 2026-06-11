"""Event serialization — data must be a JSON string (sse-starlette str()s
non-strings into Python repr, which the browser's JSON.parse can't read)."""

import json

from relearn_ai.agent import events as ev


def test_sse_data_is_valid_json_string():
    e = ev.tool_started("c1", "search_chunks", 'Searching "x"…', {"query": "x"})
    e.seq = 7
    frame = e.sse()
    assert frame["event"] == "tool_started"
    assert isinstance(frame["data"], str)  # NOT a dict
    parsed = json.loads(frame["data"])  # must be strict JSON
    assert parsed["seq"] == 7
    assert parsed["tool"] == "search_chunks"


def test_citation_map_round_trips():
    e = ev.citation_map({"E1": {"page": 1, "bbox": [1, 2, 3, 4]}})
    parsed = json.loads(e.sse()["data"])
    assert parsed["map"]["E1"]["bbox"] == [1, 2, 3, 4]
