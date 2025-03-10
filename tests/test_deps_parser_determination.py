"""Test the determination of strategy to parse dependency declarations."""

import logging
import shutil
from pathlib import Path

import pytest

from fawltydeps.extract_deps import (
    first_applicable_parser,
    parse_source,
    parse_sources,
    validate_deps_source,
)
from fawltydeps.settings import ParserChoice, Settings
from fawltydeps.traverse_project import find_sources
from fawltydeps.types import DepsSource

from .utils import assert_unordered_equivalence, collect_dep_names


@pytest.mark.parametrize(
    ("path", "expect_choice"),
    [
        pytest.param(Path(path), expect_choice, id=path)
        for path, expect_choice in [
            # in current dir:
            ("requirements.txt", ParserChoice.REQUIREMENTS_TXT),
            ("setup.py", ParserChoice.SETUP_PY),
            ("setup.cfg", ParserChoice.SETUP_CFG),
            ("pyproject.toml", ParserChoice.PYPROJECT_TOML),
            ("pixi.toml", ParserChoice.PIXI_TOML),
            ("environment.yml", ParserChoice.ENVIRONMENT_YML),
            ("anything_else", None),
            # in subdir:
            (str(Path("sub", "requirements.txt")), ParserChoice.REQUIREMENTS_TXT),
            (str(Path("sub", "setup.py")), ParserChoice.SETUP_PY),
            (str(Path("sub", "setup.cfg")), ParserChoice.SETUP_CFG),
            (str(Path("sub", "pyproject.toml")), ParserChoice.PYPROJECT_TOML),
            (str(Path("sub", "pixi.toml")), ParserChoice.PIXI_TOML),
            (str(Path("sub", "environment.yml")), ParserChoice.ENVIRONMENT_YML),
            (str(Path("sub", "anything_else")), None),
            # TODO: Make these absolute paths?
            (str(Path("abs", "requirements.txt")), ParserChoice.REQUIREMENTS_TXT),
            (str(Path("abs", "setup.py")), ParserChoice.SETUP_PY),
            (str(Path("abs", "setup.cfg")), ParserChoice.SETUP_CFG),
            (str(Path("abs", "pyproject.toml")), ParserChoice.PYPROJECT_TOML),
            (str(Path("abs", "pixi.toml")), ParserChoice.PIXI_TOML),
            (str(Path("abs", "environment.yml")), ParserChoice.ENVIRONMENT_YML),
            (str(Path("abs", "anything_else")), None),
            # using dep file name as a directory name is not supported:
            (str(Path("requirements.txt", "wat")), None),
            (str(Path("setup.py", "wat")), None),
            (str(Path("setup.cfg", "wat")), None),
            (str(Path("pyproject.toml", "wat")), None),
            (str(Path("pixi.toml", "wat")), None),
            (str(Path("environment.yml", "wat")), None),
            # variations that all map to requirements.txt parser;
            ("requirements-dev.txt", ParserChoice.REQUIREMENTS_TXT),
            ("test-requirements.txt", ParserChoice.REQUIREMENTS_TXT),
            ("extra-requirements-dev.txt", ParserChoice.REQUIREMENTS_TXT),
            ("abc_requirements.txt", ParserChoice.REQUIREMENTS_TXT),
            ("requirements_abc.txt", ParserChoice.REQUIREMENTS_TXT),
            ("more_requirements_stuff.txt", ParserChoice.REQUIREMENTS_TXT),
            ("evenrequirementsthis.txt", ParserChoice.REQUIREMENTS_TXT),
        ]
    ],
)
def test_first_applicable_parser(path, expect_choice):
    assert first_applicable_parser(path) is expect_choice


PARSER_CHOICE_FILE_NAME_MATCH_GRID = {
    ParserChoice.REQUIREMENTS_TXT: "requirements.txt",
    ParserChoice.SETUP_PY: "setup.py",
    ParserChoice.SETUP_CFG: "setup.cfg",
    ParserChoice.PYPROJECT_TOML: "pyproject.toml",
    ParserChoice.PIXI_TOML: "pixi.toml",
    ParserChoice.ENVIRONMENT_YML: "environment.yml",
}
PARSER_CHOICE_FILE_NAME_MISMATCH_GRID = {
    pc: [fn for _pc, fn in PARSER_CHOICE_FILE_NAME_MATCH_GRID.items() if pc != _pc]
    for pc in PARSER_CHOICE_FILE_NAME_MATCH_GRID
}


@pytest.mark.parametrize(
    ("parser_choice", "deps_file_name", "mismatch"),
    [
        pytest.param(pc, fn, mismatch, id=f"{pc}__{fn}")
        for pc, fn, mismatch in [
            (pc, fn, True)
            for pc, filenames in PARSER_CHOICE_FILE_NAME_MISMATCH_GRID.items()
            for fn in filenames
        ]
        + [(pc, fn, False) for pc, fn in PARSER_CHOICE_FILE_NAME_MATCH_GRID.items()]
    ],
)
def test_explicit_parse_strategy__mismatch_yields_appropriate_logging(
    fake_project, caplog, parser_choice, deps_file_name, mismatch
):
    """Log message only when there is mismatch between strategy and filename.

    In order to make sure that no warning/error messages are logged when there
    is no mismatch between parser choice and filename, we need to ensure that
    the given deps file has a _valid_ format. E.g. just passing an empty file
    is not necessarily sufficient.
    """
    tmp_path = fake_project(
        files_with_declared_deps={
            deps_file_name: ["foo", "bar"],  # dependencies
        },
    )
    deps_path = tmp_path / deps_file_name
    caplog.set_level(logging.WARNING)
    # Execute here just for side effect (log).
    list(parse_source(DepsSource(deps_path, parser_choice)))
    if mismatch:
        assert (
            f"Manually applying parser '{parser_choice}' to dependencies: {deps_path}"
        ) in caplog.text
    else:
        assert caplog.text == ""


@pytest.mark.parametrize(
    ("deps_file_name", "exp_deps"),
    [
        pytest.param(fn, deps, id=fn)
        for fn, deps in [
            ("requirements.txt", ["pandas", "click"]),
            ("setup.py", []),
            ("setup.cfg", ["dependencyA", "dependencyB"]),
            ("pyproject.toml", ["pandas", "pydantic", "pylint"]),
        ]
    ],
)
def test_filepath_inference(
    tmp_path,
    project_with_setup_with_cfg_pyproject_and_requirements,  # noqa: ARG001
    deps_file_name,
    exp_deps,
):
    """Parser choice finalization function can choose based on deps filename."""
    deps_path = tmp_path / deps_file_name
    assert deps_path.is_file()  # precondition
    src = validate_deps_source(deps_path)
    assert src is not None
    obs_deps = collect_dep_names(parse_source(src))
    assert_unordered_equivalence(obs_deps, exp_deps)


@pytest.mark.parametrize(
    ("parser_choice", "exp_deps"),
    [
        pytest.param(choice, exp, id=f"{choice.name}")
        for choice, exp in [
            (
                ParserChoice.REQUIREMENTS_TXT,
                ["pandas", "click", "black", "sphinx", "pandas", "tensorflow"],
            ),
            (ParserChoice.SETUP_PY, []),
            (ParserChoice.SETUP_CFG, ["dependencyA", "dependencyB"]),
            (ParserChoice.PYPROJECT_TOML, ["pandas", "pydantic", "pylint"]),
        ]
    ],
)
def test_extract_from_directory_applies_manual_parser_choice_iff_choice_applies(
    tmp_path,
    project_with_setup_with_cfg_pyproject_and_requirements,  # noqa: ARG001
    parser_choice,
    exp_deps,
):
    settings = Settings(code=set(), deps={tmp_path}, deps_parser_choice=parser_choice)
    deps_sources = list(find_sources(settings, {DepsSource}))
    obs_deps = collect_dep_names(parse_sources(deps_sources))
    assert_unordered_equivalence(obs_deps, exp_deps)


@pytest.mark.parametrize(
    ("parser_choice", "fn1", "fn2", "exp_deps"),
    [
        pytest.param(choice, fn1, fn2, exp, id=f"{choice.name}__{fn1}__{fn2}")
        for choice, fn1, fn2, exp in [
            (
                ParserChoice.REQUIREMENTS_TXT,
                "requirements.txt",
                "setup.py",
                ["pandas", "click"],
            ),
            (ParserChoice.SETUP_PY, "setup.py", "requirements.txt", []),
            (
                ParserChoice.SETUP_CFG,
                "setup.cfg",
                "pyproject.toml",
                ["dependencyA", "dependencyB"],
            ),
            (
                ParserChoice.PYPROJECT_TOML,
                "pyproject.toml",
                "setup.cfg",
                ["pandas", "pydantic", "pylint"],
            ),
        ]
    ],
)
def test_extract_from_file_applies_manual_choice_even_if_mismatched(
    caplog,
    tmp_path,
    project_with_setup_with_cfg_pyproject_and_requirements,  # noqa: ARG001
    parser_choice,
    fn1,
    fn2,
    exp_deps,
):
    old_path = tmp_path / fn1
    new_path = tmp_path / fn2
    shutil.move(old_path, new_path)
    caplog.set_level(logging.WARNING)
    obs_deps = collect_dep_names(parse_source(DepsSource(new_path, parser_choice)))
    assert_unordered_equivalence(obs_deps, exp_deps)
    exp_msg = f"Manually applying parser '{parser_choice}' to dependencies: {new_path}"
    assert exp_msg in caplog.text
