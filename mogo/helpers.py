from collections.abc import Mapping
from typing import Any, Optional, TypeVar


T = TypeVar("T")
Document = Mapping[str, Any]


def check_none(value: Optional[T]) -> T:
    if value is None:
        raise ValueError("Value is unexpectedly None.")
    return value
