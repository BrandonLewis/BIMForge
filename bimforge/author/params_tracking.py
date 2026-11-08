"""Declared-but-never-read spec parameters.

A transcribed, sheet-cited value in a spec's `params` that no family code reads
is not documentation: it reads as though the model honours it. A skew angle,
two support stations or a whole vertical-profile block can sit in the spec,
correctly transcribed, while the family builds square, flat and mis-stationed.

`TrackedParams` wraps the params mapping and records every leaf actually read;
`unread_params` reports the declared leaves that were not. `est-bim build`
applies it from the spec's gate block:

    gate:
      unread_params: warn      # off (default) | warn | error
      ignore: [notes, sheets]  # path prefixes that are documentation only

Examples:
    tracked = TrackedParams(spec["params"])
    model = builder(tracked, ctx)
    for path in unread_params(tracked, ignore=("notes",)):
        print(f"warning: spec declares {path!r} but the family never reads it")
"""
from __future__ import annotations

from collections.abc import Mapping

UNREAD_PARAM_MODES = ("off", "warn", "error")


class TrackedParams(Mapping):
    """A read-recording proxy over the spec's ``params`` mapping.

    Wraps nested mappings and sequences lazily, so the recorded paths are the
    leaves a family actually touched. Iterating ``.items()`` or ``.values()``
    counts as reading the children, which is right: a family that walks
    ``wingwalls["units"]`` has read every unit.
    """

    __slots__ = ("_data", "_seen", "_prefix")

    def __init__(self, data, seen: set | None = None, prefix: str = "") -> None:
        self._data = data
        self._seen = set() if seen is None else seen
        self._prefix = prefix

    def __getitem__(self, key):
        return self._wrap(f"{self._prefix}{key}", self._data[key])

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def _wrap(self, path: str, value):
        self._seen.add(path)
        if isinstance(value, Mapping):
            return TrackedParams(value, self._seen, path + ".")
        if isinstance(value, (list, tuple)):
            return [self._wrap(f"{path}[{i}]", v) for i, v in enumerate(value)]
        return value

    def declared(self) -> set[str]:
        """Every leaf path the spec declares."""
        return _leaves(self._data, self._prefix)

    def seen(self) -> set[str]:
        """Every path the family has read so far."""
        return set(self._seen)


def _leaves(data, prefix: str = "") -> set[str]:
    out: set[str] = set()
    if isinstance(data, Mapping):
        for k, v in data.items():
            out |= _leaves(v, f"{prefix}{k}.") or {f"{prefix}{k}"}
    elif isinstance(data, (list, tuple)):
        for i, v in enumerate(data):
            child = _leaves(v, f"{prefix[:-1]}[{i}].")
            out |= child or {f"{prefix[:-1]}[{i}]"}
    return out


def unread_params(tracked: TrackedParams, ignore=()) -> list[str]:
    """Spec leaves the family never read, ignoring any path that is, or sits
    under, one of `ignore`."""
    declared, seen = tracked.declared(), tracked.seen()
    return sorted(p for p in declared - seen
                  if not any(p == g or p.startswith(g + ".") or
                             p.startswith(g + "[") for g in ignore))


def unread_params_check(tracked: TrackedParams, ignore=()):
    """`unread_params` as a pre-emit gate check. Appended after the family's
    own checks, so a parameter a check reads lazily has been read by then."""
    def check_unread_params(_model) -> list[str]:
        return [f"spec declares {p!r} but the family never reads it"
                for p in unread_params(tracked, ignore)]
    return check_unread_params
