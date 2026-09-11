"""Accidental Python method replacement must fail before process rehearsal."""
import ast
from pathlib import Path


def test_host_modules_do_not_silently_replace_definitions():
    failures = []
    for path in sorted((Path(__file__).resolve().parents[1] / "host/otis_tools").glob("*.py")):
        tree = ast.parse(path.read_text())
        for scope in [tree, *(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))]:
            seen = set()
            for node in scope.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # Explicit property setters are intentional Python rebinding.
                    if any(isinstance(d, ast.Attribute) and d.attr in {"setter", "deleter"}
                           for d in getattr(node, "decorator_list", [])):
                        continue
                    if node.name in seen:
                        failures.append(f"{path.name}:{node.lineno}: duplicate {node.name}")
                    seen.add(node.name)
    assert not failures, "\n".join(failures)
