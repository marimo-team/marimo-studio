"""Render the persistent notebook, source, and preview surfaces."""

from __future__ import annotations

from typing import cast

from htpy import Element, Node, a, button, div, header, main, pre, section, span, strong

from marimo_studio._html import node_list
from marimo_studio._server.studio.menus import pane_menu

_IFRAME = Element("iframe")


def _notebook_pane(root_url: str) -> Node:
    return cast(
        Node,
        section(class_="studio-pane", data_surface="notebook", aria_label="Notebook")[
            node_list(
                header(class_="studio-pane-header")[
                    node_list(
                        strong["Notebook"],
                        div(class_="studio-pane-actions")[
                            node_list(
                                button(
                                    type="button",
                                    class_="studio-icon-action",
                                    data_focus_surface="notebook",
                                    aria_label="Focus notebook",
                                )["Focus"],
                                pane_menu("notebook"),
                            )
                        ],
                    )
                ],
                div(class_="studio-pane-content")[
                    node_list(
                        _IFRAME(
                            {
                                "data-editor-frame": True,
                                "src": root_url,
                                "title": "Marimo editor",
                                "allow": "clipboard-read; clipboard-write",
                            }
                        )
                    )
                ],
            )
        ],
    )


def _source_pane(selected: str) -> Node:
    return cast(
        Node,
        section(class_="studio-pane", data_surface="source", aria_label="View source")[
            node_list(
                header(class_="studio-pane-header studio-source-header")[
                    node_list(
                        div(
                            {
                                "class": "studio-source-tabs",
                                "role": "tablist",
                                "aria-label": "View source files",
                            }
                        )[
                            node_list(
                                button(
                                    {
                                        "id": "studio-source-tab-html",
                                        "type": "button",
                                        "role": "tab",
                                        "data-source-tab": "index.html",
                                        "aria-selected": "true",
                                        "aria-controls": "studio-source-html",
                                        "tabindex": "0",
                                    }
                                )["HTML"],
                                button(
                                    {
                                        "id": "studio-source-tab-css",
                                        "type": "button",
                                        "role": "tab",
                                        "data-source-tab": "app.css",
                                        "aria-selected": "false",
                                        "aria-controls": "studio-source-css",
                                        "tabindex": "-1",
                                    }
                                )["CSS"],
                            )
                        ],
                        div(class_="studio-source-meta")[
                            node_list(
                                span(data_source_path=True)[f"{selected}/index.html"],
                                span(
                                    {
                                        "class": "studio-source-status",
                                        "data-source-status": True,
                                        "role": "status",
                                    }
                                )["Loading"],
                                button(
                                    type="button",
                                    class_="studio-icon-action",
                                    data_focus_surface="source",
                                    aria_label="Focus source",
                                )["Focus"],
                                pane_menu("source"),
                            )
                        ],
                    )
                ],
                _source_conflict(),
                div(class_="studio-pane-content studio-source-content")[
                    node_list(
                        div(
                            {
                                "id": "studio-source-html",
                                "class": "studio-source-editor",
                                "data-source-editor": "index.html",
                                "role": "tabpanel",
                                "aria-labelledby": "studio-source-tab-html",
                            }
                        ),
                        div(
                            {
                                "id": "studio-source-css",
                                "class": "studio-source-editor",
                                "data-source-editor": "app.css",
                                "role": "tabpanel",
                                "aria-labelledby": "studio-source-tab-css",
                                "hidden": True,
                            }
                        ),
                    )
                ],
            )
        ],
    )


def _source_conflict() -> Node:
    return cast(
        Node,
        node_list(
            div(
                {
                    "class": "studio-source-conflict",
                    "data-source-conflict": True,
                    "role": "alert",
                    "hidden": True,
                }
            )[
                node_list(
                    span(data_source_conflict_message=True),
                    div[
                        node_list(
                            button(type="button", data_conflict_compare=True)[
                                "Compare"
                            ],
                            button(type="button", data_conflict_disk=True)["Use disk"],
                            button(type="button", data_conflict_local=True)[
                                "Keep mine"
                            ],
                        )
                    ],
                )
            ],
            div(
                {
                    "class": "studio-source-compare",
                    "data-source-compare": True,
                    "hidden": True,
                }
            )[
                node_list(
                    section[
                        node_list(strong["Your edits"], pre(data_compare_local=True))
                    ],
                    section[node_list(strong["On disk"], pre(data_compare_disk=True))],
                )
            ],
        ),
    )


def _preview_pane(preview_url: str, selected: str) -> Node:
    return cast(
        Node,
        section(class_="studio-pane", data_surface="preview", aria_label="Preview")[
            node_list(
                header(class_="studio-pane-header")[
                    node_list(
                        strong["Preview"],
                        div(class_="studio-pane-actions")[
                            node_list(
                                span(
                                    {
                                        "class": "studio-status",
                                        "data-studio-status": True,
                                        "role": "status",
                                    }
                                )["Connecting"],
                                a(
                                    {
                                        "class": "studio-icon-action",
                                        "data-preview-popout": True,
                                        "href": preview_url,
                                        "target": "_blank",
                                        "rel": "noopener",
                                        "aria-label": "Open preview in a new tab",
                                    }
                                )["Open ↗"],
                                button(
                                    type="button",
                                    class_="studio-icon-action",
                                    data_focus_surface="preview",
                                    aria_label="Focus preview",
                                )["Focus"],
                                pane_menu("preview"),
                            )
                        ],
                    )
                ],
                div(class_="studio-pane-content")[
                    node_list(
                        _IFRAME(
                            {
                                "data-preview-frame": True,
                                "src": "about:blank",
                                "title": f"{selected} custom view",
                                "allow": "clipboard-read; clipboard-write",
                            }
                        )
                    )
                ],
            )
        ],
    )


def workspace(root_url: str, preview_url: str, selected: str) -> Node:
    """Render stable hosts for the three Studio surfaces."""
    return cast(
        Node,
        main(
            class_="studio-workspace",
            data_workspace=True,
            aria_label="Studio workspace",
        )[
            node_list(
                div(class_="studio-surface-layer")[
                    node_list(
                        _notebook_pane(root_url),
                        _source_pane(selected),
                        _preview_pane(preview_url, selected),
                    )
                ],
                div(class_="studio-divider-layer", data_divider_layer=True),
                div(class_="studio-resize-scrim", data_resize_scrim=True, hidden=True),
            )
        ],
    )
