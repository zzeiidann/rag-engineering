import pytest

from tests.fakes import offline_service


@pytest.fixture
def service(tmp_path):
    return offline_service(tmp_path)
