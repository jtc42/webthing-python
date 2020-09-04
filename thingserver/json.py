import datetime
import json as _json
import types
import typing
import uuid
from base64 import b64encode

try:
    import dataclasses
except ImportError:
    # Python < 3.7
    dataclasses = None


class JSONEncoder(_json.JSONEncoder):
    """The default JSON encoder. Handles extra types compared to the
    built-in :class:`json.JSONEncoder`.
    -   :class:`datetime.datetime` and :class:`datetime.date` are
        serialized to :rfc:`822` strings. This is the same as the HTTP
        date format.
    -   :class:`uuid.UUID` is serialized to a string.
    -   :class:`dataclasses.dataclass` is passed to
        :func:`dataclasses.asdict`.
    Assign a subclass of this to :attr:`flask.Flask.json_encoder` or
    :attr:`flask.Blueprint.json_encoder` to override the default.
    """

    def default(self, o):
        """Convert ``o`` to a JSON serializable type. See
        :meth:`json.JSONEncoder.default`. Python does not support
        overriding how basic types like ``str`` or ``list`` are
        serialized, they are handled before this method.
        """
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        if dataclasses and dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, set):
            return list(o)
        if isinstance(o, bytes):
            try:  # Try unicode
                return o.decode()
            except UnicodeDecodeError:  # Otherwise, base64
                return b64encode(o).decode()
        try:
            return super().default(o)
        except TypeError:
            return f"<<non-serializable: {type(o).__qualname__}>>"
