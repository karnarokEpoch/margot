"""Blocking, peer-to-peer D-Bus client over AF_UNIX for `margot install`.

jeepney's blocking ``open_dbus_connection()`` always sends ``Hello()``, which the systemd user manager's
private socket does not answer. This client uses jeepney's sans-IO pieces (the SASL authenticator, the
message parser and message serialisation) over a plain socket, so ``Hello()`` is sent only when asked for.

Every wait has a deadline: ``connect`` and ``call`` raise ``DBusError`` instead of blocking forever.
"""

from socket import AF_UNIX, SOCK_STREAM, socket
from time import monotonic
from typing import Any, Self

from jeepney import Message
from jeepney.auth import BEGIN, AuthenticationError, Authenticator
from jeepney.bus_messages import message_bus
from jeepney.low_level import HeaderFields, MessageType, Parser

from margot import console

_RECV_BYTES = 65536
_AUTH_HINT = (
    "In a rootless container, run with --userns=keep-id so the process uid matches the host user, "
    "or pass --no-reload to only place the files."
)


class DBusError(Exception):
    """A D-Bus connection, authentication, call or reply failed."""


def _remaining(deadline: float, path: str) -> float:
    """Seconds left before ``deadline``. Raises DBusError when none are left."""
    left = deadline - monotonic()
    if left <= 0:
        raise DBusError(f"the D-Bus call to {path} timed out")
    return left


class DBusConnection:
    """One authenticated connection to a D-Bus socket. Use ``connect`` to open it; close it with ``with``."""

    def __init__(self, sock: socket, path: str) -> None:
        self._sock = sock
        self._path = path
        self._parser = Parser()
        self._serial = 0
        self._closed = False

    @classmethod
    def connect(cls, path: str, *, hello: bool, timeout: float) -> Self:
        """Connect to ``path``, authenticate with EXTERNAL and optionally send Hello().

        Args:
            path: The AF_UNIX socket path.
            hello: Send org.freedesktop.DBus.Hello(). Needed on the session bus, not on the private socket.
            timeout: Seconds allowed for the whole handshake, Hello included.

        Raises:
            DBusError: Connection refused, authentication rejected, closed, or timed out.
        """
        deadline = monotonic() + timeout
        sock = socket(AF_UNIX, SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            sock.connect(path)
        except OSError as error:
            sock.close()
            raise DBusError(f"could not connect to {path}: {error}") from error
        connection = cls(sock, path)
        try:
            connection._authenticate(deadline)
            if hello:
                connection.call(message_bus.Hello(), timeout=_remaining(deadline, path))
        except BaseException:
            connection.close()
            raise
        console.debug(f"D-Bus connection to {path} is authenticated (hello={hello}).")
        return connection

    def call(self, message: Message, timeout: float) -> tuple[Any, ...]:
        """Send a method call and return the body of its reply. Signals and other replies are skipped.

        Raises:
            DBusError: Error reply (with its D-Bus error name), closed socket, or no reply before ``timeout``.
        """
        if self._closed:
            raise DBusError(f"the D-Bus connection to {self._path} is closed")
        deadline = monotonic() + timeout
        self._serial += 1
        serial = self._serial
        member = message.header.fields.get(HeaderFields.member, "?")
        console.debug(f"D-Bus call {member} to {self._path} (serial {serial}).")
        self._send(message.serialise(serial=serial), deadline)
        while True:
            reply = self._parser.get_next_message()
            if reply is None:
                self._parser.add_data(self._recv(deadline))
                continue
            if reply.header.fields.get(HeaderFields.reply_serial) != serial:
                continue
            if reply.header.message_type is MessageType.error:
                name = reply.header.fields.get(HeaderFields.error_name, "org.freedesktop.DBus.Error.Failed")
                text = reply.body[0] if reply.body and isinstance(reply.body[0], str) else ""
                raise DBusError(f"{name}: {text}" if text else name)
            return reply.body

    def close(self) -> None:
        """Close the socket. Calling it twice is harmless."""
        if not self._closed:
            self._closed = True
            self._sock.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _authenticate(self, deadline: float) -> None:
        """Run the client side of the SASL EXTERNAL exchange, then send BEGIN.

        Raises:
            DBusError: The server refused EXTERNAL (usually a user-namespace uid mismatch) or the exchange broke.
        """
        self._send(b"\0", deadline)
        auth = Authenticator(enable_fds=False, inc_null_byte=False)
        for line in auth:
            self._send(line, deadline)
            try:
                auth.feed(self._recv(deadline))
            except AuthenticationError as error:
                answer = bytes(error.data).decode("utf-8", errors="replace").strip()
                raise DBusError(
                    f"D-Bus authentication was refused by {self._path} (server answered: {answer or 'nothing'}). {_AUTH_HINT}"
                ) from error
        self._send(BEGIN, deadline)

    def _send(self, data: bytes, deadline: float) -> None:
        self._sock.settimeout(_remaining(deadline, self._path))
        try:
            self._sock.sendall(data)
        except TimeoutError as error:
            raise DBusError(f"the D-Bus call to {self._path} timed out") from error
        except OSError as error:
            raise DBusError(f"the D-Bus connection to {self._path} failed while sending: {error}") from error

    def _recv(self, deadline: float) -> bytes:
        self._sock.settimeout(_remaining(deadline, self._path))
        try:
            data = self._sock.recv(_RECV_BYTES)
        except TimeoutError as error:
            raise DBusError(f"the D-Bus call to {self._path} timed out") from error
        except OSError as error:
            raise DBusError(f"the D-Bus connection to {self._path} failed: {error}") from error
        if not data:
            raise DBusError(f"the D-Bus socket {self._path} was closed by the server")
        return data
