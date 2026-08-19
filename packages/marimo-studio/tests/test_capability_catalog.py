from __future__ import annotations

import inspect
import json
from importlib import import_module
from pathlib import Path
from typing import Any, get_type_hints

import agent_plugins
import click

import marimo_studio.agent as studio_agent
from marimo_studio._cli import cli

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills" / "marimo-studio"
CATALOG = SKILL / "references" / "capabilities.json"
CAPABILITY_IDS = {
    "studio.overview",
    "studio.inspect",
    "studio.view.ensure",
    "studio.bind",
    "studio.view.activate",
    "studio.check",
    "studio.analyze",
    "studio.view.remove",
    "studio.export",
}


def _catalog() -> list[dict[str, Any]]:
    payload = _catalog_document()
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, list)
    return capabilities


def _catalog_document() -> dict[str, Any]:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["shared_cli_options"] == ["--format", "--diagnostics"]
    return payload


def _command(path: list[str]) -> click.Command:
    command: click.Command = cli
    for name in path:
        assert isinstance(command, click.Group)
        command = command.commands[name]
    return command


def _option_names(command: click.Command) -> set[str]:
    return {
        option
        for parameter in command.params
        if isinstance(parameter, click.Option)
        for option in parameter.opts + parameter.secondary_opts
    }


def _option(command: click.Command, name: str) -> click.Option:
    requested = set(name.split("/"))
    for parameter in command.params:
        if not isinstance(parameter, click.Option):
            continue
        if requested <= set(parameter.opts + parameter.secondary_opts):
            return parameter
    raise AssertionError(f"Missing option {name}")


def _catalog_type(reference: str) -> type[object]:
    module_name, _, name = reference.rpartition(".")
    value = getattr(import_module(module_name), name)
    assert isinstance(value, type)
    return value


def test_catalog_declares_the_supported_capability_surface() -> None:
    capabilities = _catalog()

    assert {item["id"] for item in capabilities} == CAPABILITY_IDS
    assert len({item["id"] for item in capabilities}) == len(capabilities)
    assert all(
        item["mutation"]
        in {"none", "files", "configuration", "browser", "execution", "output"}
        for item in capabilities
    )
    assert all(item["result"]["schema"] == 1 for item in capabilities)
    for item in capabilities:
        result_reference = item["result"]["type"]
        result_type = _catalog_type(result_reference)
        assert result_type.__name__ == item["result"]["record"]
        assert callable(getattr(result_type, "to_dict", None))
        module_name, _, name = result_reference.rpartition(".")
        assert name in getattr(import_module(module_name), "__all__", ())
        if item["request"] is not None:
            assert item["request"]["schema"] == 1
            request_type = _catalog_type(item["request"]["type"])
            assert callable(getattr(request_type, "to_dict", None))
            assert callable(getattr(request_type, "from_dict", None))


def test_catalog_code_mode_mappings_match_public_signatures() -> None:
    for capability in _catalog():
        mapping = capability["interfaces"]["code_mode"]
        if mapping is None:
            continue
        name = mapping["call"]
        function = getattr(studio_agent, name)
        signature = inspect.signature(function)
        hints = get_type_hints(function)
        mapped_parameters = {
            parameter["code_mode"]
            for parameter in capability["parameters"]
            if parameter.get("code_mode") is not None
        }

        assert name in studio_agent.__all__
        assert inspect.iscoroutinefunction(function) is mapping["async"]
        assert hints["return"].__name__ == capability["result"]["record"]
        assert hints["return"] is _catalog_type(capability["result"]["type"])
        assert set(signature.parameters) == {"context", *mapped_parameters}
        for parameter in capability["parameters"]:
            python_name = parameter.get("code_mode")
            if python_name is None:
                continue
            assert python_name in signature.parameters
            if "default" in parameter:
                assert signature.parameters[python_name].default == parameter["default"]
            elif parameter.get("required"):
                assert (
                    signature.parameters[python_name].default is inspect.Parameter.empty
                )


def test_catalog_accounts_for_every_public_agent_export() -> None:
    capability_calls = {
        mapping["call"]
        for capability in _catalog()
        if (mapping := capability["interfaces"]["code_mode"]) is not None
    }
    utilities = _catalog_document()["code_mode_utilities"]
    utility_calls = {item["call"] for item in utilities}

    assert len(utility_calls) == len(utilities)
    assert set(studio_agent.__all__) == capability_calls | utility_calls
    assert all(callable(getattr(studio_agent, name)) for name in utility_calls)


def test_catalog_cli_mappings_match_the_click_tree() -> None:
    for capability in _catalog():
        mapping = capability["interfaces"]["cli"]
        command = _command(mapping["command"])
        options = _option_names(command)

        assert "--format" in options
        for parameter in capability["parameters"]:
            option = parameter.get("cli")
            if option is None:
                continue
            cli_option = _option(command, option)
            if "default" in parameter:
                default = cli_option.get_default(click.Context(command))
                if default is click.core.UNSET:
                    default = None
                assert default == parameter["default"]
            if parameter.get("required"):
                assert cli_option.required
            if "minimum" in parameter:
                assert getattr(cli_option.type, "min", None) == parameter["minimum"]
            if "maximum" in parameter:
                assert getattr(cli_option.type, "max", None) == parameter["maximum"]
        for option in mapping.get("connection_options", []):
            assert option in options
        for envvar, option in mapping.get("environment", {}).items():
            assert _option(command, option).envvar == envvar
        assert all(
            name.startswith("MARIMO_STUDIO_") for name in mapping.get("credentials", [])
        )
        for extension in mapping.get("extensions", []):
            assert isinstance(extension["executes_notebook"], bool)
            assert extension["options"]
            for option in extension["options"]:
                assert option in options
        expected_options = set(_catalog_document()["shared_cli_options"])
        for parameter in capability["parameters"]:
            if option := parameter.get("cli"):
                expected_options.update(option.split("/"))
        for option in mapping.get("connection_options", []):
            expected_options.update(option.split("/"))
        for extension in mapping.get("extensions", []):
            for option in extension["options"]:
                expected_options.update(option.split("/"))
        expected_options.update(
            item for item in mapping["machine_output"] if item.startswith("-")
        )
        assert options == expected_options


def test_catalog_marks_runtime_extensions_as_notebook_execution() -> None:
    runtime_extensions = [
        extension
        for capability in _catalog()
        for extension in capability["interfaces"]["cli"].get("extensions", [])
        if "--runtime" in extension["options"]
    ]

    assert runtime_extensions
    assert all(extension["executes_notebook"] for extension in runtime_extensions)


def test_catalog_activation_errors_are_stable_and_unique() -> None:
    activation = next(
        item for item in _catalog() if item["id"] == "studio.view.activate"
    )

    assert len(activation["errors"]) == len(set(activation["errors"]))
    assert {
        "invalid-activation-request",
        "view-not-found",
        "browser-client-ambiguous",
        "browser-client-unavailable",
        "activation-timeout",
        "protocol-error",
    } <= set(activation["errors"])


def test_catalog_guides_resolve_inside_the_skill() -> None:
    root = SKILL.resolve()
    for capability in _catalog():
        guide = (SKILL / capability["guide"]).resolve()
        assert guide.is_relative_to(root)
        assert guide.is_file()


def test_plugin_build_plan_selects_the_complete_canonical_skill_tree() -> None:
    plan = agent_plugins.build_plan(ROOT / "packages" / "marimo-studio")
    selected = {mapping.source.resolve() for mapping in plan.files}
    expected = {
        (ROOT / "plugin.json").resolve(),
        *(path.resolve() for path in SKILL.rglob("*") if path.is_file()),
    }

    assert selected == expected


def test_editable_plugin_inventory_matches_the_build_plan() -> None:
    plan = agent_plugins.build_plan(ROOT / "packages" / "marimo-studio")
    plugin = studio_agent.agent_plugin()
    planned = {mapping.target.as_posix() for mapping in plan.files}
    installed = {path.relative_to(plugin.path).as_posix() for path in plugin.files}

    assert installed == planned
