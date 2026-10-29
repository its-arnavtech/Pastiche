import pytest

_REPORT: list[str] = []


@pytest.fixture
def report():
    return _REPORT.append


def pytest_terminal_summary(terminalreporter):
    if _REPORT:
        terminalreporter.section("skip detector precision / recall")
        for line in _REPORT:
            terminalreporter.write_line(line)
