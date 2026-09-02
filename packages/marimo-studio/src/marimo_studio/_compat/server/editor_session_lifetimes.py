"""Own accepted Studio editor sessions through reconnect and final close."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock, RLock
from typing import Any
from weakref import WeakKeyDictionary, WeakSet, ref


@dataclass
class _StudioSessionLifetime:
    manager: Callable[[], Any | None]
    session_id: object
    callbacks: dict[object, Callable[[], object]]
    generation: int = 0
    timer: asyncio.TimerHandle | None = None
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
        lifetime = _STUDIO_SESSION_LIFETIMES.get(session)
        if lifetime is None:
            lifetime = _StudioSessionLifetime(
                ref(manager),
                session_id,
                {owner: on_close},
            )
            _STUDIO_SESSION_LIFETIMES[session] = lifetime
        elif lifetime.settling:
            return False
        elif lifetime.timer is not None:
            lifetime.timer.cancel()
        lifetime.manager = ref(manager)
        lifetime.session_id = session_id
        lifetime.callbacks[owner] = on_close
        lifetime.generation += 1
        lifetime.timer = None
        return True


def _schedule_studio_session_close(session: Any) -> None:
    released: _StudioSessionLifetime | None = None
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        lifetime = _STUDIO_SESSION_LIFETIMES.get(session)
        if lifetime is None:
            return
        manager = lifetime.manager()
        if manager is None or manager.get_session(lifetime.session_id) is not session:
            released = lifetime
        else:
            if lifetime.timer is not None:
                lifetime.timer.cancel()
            lifetime.generation += 1
            generation = lifetime.generation
            lifetime.timer = asyncio.get_running_loop().call_later(
                session.ttl_seconds,
                _close_studio_session,
                session,
                generation,
            )
    if released is not None:
        _release_studio_session_lifetimes(
            ((session, released),),
            require_detached=True,
        )


def _notify_closed_studio_session(session: Any) -> None:
    released: _StudioSessionLifetime | None = None
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        lifetime = _STUDIO_SESSION_LIFETIMES.get(session)
        if lifetime is None:
            return
        manager = lifetime.manager()
        if manager is not None and manager.get_session(lifetime.session_id) is session:
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
        _STUDIO_SESSION_LIFETIME_MANAGERS.clear()


def _track_manager_session_lifetimes(manager: Any, owner: object) -> bool:
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        if (
            _STUDIO_SESSION_LIFETIMES_CLOSING
            or manager in _STUDIO_SESSION_LIFETIME_CLOSING_MANAGERS
        ):
            return False
        _STUDIO_SESSION_LIFETIME_MANAGERS.setdefault(manager, set()).add(owner)
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
            if lifetime.manager() is manager and owner in lifetime.callbacks
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
            callback = lifetime.callbacks.pop(owner, None)
            if callback is None:
                return
            lifetime.settling = True
            final_owner = not lifetime.callbacks
            if final_owner and lifetime.timer is not None:
                lifetime.timer.cancel()
        try:
            if final_owner:
                _close_exact_studio_session(session, lifetime)
            callback()
        except BaseException:
            with _STUDIO_SESSION_LIFETIMES_LOCK:
                if _STUDIO_SESSION_LIFETIMES.get(session) is lifetime:
                    lifetime.callbacks[owner] = callback
                    lifetime.settling = False
            raise
        with _STUDIO_SESSION_LIFETIMES_LOCK:
            if _STUDIO_SESSION_LIFETIMES.get(session) is lifetime:
                lifetime.settling = False
                if final_owner:
                    _STUDIO_SESSION_LIFETIMES.pop(session, None)


def _release_studio_session_lifetimes(
    owned: tuple[tuple[Any, _StudioSessionLifetime], ...],
    *,
    expected_generation: int | None = None,
    require_detached: bool = False,
    require_disconnected: bool = False,
) -> None:
    from marimo._session.model import ConnectionState

    failure: BaseException | None = None
    for session, lifetime in owned:
        with lifetime.settlement_lock:
            with _STUDIO_SESSION_LIFETIMES_LOCK:
                if _STUDIO_SESSION_LIFETIMES.get(session) is not lifetime:
                    continue
                if (
                    (
                        expected_generation is not None
                        and lifetime.generation != expected_generation
                    )
                    or (
                        require_detached
                        and (manager := lifetime.manager()) is not None
                        and manager.get_session(lifetime.session_id) is session
                    )
                    or (
                        require_disconnected
                        and session.connection_state() is ConnectionState.OPEN
                    )
                ):
                    continue
                lifetime.settling = True
                callbacks = dict(lifetime.callbacks)
                lifetime.callbacks.clear()
                if lifetime.timer is not None:
                    lifetime.timer.cancel()
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
            failed_callbacks: dict[object, Callable[[], object]] = {}
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
    if manager is not None and manager.get_session(lifetime.session_id) is session:
        manager.close_session(lifetime.session_id)
    if manager is not None and manager.get_session(lifetime.session_id) is session:
        raise RuntimeError("Marimo retained a closed Studio editor session")


def _close_studio_session(session: Any, generation: int) -> None:
    with _STUDIO_SESSION_LIFETIMES_LOCK:
        lifetime = _STUDIO_SESSION_LIFETIMES.get(session)
        if lifetime is None or lifetime.generation != generation:
            return
        lifetime.timer = None
    _release_studio_session_lifetimes(
        ((session, lifetime),),
        expected_generation=generation,
        require_disconnected=True,
    )
