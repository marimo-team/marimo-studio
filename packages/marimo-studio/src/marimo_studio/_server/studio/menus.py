"""Render Studio toolbar and pane menus."""

from __future__ import annotations

from typing import cast

from htpy import (
    Node,
    a,
    button,
    circle,
    details,
    div,
    form,
    header,
    label,
    nav,
    p,
    path,
    section,
    span,
    strong,
    summary,
    svg,
)
from htpy import input as input_element

from marimo_studio._html import node_list
from marimo_studio._server.studio.brand import marimo_mark
from marimo_studio._workspace.models import StudioConfig


def menu_chevron() -> Node:
    """Render the down-chevron geometry used by Marimo controls."""
    return cast(
        Node,
        svg(
            {
                "class": "studio-menu-chevron",
                "viewBox": "0 0 24 24",
                "fill": "none",
                "stroke": "currentColor",
                "stroke-width": "2",
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
                "aria-hidden": "true",
                "focusable": "false",
            }
        )[node_list(path(d="m6 9 6 6 6-6"))],
    )


def popout_icon() -> Node:
    return cast(
        Node,
        svg(
            {
                "class": "studio-toolbar-icon",
                "viewBox": "0 0 24 24",
                "fill": "none",
                "stroke": "currentColor",
                "stroke-width": "1.8",
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
                "aria-hidden": "true",
            }
        )[
            node_list(
                path(d="M14 5h5v5"),
                path(d="m10 14 9-9"),
                path(d="M19 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"),
            )
        ],
    )


def more_icon() -> Node:
    return cast(
        Node,
        svg(
            {
                "class": "studio-toolbar-icon",
                "viewBox": "0 0 24 24",
                "fill": "currentColor",
                "aria-hidden": "true",
            }
        )[
            node_list(
                circle(cx="12", cy="5", r="1.35"),
                circle(cx="12", cy="12", r="1.35"),
                circle(cx="12", cy="19", r="1.35"),
            )
        ],
    )


def view_menu(config: StudioConfig, selected: str) -> Node:
    """Render view selection, creation, and removal controls."""
    return cast(
        Node,
        details(class_="studio-menu studio-view-menu", data_view_menu=True)[
            node_list(
                summary(
                    {
                        "class": "studio-menu-trigger",
                        "aria-label": "Select or manage a view",
                        "data-view-trigger": True,
                    }
                )[
                    node_list(
                        span(data_view_trigger_label=True)[selected],
                        menu_chevron(),
                    )
                ],
                div(class_="studio-menu-popover")[
                    node_list(
                        strong(class_="studio-menu-heading")["Views"],
                        div(
                            {
                                "class": "studio-view-list",
                                "data-view-list": True,
                                "role": "group",
                                "aria-label": "Views",
                            }
                        )[
                            node_list(
                                *[
                                    div(class_="studio-view-row")[
                                        node_list(
                                            button(
                                                {
                                                    "type": "button",
                                                    "class": (
                                                        "studio-menu-item "
                                                        "studio-view-option"
                                                    ),
                                                    "data-view-option": name,
                                                    "aria-current": (
                                                        "page"
                                                        if name == selected
                                                        else None
                                                    ),
                                                }
                                            )[
                                                node_list(
                                                    span(class_="studio-menu-check")[
                                                        "✓"
                                                    ],
                                                    name,
                                                )
                                            ],
                                            len(config.views) > 1
                                            and button(
                                                {
                                                    "type": "button",
                                                    "class": "studio-view-remove",
                                                    "data-remove-view": name,
                                                    "aria-label": (
                                                        f"Remove {name} view"
                                                    ),
                                                }
                                            )["Remove"],
                                        )
                                    ]
                                    for name in config.views
                                ]
                            )
                        ],
                        button(
                            {
                                "type": "button",
                                "class": "studio-menu-item studio-new-view",
                                "data-new-view": True,
                            }
                        )["+ New view"],
                        _new_view_form(),
                        _remove_view_confirmation(),
                    )
                ],
            )
        ],
    )


def _new_view_form() -> Node:
    return cast(
        Node,
        form(
            {
                "class": "studio-new-view-form",
                "data-new-view-form": True,
                "hidden": True,
            }
        )[
            node_list(
                label(for_="studio-view-name")["New view"],
                input_element(
                    id="studio-view-name",
                    name="name",
                    type="text",
                    autocomplete="off",
                    autocapitalize="none",
                    spellcheck="false",
                    pattern="[a-z][a-z0-9-]*",
                    placeholder="executive-report",
                    required=True,
                    data_new_view_name=True,
                ),
                p(class_="studio-form-hint")[
                    "Start with a lowercase letter. Use letters, numbers, and hyphens."
                ],
                p(
                    {
                        "class": "studio-form-message",
                        "data-new-view-message": True,
                        "role": "status",
                        "hidden": True,
                    }
                ),
                div(class_="studio-form-actions")[
                    node_list(
                        button(type="button", data_new_view_cancel=True)["Cancel"],
                        button(
                            type="submit",
                            class_="studio-primary-action",
                            data_new_view_submit=True,
                        )["Create"],
                    )
                ],
            )
        ],
    )


def _remove_view_confirmation() -> Node:
    return cast(
        Node,
        section(
            {
                "class": "studio-remove-view-confirm",
                "data-remove-view-confirm": True,
                "hidden": True,
                "aria-labelledby": "studio-remove-view-title",
            }
        )[
            node_list(
                strong(
                    {
                        "id": "studio-remove-view-title",
                        "data-remove-view-title": True,
                    }
                )["Remove view?"],
                p(class_="studio-remove-view-detail")[
                    node_list(
                        "This deletes the HTML, CSS, and static files for ",
                        strong(data_remove_view_name=True),
                        ".",
                    )
                ],
                p(
                    {
                        "class": "studio-form-message",
                        "data-remove-view-message": True,
                        "role": "alert",
                        "hidden": True,
                    }
                ),
                div(class_="studio-form-actions")[
                    node_list(
                        button(type="button", data_remove_view_cancel=True)["Cancel"],
                        button(
                            type="button",
                            class_="studio-danger-action",
                            data_remove_view_submit=True,
                        )["Remove"],
                    )
                ],
            )
        ],
    )


def _runtime_description(runtime_id: str) -> str:
    if runtime_id == "server":
        return "Uses the notebook kernel"
    if runtime_id == "wasm":
        return "Runs locally in your browser"
    return "Custom preview runtime"


def _runtime_option(
    runtime_id: str,
    label_text: str,
    selected: str,
) -> Node:
    return cast(
        Node,
        button(
            {
                "type": "button",
                "class": "studio-runtime-option",
                "data-preview-runtime": runtime_id,
                "aria-pressed": str(runtime_id == selected).lower(),
            }
        )[
            node_list(
                span(class_="studio-runtime-copy")[
                    node_list(
                        strong[label_text],
                        span[_runtime_description(runtime_id)],
                    )
                ],
                span(
                    class_="studio-runtime-check",
                    aria_hidden="true",
                )["✓"],
            )
        ],
    )


def _overflow_preview_controls(
    runtimes: tuple[tuple[str, str], ...],
    selected: str,
    preview_url: str,
) -> Node:
    return cast(
        Node,
        div(
            {
                "class": "studio-overflow-preview",
                "data-preview-control": True,
            }
        )[
            node_list(
                strong(class_="studio-menu-heading")["Preview runtime"],
                div(class_="studio-overflow-runtime-status")[
                    node_list(
                        span(class_="studio-runtime-dot", aria_hidden="true"),
                        span(data_studio_status=True)["Connecting"],
                    )
                ],
                *[
                    _runtime_option(runtime_id, label_text, selected)
                    for runtime_id, label_text in runtimes
                ],
                a(
                    {
                        "class": "studio-menu-item studio-overflow-popout",
                        "data-preview-popout": True,
                        "href": preview_url,
                        "target": "_blank",
                        "rel": "noopener",
                    }
                )[node_list(popout_icon(), span["Open preview in new tab"])],
                div(class_="studio-menu-separator"),
            )
        ],
    )


def workspace_menu(
    runtimes: tuple[tuple[str, str], ...],
    selected: str,
    preview_url: str,
) -> Node:
    return cast(
        Node,
        details(class_="studio-menu studio-workspace-menu", data_layout_menu=True)[
            node_list(
                summary(
                    class_="studio-toolbar-action",
                    aria_label="Workspace options",
                )[node_list(more_icon())],
                div(class_="studio-menu-popover studio-workspace-popover")[
                    node_list(
                        _overflow_preview_controls(
                            runtimes,
                            selected,
                            preview_url,
                        ),
                        strong(class_="studio-menu-heading")["Show"],
                        mode_navigation(overflow=True),
                        strong(class_="studio-menu-heading")["Workspace"],
                        button(
                            type="button",
                            class_="studio-menu-item",
                            data_layout_action="workspace",
                        )["Open saved layout"],
                        button(
                            type="button",
                            class_="studio-menu-item",
                            data_layout_action="arrange",
                        )["Arrange panes"],
                        div(class_="studio-menu-separator"),
                        button(
                            type="button",
                            class_="studio-menu-item",
                            data_layout_action="equalize",
                        )["Equalize split sizes"],
                        button(
                            type="button",
                            class_="studio-menu-item",
                            data_layout_action="reset",
                        )["Restore workspace"],
                    )
                ],
            )
        ],
    )


def compact_tabs() -> Node:
    return cast(
        Node,
        nav(
            {
                "class": "studio-compact-tabs",
                "data-compact-tabs": True,
                "aria-label": "Studio surface",
                "hidden": True,
            }
        )[
            node_list(
                *[
                    button(
                        type="button",
                        data_compact_surface=surface,
                        aria_pressed=str(surface == "notebook").lower(),
                    )[label_text]
                    for surface, label_text in (
                        ("notebook", "Notebook"),
                        ("source", "HTML/CSS"),
                        ("preview", "Preview"),
                    )
                ]
            )
        ],
    )


def _runtime_menu(
    runtimes: tuple[tuple[str, str], ...],
    selected: str,
) -> Node:
    selected_label = next(
        label for runtime_id, label in runtimes if runtime_id == selected
    )
    return cast(
        Node,
        details(
            {
                "class": "studio-menu studio-runtime-menu",
                "data-preview-control": True,
                "data-runtime-menu": True,
            }
        )[
            node_list(
                summary(
                    {
                        "class": "studio-runtime-trigger",
                        "aria-label": f"{selected_label} preview runtime",
                        "data-runtime-trigger": True,
                    }
                )[
                    node_list(
                        span(class_="studio-runtime-dot", aria_hidden="true"),
                        span(data_preview_runtime_label=True)[selected_label],
                        span(
                            {
                                "class": "studio-visually-hidden",
                                "data-studio-status": True,
                            }
                        )["Connecting"],
                        menu_chevron(),
                    )
                ],
                div(class_="studio-menu-popover studio-runtime-popover")[
                    node_list(
                        strong(class_="studio-menu-heading")["Preview runtime"],
                        *[
                            _runtime_option(runtime_id, label_text, selected)
                            for runtime_id, label_text in runtimes
                        ],
                    )
                ],
            )
        ],
    )


def mode_navigation(*, overflow: bool = False) -> Node:
    classes = (
        "studio-overflow-modes" if overflow else "studio-modes studio-primary-modes"
    )
    modes = (
        (
            ("notebook", "Notebook"),
            ("split", "Build"),
            ("preview", "Preview"),
            ("code", "HTML & CSS"),
        )
        if overflow
        else (
            ("notebook", "Notebook"),
            ("split", "Build"),
            ("preview", "Preview"),
        )
    )
    return cast(
        Node,
        nav(
            {
                "class": classes,
                "aria-label": "Studio mode",
            }
        )[
            node_list(
                *[
                    button(
                        {
                            "type": "button",
                            "class": "studio-menu-item" if overflow else None,
                            "data-studio-mode": mode,
                            "aria-pressed": str(mode == "split").lower(),
                        }
                    )[label_text]
                    for mode, label_text in modes
                ]
            )
        ],
    )


def toolbar(
    config: StudioConfig,
    selected: str,
    runtimes: tuple[tuple[str, str], ...],
    preview_url: str,
) -> Node:
    return cast(
        Node,
        header(class_="studio-toolbar")[
            node_list(
                div(class_="studio-title")[
                    node_list(
                        span(class_="studio-brand-mark")[marimo_mark()],
                        span(class_="studio-notebook")[config.notebook.name],
                        span(class_="studio-title-separator")["/"],
                        view_menu(config, selected),
                    )
                ],
                mode_navigation(),
                div(class_="studio-controls")[
                    node_list(
                        _runtime_menu(runtimes, config.default_runtime),
                        a(
                            {
                                "class": "studio-toolbar-action",
                                "data-preview-control": True,
                                "data-preview-popout": True,
                                "href": preview_url,
                                "target": "_blank",
                                "rel": "noopener",
                                "aria-label": "Open preview in a new tab",
                            }
                        )[popout_icon()],
                        workspace_menu(
                            runtimes,
                            config.default_runtime,
                            preview_url,
                        ),
                    )
                ],
                compact_tabs(),
                span(
                    {
                        "class": "studio-visually-hidden",
                        "data-studio-status": True,
                        "data-studio-live-status": True,
                        "role": "status",
                    }
                )["Connecting"],
            )
        ],
    )


def pane_menu(surface: str) -> Node:
    return cast(
        Node,
        details(class_="studio-pane-menu", data_pane_menu=surface)[
            node_list(
                summary(
                    class_="studio-pane-menu-trigger",
                    aria_label=f"Arrange {surface} pane",
                )[
                    node_list(
                        span(class_="studio-pane-menu-label")["Arrange"],
                        menu_chevron(),
                    )
                ],
                div(class_="studio-menu-popover studio-pane-popover")[
                    node_list(div(data_pane_actions=True))
                ],
            )
        ],
    )
