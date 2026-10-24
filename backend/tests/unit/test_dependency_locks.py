"""The clean CI environment must contain all declared runtime dependencies."""

from scripts.check_dependency_locks import check_locks


def test_runtime_and_ci_locks_include_all_direct_dependencies():
    assert check_locks() == []
