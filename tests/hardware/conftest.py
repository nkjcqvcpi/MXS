import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.getenv("X4CIR_HARDWARE") == "1":
        return
    marker = pytest.mark.skip(reason="set X4CIR_HARDWARE=1 to run connected-device tests")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(marker)
