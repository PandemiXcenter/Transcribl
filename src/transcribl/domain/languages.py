"""Language identity for user-entered names; preserve original wording in storage."""

from typing import Annotated

from pydantic import Field, StringConstraints

LanguageName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), Field(max_length=100)
]


def same_language(left: str | None, right: str) -> bool:
    return left is not None and left.strip().casefold() == right.strip().casefold()
