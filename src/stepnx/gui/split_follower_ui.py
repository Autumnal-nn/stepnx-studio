from __future__ import annotations


def _rewrite_route_labels(item) -> None:
    text = item.text(1)
    if text:
        text = text.replace("random start", "random at chart load")
        if "random trigger" in text:
            if "group " in text:
                text = text.replace("random trigger", "follower block")
            else:
                text = text.replace("random trigger", "random at block start")
        text = text.replace("group ", "bank ")
        item.setText(1, text)
    for index in range(item.childCount()):
        _rewrite_route_labels(item.child(index))


def install_split_follower_ui(window) -> None:
    """Keep Routes terminology aligned with selector timing/bank semantics."""

    if getattr(window, "_stepnx_split_follower_ui", False):
        return
    window._stepnx_split_follower_ui = True

    original_populate = window._populate_routes

    def populate_routes() -> None:
        original_populate()
        for index in range(window.routes.topLevelItemCount()):
            _rewrite_route_labels(window.routes.topLevelItem(index))

    window._populate_routes = populate_routes
    populate_routes()
