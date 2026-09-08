"""Own accepted Studio editor sessions through reconnect and final close."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock, RLock
from typing import Any
from weakref import WeakKeyDictionary, WeakSet, WeakValueDictionary, ref

from marimo._session.events import SessionEventListener


@dataclass
class _StudioSessionLifetime:
    manager: Callable[[], Any | None]
    owners: set[object]
    # Active client bindings retain callbacks across transport reconnects.
    callbacks: WeakValueDictionary[tuple[object, object], Callable[[], object]]
    settling: bool = False
    settlement_lock: Lock = field(default_factory=Lock, repr=False)


_STUDIO_SESSION_LIFETIMES: WeakKeyDictionary[Any, _StudioSessionLifetime] = (
    WeakKeyDictionary()
)
_STUDIO_SESSION_LIFETIME_MANAGERS: WeakKeyDictionary[Any, set[object]] = (
    WeakKeyDictionary()
)
_STUDIO_SESSION_LIFETIMES_LOCK = RLock()
_STUDIO_SESSION_LIFETIME_OWNERS = 0
_STUDIO_SESSION_LIFETIMES_CLOSING = False
_STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS: WeakSet[Any] = WeakSet()


def session_is_owned(session: object) -> bool:
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        return session in _STUDIO_SESSION_LIFETIMES


def _accept_studio_session(
    manager: Any,
    session_id: object,
    session: Any,
    on_close: Callable[[], object] | None,
    owner: object | None,
) -> bool:
    if on_close is None or owner is None:
        return False
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        owners = _STUDIO_SESSION_LIFETIME_MANAGERS.get(manager)
        if (
            _STUDIO_SESSION_LIFETIMES_CLOSING
            or manager in _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS
            or owners is None
            or owner not in owners
        ):
            return False
        if _canonical_session_id(manager, session) is None:
            return False
        lifetime = _STUDIO_SESSION_LIFETIMES.get(session)
        if lifetime is None:
            lifetime = _StudioSessionLifetime(
                ref(manager),
                {owner},
                WeakValueDictionary(),
            )
            _STUDIO_SESSION_LIFETIMES[session] = lifetime
        elif lifetime.settling:
            return False
        lifetime.manager = ref(manager)
        lifetime.owners.add(owner)
        lifetime.callbacks[owner, session_id] = on_close
        return True


def _notify_closed_studio_session(session: Any) -> None:
    released: _StudioSessionLifetime | None = None
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        lifetime = _STUDIO_SESSION_LIFETIMES.get(session)
        if lifetime is None:
            return
        manager = lifetime.manager()
        if manager is not None and _canonical_session_id(manager, session) is not None:
            return
        released = lifetime
    if released is not None:
        _release_studio_session_lifetimes(
            ((session, released),),
            require_detached=True,
        )


def _open_studio_session_lifetimes() -> bool:
    global _STUDIO_SESSION_LIFETIME_OWNERS
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        if _STUDIO_SESSION_LIFETIMES_CLOSING:
            return False
        _STUDIO_SESSION_LIFETIME_OWNERS += 1
        return True


def _close_studio_session_lifetimes() -> None:
    global _STUDIO_SESSION_LIFETIME_OWNERS, _STUDIO_SESSION_LIFETIMES_CLOSING
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        if _STUDIO_SESSION_LIFETIME_OWNERS <= 0:
            return
        if _STUDIO_SESSION_LIFETIME_OWNERS > 1:
            _STUDIO_SESSION_LIFETIME_OWNERS -= 1
            return
        if _STUDIO_SESSION_LIFETIMES_CLOSING:
            raise RuntimeError("Studio session lifetime cleanup is already running")
        _STUDIO_SESSION_LIFETIMES_CLOSING = True
        lifetimes = tuple(_STUDIO_SESSION_LIFETIMES.items())
    try:
        _release_studio_session_lifetimes(lifetimes)
    except BaseException:
        with _STUDIO_SESSION_LIFETIMES_LOCK:
            _STUDIO_SESSION_LIFETIMES_CLOSING = False
        raise
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        _STUDIO_SESSION_LIFETIME_OWNERS = 0
        _STUDIO_SESSION_LIFETIMES_CLOSING = False
        for manager in tuple(_STUDIO_SESSION_LIFETIME_MANAGERS):
            manager._event_bus.unsubscribe(_SESSION_LIFETIME_LISTENER)
        _STUDIO_SESSION_LIFETIME_MANAGERS.clear()


def _track_manager_session_lifetimes(manager: Any, owner: object) -> bool:
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        if (
            _STUDIO_SESSION_LIFETIMES_CLOSING
            or manager in _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS
        ):
            return False
        owners = _STUDIO_SESSION_LIFETIME_MANAGERS.get(manager)
        if owners is None:
            manager._event_bus.subscribe(_SESSION_LIFETIME_LISTENER)
            owners = set()
            _STUDIO_SESSION_LIFETIME_MANAGERS[manager] = owners
        owners.add(owner)
        return True


def _close_manager_session_lifetimes(manager: Any, owner: object) -> None:
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        owners = _STUDIO_SESSION_LIFETIME_MANAGERS.get(manager)
        if owners is None:
            return
        if owner not in owners:
            return
        if manager in _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS:
            raise RuntimeError("Studio manager lifetime cleanup is already running")
        _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS.add(manager)
        owned = tuple(
            (session, lifetime)
            for session, lifetime in _STUDIO_SESSION_LIFETIMES.items()
            if lifetime.manager() is manager and owner in lifetime.owners
        )
    try:
        for session, lifetime in owned:
            _release_studio_session_lifetime_owner(session, lifetime, owner)
    except BaseException:
        with _STUDIO_SESSION_LIFETIMES_LOCK:
            _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS.discard(manager)
        raise
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        owners = _STUDIO_SESSION_LIFETIME_MANAGERS.get(manager)
        if owners is not None:
            owners.discard(owner)
            if not owners:
                _STUDIO_SESSION_LIFETIME_MANAGERS.pop(manager, None)
                manager._event_bus.unsubscribe(_SESSION_LIFETIME_LISTENER)
        _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS.discard(manager)


def _release_studio_session_lifetime_owner(
    session: Any,
    lifetime: _StudioSessionLifetime,
    owner: object,
) -> None:
    with lifetime.settlement_lock:
        with _STUDIO_SESSION_LIFETIMES_LOCK:
            if _STUDIO_SESSION_LIFETIMES.get(session) is not lifetime:
                return
            callbacks = {
                key: callback
                for key, callback in lifetime.callbacks.items()
                if key[0] is owner
            }
            for key in callbacks:
                lifetime.callbacks.pop(key, None)
            if owner not in lifetime.owners:
                return
            lifetime.owners.remove(owner)
            lifetime.settling = True
            final_owner = not lifetime.owners
        try:
            if final_owner:
                _close_exact_studio_session(session, lifetime)
        except BaseException:
            with _STUDIO_SESSION_LIFETIMES_LOCK:
                if _STUDIO_SESSION_LIFETIMES.get(session) is lifetime:
                    lifetime.owners.add(owner)
                    lifetime.callbacks.update(callbacks)
                    lifetime.settling = False
            raise
        failure: BaseException | None = None
        for key, callback in tuple(callbacks.items()):
            try:
                callback()
            except BaseException as error:
                if failure is None:
                    failure = error
            else:
                callbacks.pop(key)
        with _STUDIO_SESSION_LIFETIMES_LOCK:
            if _STUDIO_SESSION_LIFETIMES.get(session) is lifetime:
                lifetime.callbacks.update(callbacks)
                if callbacks:
                    lifetime.owners.add(owner)
                lifetime.settling = False
                if final_owner and not callbacks:
                    _STUDIO_SESSION_LIFETIMES.pop(session, None)
        if failure is not None:
            raise failure


def _release_studio_session_lifetimes(
    owned: tuple[tuple[Any, _StudioSessionLifetime], ...],
    *,
    require_detached: bool = False,
) -> None:
    failure: BaseException | None = None
    for session, lifetime in owned:
        with lifetime.settlement_lock:
            with _STUDIO_SESSION_LIFETIMES_LOCK:
                if _STUDIO_SESSION_LIFETIMES.get(session) is not lifetime:
                    continue
                if (
                    require_detached
                    and (manager := lifetime.manager()) is not None
                    and _canonical_session_id(manager, session) is not None
                ):
                    continue
                lifetime.settling = True
                callbacks = dict(lifetime.callbacks.items())
                lifetime.callbacks.clear()
            try:
                _close_exact_studio_session(session, lifetime)
            except BaseException as error:
                with _STUDIO_SESSION_LIFETIMES_LOCK:
                    if _STUDIO_SESSION_LIFETIMES.get(session) is lifetime:
                        lifetime.callbacks.update(callbacks)
                        lifetime.settling = False
                if failure is None:
                    failure = error
                continue
            failed_callbacks: dict[tuple[object, object], Callable[[], object]] = {}
            for owner, callback in callbacks.items():
                try:
                    callback()
                except BaseException as error:
                    failed_callbacks[owner] = callback
                    if failure is None:
                        failure = error
            with _STUDIO_SESSION_LIFETIMES_LOCK:
                if _STUDIO_SESSION_LIFETIMES.get(session) is lifetime:
                    lifetime.callbacks.update(failed_callbacks)
                    lifetime.settling = False
                    if not failed_callbacks:
                        _STUDIO_SESSION_LIFETIMES.pop(session, None)
    if failure is not None:
        raise failure


def _close_exact_studio_session(
    session: Any,
    lifetime: _StudioSessionLifetime,
) -> None:
    manager = lifetime.manager()
    if manager is not None:
        canonical_id = _canonical_session_id(manager, session)
        if canonical_id is not None:
            manager.close_session(canonical_id)
        if _canonical_session_id(manager, session) is not None:
            raise RuntimeError("Marimo retained a closed Studio editor session")


def _canonical_session_id(manager: Any, session: Any) -> object | None:
    return next(
        (key for key, current in manager.sessions.items() if current is session),
        None,
    )


class _SessionLifetimeListener(SessionEventListener):
    async def on_session_closed(self, session: Any) -> None:
        _notify_closed_studio_session(session)


_SESSION_LIFETIME_LISTENER = _SessionLifetimeListener()
