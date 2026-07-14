import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.getenv("MXS_TEST_PORT"):
        return
    marker = pytest.mark.skip(reason="set MXS_TEST_PORT to run connected-device tests")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(marker)
