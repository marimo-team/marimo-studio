"""Coordinate agent work that depends on a live Studio browser.

Agents can select a named view in one connected browser and request fresh
evidence about the page that browser rendered. When several Studio tabs are
open, the caller must identify the intended browser or native editor session.

Activation stays tied to the browser, editor session, selected view, and active
view state it observed. Observation additionally names the runtime and
presentation revision being checked. Public query writes use the current
session binding and an ordered query generation. A reconnect, manual view
change, newer query, or replacement session rejects stale replies instead of
letting them complete older work.
"""
