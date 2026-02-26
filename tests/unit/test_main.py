"""Bug condition exploration tests — Application Factory Pattern (Gap 5).

**Validates: Requirements 1.17, 1.18**

These tests MUST FAIL on unfixed code — failure confirms each bug exists.
DO NOT fix the tests or the code when they fail.
"""

from __future__ import annotations

from fastapi import FastAPI

# ── Bug 1.17: FastAPI constructed at module level, not inside create_app() ───


def test_create_app_function_exists_in_main() -> None:
    """Requirement 2.20: src.main must expose a create_app() factory function.

    BUG: currently FastAPI is constructed at module level — there is no
    create_app() function.
    Counterexample: AttributeError or create_app not callable.
    """
    import src.main as main_module

    assert hasattr(main_module, "create_app"), (
        "Expected src.main to expose a 'create_app' function but it was not found. "
        "BUG: FastAPI is constructed at module level, not inside a factory."
    )
    assert callable(main_module.create_app), (  # type: ignore[attr-defined]
        "Expected 'create_app' to be callable but it is not."
    )


def test_create_app_returns_fastapi_instance() -> None:
    """Requirement 2.20: create_app() must return a FastAPI instance.

    BUG: create_app() does not exist yet.
    Counterexample: AttributeError raised on import.
    """
    import src.main as main_module

    assert hasattr(main_module, "create_app"), "create_app() not found in src.main"

    app = main_module.create_app()  # type: ignore[attr-defined]
    assert isinstance(app, FastAPI), f"Expected create_app() to return FastAPI but got {type(app)}"


def test_two_create_app_calls_produce_independent_instances() -> None:
    """Requirement 2.20: Two calls to create_app() must produce independent FastAPI instances.

    BUG: create_app() does not exist; FastAPI is a module-level singleton.
    Counterexample: same object returned, or AttributeError.
    """
    import src.main as main_module

    assert hasattr(main_module, "create_app"), "create_app() not found in src.main"

    app1 = main_module.create_app()  # type: ignore[attr-defined]
    app2 = main_module.create_app()  # type: ignore[attr-defined]

    assert app1 is not app2, (
        "Expected two calls to create_app() to produce independent FastAPI instances "
        "but got the same object. BUG: module-level singleton."
    )
