"""Architecture test: verify scheduling_engine has zero framework dependencies."""

import ast
import importlib.util
import pkgutil
from pathlib import Path


def test_scheduling_engine_has_no_fastapi_imports() -> None:
    """Verify scheduling_engine contains no FastAPI imports."""
    forbidden = {"fastapi", "sqlalchemy"}
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
                            module_name = alias.name.split(".")[0]
                            if module_name in forbidden:
                                violations.append(f"{spec.origin}: imports {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            base = node.module.split(".")[0]
                            if base in forbidden:
                                violations.append(f"{spec.origin}: from {node.module} import ...")
        except (ImportError, AttributeError, OSError):
            pass

    assert not violations, "scheduling_engine has forbidden imports:\n" + "\n".join(violations)
