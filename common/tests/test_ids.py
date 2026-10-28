import re

from common.ids import new_id, short_id


def test_short_id_format() -> None:
    assert re.fullmatch(r"c_[0-9a-f]{8}", short_id())
    assert short_id("r_").startswith("r_")


def test_new_id_unique() -> None:
    assert new_id() != new_id()
