from pymongo.collection import Collection
from typing import Any, Dict, Optional, Sequence, Tuple, Union


class Cursor(object):

    def __init__(
        self, collection: Collection,
        filter: Optional[Dict[str, Any]],
        *args: Any, **kwargs: Any) -> None: ...

    def __getitem__(self, index: int) -> Dict[str, Any]: ...

    def next(self) -> Dict[str, Any]: ...

    def limit(self, limit: int) -> None: ...

    def distinct(self, key: str) -> Sequence[Any]: ...

    def sort(
        self, key_or_list: Union[str, Sequence[Tuple[str, int]]],
        direction: Optional[int] = None) -> None: ...

    def count(self, with_limit_and_skip: bool = False) -> int: ...
