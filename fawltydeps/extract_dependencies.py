"Collect declared dependencies of the project"

import ast
import logging
import os
from pathlib import Path
from typing import Iterator, Optional, Tuple

from pkg_resources import parse_requirements

logger = logging.getLogger(__name__)


def parse_requirements_contents(
    text: str, path_hint: Path
) -> Iterator[Tuple[str, Path]]:
    """
    Extract dependencies (packages names) from the requirement.txt file
    and other following Requirements File Format. For more information, see
    https://pip.pypa.io/en/stable/reference/requirements-file-format/.
    """
    for requirement in parse_requirements(text):
        yield (requirement.key, path_hint)


def parse_setup_contents(text: str, path_hint: Path) -> Iterator[Tuple[str, Path]]:
    """
    Extract dependencies (package names) from setup.py.
    Function `setup` where dependencies are listed is at the
    """
    setup_contents = ast.parse(text, filename=str(path_hint))

    def _handle_dependencies(deps: ast.List) -> Iterator[Tuple[str, Path]]:
        for element in deps.elts:
            if isinstance(element, ast.Constant):
                yield from parse_requirements_contents(
                    element.value, path_hint=path_hint
                )

    def _extract_dependencies(node: ast.Call) -> Iterator[Tuple[str, Path]]:
        for keyword in node.keywords:
            if keyword.arg == "install_requires":
                if isinstance(keyword.value, ast.List):
                    yield from _handle_dependencies(keyword.value)

            if keyword.arg == "extras_require":
                if isinstance(keyword.value, ast.Dict):
                    logger.debug(ast.dump(keyword.value))
                    for elements in keyword.value.values:
                        logger.debug(ast.dump(elements))
                        if isinstance(elements, ast.List):
                            yield from _handle_dependencies(elements)

    def _get_setup_function_call(node: ast.AST) -> Optional[ast.Call]:
        function_name = "setup"
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name):
                    if node.value.func.id == function_name:
                        return node.value
        return None

    for node in ast.walk(setup_contents):
        function_node = _get_setup_function_call(node)
        if function_node:
            yield from _extract_dependencies(function_node)
            break


def extract_dependencies(path: Path) -> Iterator[Tuple[str, Path]]:
    """
    Extract dependencies from supported file types.
    Traverse directory tree to find matching files.
    Call handlers for each file type to extract dependencies.
    """
    parsers = {
        "requirements.txt": parse_requirements_contents,
        "requirements.in": parse_requirements_contents,
        "setup.py": parse_setup_contents,
    }
    # TODO extract dependencies from pyproject.toml

    for root, _dirs, files in os.walk(path):
        for filename in files:
            if filename in parsers:
                parser = parsers[filename]
                current_path = Path(root, filename)
                logger.debug(f"Extracting dependency from {current_path}.")
                yield from parser(current_path.read_text(), path_hint=current_path)
