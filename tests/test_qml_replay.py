from __future__ import annotations

import pytest

from memoryhub_qml.replay import ReplayError, mask_for_display, parse_replay


def test_parse_replay_and_mask_sensitive_values():
    replay = parse_replay(
        {
            "schema_version": "conversation-replay/1.0",
            "session_id": "test",
            "turns": [
                {
                    "turn_id": "turn_1",
                    "user_message": "联系 13812345678 或 test@example.com",
                    "assistant_message": "ok",
                    "tool_calls": [
                        {
                            "call_id": "call_1",
                            "tool_name": "search",
                            "sequence": 1,
                            "result": {"token": "Bearer abcdefghijklmnop"},
                        }
                    ],
                }
            ],
        }
    )
    assert "[REDACTED_PHONE]" in replay["turns"][0]["user_message"]
    assert "[REDACTED_EMAIL]" in replay["turns"][0]["user_message"]
    assert "[REDACTED_TOKEN]" in replay["turns"][0]["tool_calls"][0]["result"]["token"]


@pytest.mark.parametrize(
    "turn, expected",
    [
        ({"user_message": "missing"}, "turn_id"),
        (
            {
                "turn_id": "t1",
                "tool_calls": [
                    {"call_id": "x", "sequence": 1},
                    {"call_id": "x", "sequence": 2},
                ],
            },
            "call_id",
        ),
        (
            {
                "turn_id": "t1",
                "tool_calls": [
                    {"call_id": "x", "sequence": 2},
                    {"call_id": "y", "sequence": 1},
                ],
            },
            "sequence",
        ),
    ],
)
def test_replay_validation_errors_are_locatable(turn, expected):
    with pytest.raises(ReplayError, match=expected):
        parse_replay({"schema_version": "conversation-replay/1.0", "turns": [turn]})


def test_mask_for_display_is_recursive():
    value = mask_for_display({"nested": ["mail me at a@b.com", "13812345678"]})
    assert value == {"nested": ["mail me at [REDACTED_EMAIL]", "[REDACTED_PHONE]"]}
