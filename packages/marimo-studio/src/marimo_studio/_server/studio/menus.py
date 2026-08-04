"""Render Studio toolbar and pane menus."""

from __future__ import annotations

from typing import cast

from htpy import (
    Node,
    button,
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


def layout_menu() -> Node:
    return cast(
        Node,
        details(class_="studio-menu studio-layout-menu", data_layout_menu=True)[
            node_list(
                summary(class_="studio-menu-trigger")[
                    node_list("Layout", menu_chevron())
                ],
                div(class_="studio-menu-popover studio-layout-popover")[
                    node_list(
                        strong(class_="studio-menu-heading")["Layout"],
                        button(
                            type="button",
                            class_="studio-menu-item",
                            data_layout_action="equalize",
                        )["Equalize split sizes"],
                        button(
                            type="button",
                            class_="studio-menu-item",
                            data_layout_action="reset",
                        )["Restore default"],
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
                        ("source", "Source"),
                        ("preview", "Preview"),
                    )
                ]
            )
        ],
    )


def _runtime_switch(
    runtimes: tuple[tuple[str, str], ...],
    selected: str,
) -> Node:
    return cast(
        Node,
        div(
            {
                "class": "studio-runtime-switch",
                "role": "group",
                "aria-label": "Preview runtime",
            }
        )[
            node_list(
                *[
                    button(
                        {
                            "type": "button",
                            "data-preview-runtime": runtime_id,
                            "aria-pressed": str(runtime_id == selected).lower(),
                        }
                    )[label_text]
                    for runtime_id, label_text in runtimes
                ]
            )
        ],
    )


def toolbar(
    config: StudioConfig,
    selected: str,
    runtimes: tuple[tuple[str, str], ...],
) -> Node:
    return cast(
        Node,
        header(class_="studio-toolbar")[
            node_list(
                div(class_="studio-title")[
                    node_list(
                        span(class_="studio-wordmark")["Studio"],
                        span(class_="studio-notebook")[config.notebook.name],
                        span(class_="studio-title-separator")["/"],
                        view_menu(config, selected),
                    )
                ],
                div(class_="studio-controls")[
                    node_list(
                        _runtime_switch(runtimes, config.default_runtime),
                        compact_tabs(),
                        layout_menu(),
                    )
                ],
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
                        span(class_="studio-pane-menu-label")["Pane"],
                        menu_chevron(),
                    )
                ],
                div(class_="studio-menu-popover studio-pane-popover")[
                    node_list(div(data_pane_actions=True))
                ],
            )
        ],
    )
