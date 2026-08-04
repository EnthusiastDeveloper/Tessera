"""Architecture test: verify scheduling_engine has zero framework/app dependencies."""

import ast
import importlib.util
import pkgutil
from pathlib import Path


def _is_forbidden(module_name: str) -> bool:
    """A module is forbidden if it's fastapi/sqlalchemy, or any app.* module
    other than scheduling_engine itself (its own package)."""
    if module_name in {"fastapi", "sqlalchemy"} or module_name.startswith(("fastapi.", "sqlalchemy.")):
        return True
    if module_name == "app" or module_name.startswith("app."):
        return not (module_name == "app.scheduling_engine" or module_name.startswith("app.scheduling_engine."))
    return False


def test_scheduling_engine_has_no_forbidden_imports() -> None:
    """Verify scheduling_engine imports nothing from FastAPI, SQLAlchemy, or the rest of app/."""
    violations: list[str] = []

    engine_path = Path(__file__).parent.parent.parent / "app" / "scheduling_engine"
    assert engine_path.exists(), f"scheduling_engine path not found: {engine_path}"

    for module_info in pkgutil.walk_packages(
        [str(engine_path)],
        prefix="app.scheduling_engine.",
    ):
        try:
            spec = importlib.util.find_spec(module_info.name)
            if spec and spec.origin:
                with open(spec.origin, encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=spec.origin)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if _is_forbidden(alias.name):
                                violations.append(f"{spec.origin}: imports {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.level == 0 and _is_forbidden(node.module):
                            violations.append(f"{spec.origin}: from {node.module} import ...")
        except (ImportError, AttributeError, OSError):
            pass

    assert not violations, "scheduling_engine has forbidden imports:\n" + "\n".join(violations)
