"""Deterministic implementation-relationship extraction for indexed codebases.

The extractor deliberately favors precision over coverage. It currently resolves
Python and Go imports against the repository file inventory. Unresolved imports
are ignored rather than represented as inferred graph facts.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ImplementationRelation:
    """A confidently resolved relationship between two indexed source files."""

    source_path: str
    target_path: str
    relation_type: str
    confidence: float = 1.0


class ImplementationRelationshipExtractor:
    """Extract deterministic file-to-file relationships from source text."""

    SUPPORTED_LANGUAGES = {"Python", "Go"}

    def extract(
        self,
        files: Iterable[Mapping[str, str]],
    ) -> list[ImplementationRelation]:
        """Return deduplicated, resolvable relationships for indexed source files."""
        inventory = {str(item["path"]): item for item in files if item.get("path")}
        relations: set[ImplementationRelation] = set()

        for path, item in inventory.items():
            language = str(item.get("language") or "")
            content = item.get("content")
            if language not in self.SUPPORTED_LANGUAGES or not content:
                continue

            if language == "Python":
                relations.update(self._python_imports(path, content, inventory))
            elif language == "Go":
                relations.update(self._go_imports(path, content, inventory))

        return sorted(
            relations,
            key=lambda relation: (
                relation.source_path,
                relation.relation_type,
                relation.target_path,
            ),
        )

    def _python_imports(
        self,
        source_path: str,
        content: str,
        inventory: Mapping[str, Mapping[str, str]],
    ) -> set[ImplementationRelation]:
        """Resolve Python import statements to repository files where possible."""
        try:
            tree = ast.parse(content, filename=source_path)
        except (SyntaxError, ValueError):
            return set()

        source_dir = PurePosixPath(source_path).parent
        repo_roots = self._python_roots(inventory)
        result: set[ImplementationRelation] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = self._resolve_python_module(alias.name, None, source_dir, inventory, repo_roots)
                    if target:
                        result.add(ImplementationRelation(source_path, target, "IMPORTS"))
            elif isinstance(node, ast.ImportFrom):
                target = self._resolve_python_module(
                    node.module or "",
                    node.level,
                    source_dir,
                    inventory,
                    repo_roots,
                )
                if target:
                    result.add(ImplementationRelation(source_path, target, "IMPORTS"))

        return result

    def _python_roots(self, inventory: Mapping[str, Mapping[str, str]]) -> list[str]:
        """Find package roots from indexed Python files."""
        roots: set[str] = set()
        for path in inventory:
            if not path.endswith(".py"):
                continue
            parts = PurePosixPath(path).parts
            for index, part in enumerate(parts[:-1]):
                if part in {"nlp", "api", "src", "app", "tests"}:
                    roots.add("/".join(parts[: index + 1]))
        roots.add("")
        return sorted(roots, key=len, reverse=True)

    def _resolve_python_module(
        self,
        module: str,
        level: int | None,
        source_dir: PurePosixPath,
        inventory: Mapping[str, Mapping[str, str]],
        roots: list[str],
    ) -> str | None:
        """Resolve a Python module name to an indexed .py file."""
        if not module and not level:
            return None

        if level:
            base = source_dir
            for _ in range(max(level - 1, 0)):
                base = base.parent
            module_path = str(base / module.replace(".", "/")) if module else str(base)
        else:
            module_path = module.replace(".", "/")

        candidates = []
        for root in roots:
            if root and not module_path.startswith(root + "/") and module_path != root:
                candidates.append(f"{root}/{module_path}")
            else:
                candidates.append(module_path)

        for candidate in candidates:
            candidate = candidate.strip("/")
            for path in (f"{candidate}.py", f"{candidate}/__init__.py"):
                if path in inventory:
                    return path

        return None

    def _go_imports(
        self,
        source_path: str,
        content: str,
        inventory: Mapping[str, Mapping[str, str]],
    ) -> set[ImplementationRelation]:
        """Resolve Go imports using the repository's go.mod module path."""
        module_name = self._go_module_name(inventory)
        if not module_name:
            return set()

        imports = re.findall(
            r'(?ms)^\s*import\s*\((.*?)\)',
            content,
        )
        single_imports = re.findall(r'^\s*import\s+(?:[\w.]+\s+)?"([^"]+)"', content, re.MULTILINE)
        paths = list(single_imports)
        for block in imports:
            paths.extend(re.findall(r'"([^"]+)"', block))

        result: set[ImplementationRelation] = set()
        for imported in paths:
            if not imported.startswith(module_name + "/"):
                continue
            package_path = imported[len(module_name) + 1 :].strip("/")
            target = self._resolve_go_package(package_path, inventory)
            if target:
                result.add(ImplementationRelation(source_path, target, "IMPORTS"))
        return result

    def _go_module_name(self, inventory: Mapping[str, Mapping[str, str]]) -> str | None:
        """Read the module declaration from indexed go.mod content."""
        go_mod = inventory.get("go.mod")
        if not go_mod or not go_mod.get("content"):
            return None
        match = re.search(r"(?m)^\s*module\s+(\S+)\s*$", go_mod["content"])
        return match.group(1) if match else None

    def _resolve_go_package(
        self,
        package_path: str,
        inventory: Mapping[str, Mapping[str, str]],
    ) -> str | None:
        """Resolve a Go package to a deterministic representative .go file."""
        prefix = package_path.rstrip("/") + "/"
        candidates = sorted(
            path
            for path, item in inventory.items()
            if path.startswith(prefix) and path.endswith(".go") and not path.endswith("_test.go")
            and str(item.get("language")) == "Go"
        )
        return candidates[0] if candidates else None
