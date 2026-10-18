import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.execution import normalize_desktop_request, remember_windows
from backend.desktop_worker import execute_connected, inspection_result

TITLE = "Budget - Google Sheets - Google Chrome"


def test_exact_observed_title_replaces_model_omission_without_mutating_input():
    args = {"tool": "type", "arguments": {"text": "B26", "target_window_id": 7},
            "window_title": "Budget - Google Chrome", "reason": "Select total"}
    name, fixed = normalize_desktop_request("zavora", args, {7: TITLE})
    assert name == "zavora"
    assert fixed["window_title"] == TITLE
    assert args["window_title"] == "Budget - Google Chrome"
    assert fixed["arguments"] == args["arguments"]


def test_native_query_mistake_uses_supported_label_or_value_search():
    name, args = normalize_desktop_request("zavora", {
        "tool": "find_element", "arguments": {"window_id": 7, "query": "B26", "role": "AXTextField"},
        "window_title": "Budget", "reason": "Locate cell"}, {7: TITLE})
    assert name == "find_elements"
    assert args == {"window_id": 7, "window_title": TITLE, "query": "B26", "role": "AXTextField"}


def test_window_refresh_invalidates_inspection_when_tab_changes_or_window_disappears():
    titles, inspected = {7: TITLE, 8: "Old"}, {7, 8}
    remember_windows(titles, inspected, [{"windowId": 7, "title": "Different document - Google Chrome"}])
    assert titles == {7: "Different document - Google Chrome"}
    assert not inspected


def test_real_live_tab_change_is_still_rejected_before_typing():
    calls = []
    class Client:
        tools = {"type": object()}
        async def call(self, name, args):
            calls.append(name)
            return {"windows": [{"windowId": 7, "title": "Different document - Google Chrome"}]}
    with pytest.raises(ValueError, match="identity changed"):
        asyncio.run(execute_connected(Client(), "zavora", {
            "tool": "type", "arguments": {"target_window_id": 7, "text": "=SUM(B19:B25)"},
            "window_title": TITLE, "reason": "Update total"}))
    assert calls == ["list_windows"]


def test_large_inspection_preserves_valid_json_and_deep_formula_controls():
    tree = {"role": "AXWindow", "children": [
        {"role": "AXGroup", "label": "x" * 1000} for _ in range(60)] + [
        {"role": "AXTextField", "label": "Name box", "value": "B26"},
        {"role": "AXTextField", "label": "", "value": "=SUM(B19:B25)"}]}
    result = inspection_result(tree, 7)
    assert len(result["tree"]) <= 20000
    compact = json.loads(result["tree"])
    assert result["truncated"]
    assert any(e.get("value") == "=SUM(B19:B25)" for e in compact["elements"])
    assert compact["omitted_elements"] >= 0
