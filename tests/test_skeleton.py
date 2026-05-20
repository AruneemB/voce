import importlib
import pytest


MODULES = [
    "voce",
    "voce.config",
    "voce.db",
    "voce.models",
    "voce.feeds",
    "voce.article",
    "voce.tts",
    "voce.cache",
    "voce.scheduler",
    "voce.api",
]


@pytest.mark.parametrize("module_path", MODULES)
def test_module_imports_without_error(module_path: str) -> None:
    """Every voce module must be importable with no side-effect errors."""
    mod = importlib.import_module(module_path)
    assert mod is not None


def test_package_version() -> None:
    """voce.__version__ must be the string '0.1.0'."""
    import voce
    assert voce.__version__ == "0.1.0"
