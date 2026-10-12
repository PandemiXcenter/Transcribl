"""Guard the provider-neutral boundaries and loadable editor module graph."""

from __future__ import annotations

import ast
import re
import sys
from graphlib import TopologicalSorter
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "transcribl"
SDK_ROOTS = {"google", "openai", "anthropic"}


def imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text("utf-8"))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_core_layers_do_not_import_adapters_interfaces_or_provider_sdks() -> None:
    for layer in ("domain", "ports", "application", "config"):
        for path in (SOURCE / layer).rglob("*.py"):
            for dependency in imports(path):
                assert dependency.split(".")[0] not in SDK_ROOTS, (path, dependency)
                assert not dependency.startswith(
                    ("transcribl.adapters", "transcribl.interfaces", "transcribl.composition")
                ), (path, dependency)
                if layer == "domain":
                    assert dependency.split(".")[0] in (
                        sys.stdlib_module_names | {"transcribl", "pydantic"}
                    ), (path, dependency)
                    assert not dependency.startswith(
                        ("transcribl.application", "transcribl.ports", "transcribl.config")
                    ), (path, dependency)


def test_provider_sdks_are_confined_to_company_adapters() -> None:
    for path in SOURCE.rglob("*.py"):
        if any(name.split(".")[0] in SDK_ROOTS for name in imports(path)):
            assert path.parent == SOURCE / "adapters" / "llm" / "providers", path


def test_editor_imports_resolve_exported_symbols_without_cycles() -> None:
    root = SOURCE / "interfaces" / "desktop" / "static" / "editor"
    modules = {path.stem: path.read_text("utf-8") for path in root.glob("*.js")}
    exports = {
        name: set(re.findall(r"^export (?:async )?(?:function|const) (\w+)", text, re.M))
        for name, text in modules.items()
    }
    graph: dict[str, set[str]] = {}
    for name, text in modules.items():
        graph[name] = set()
        for symbols, dependency in re.findall(
            r'import\s*\{([^}]+)\}\s*from\s*"\./([\w_]+)\.js";', text
        ):
            assert dependency in modules, (name, dependency)
            assert {s.strip() for s in symbols.split(",")} <= exports[dependency]
            graph[name].add(dependency)
    assert len(tuple(TopologicalSorter(graph).static_order())) == len(modules)
    assert "initializeEditor" in exports["index"]


def test_editor_styles_resolve_packaged_assets() -> None:
    root = SOURCE / "interfaces" / "desktop" / "static"
    stylesheet = (root / "editor.css").read_text("utf-8")
    references = re.findall(r'@import url\("/editor-assets/([^\"]+)"\)', stylesheet)
    assert references
    for reference in references:
        assert (root / reference).is_file()
        assert ".." not in Path(reference).parts


def test_python_runtime_module_graph_is_acyclic() -> None:
    modules = {
        "transcribl."
        + ".".join(path.relative_to(SOURCE).with_suffix("").parts).removesuffix(".__init__"): path
        for path in SOURCE.rglob("*.py")
    }

    def runtime_nodes(tree: ast.AST) -> list[ast.AST]:
        result: list[ast.AST] = []
        for node in ast.iter_child_nodes(tree):
            if (
                isinstance(node, ast.If)
                and isinstance(node.test, ast.Name)
                and node.test.id == "TYPE_CHECKING"
            ):
                continue
            result.append(node)
            result.extend(runtime_nodes(node))
        return result

    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        for node in runtime_nodes(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    target = f"{node.module}.{alias.name}"
                    if target not in modules:
                        target = node.module
                    if target in modules:
                        graph[name].add(target)
            elif isinstance(node, ast.Import):
                graph[name].update(a.name for a in node.names if a.name in modules)
    assert len(tuple(TopologicalSorter(graph).static_order())) == len(modules)
