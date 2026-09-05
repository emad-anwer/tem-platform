import base64
import binascii
import json
from typing import Any


def encode_cursor(values: list[Any]) -> str:
    payload = json.dumps(values, separators=(",", ":"))

    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)

        payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")

        values = json.loads(payload)

        if not isinstance(values, list):
            raise TypeError("Cursor payload must be a list.")

        return values

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        binascii.Error,
    ) as exc:
        raise ValueError("Invalid cursor.") from exc
