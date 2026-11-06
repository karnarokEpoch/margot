"""Unit tests for infra/dbus.py against a stub AF_UNIX D-Bus server running in a thread.

The stub speaks the server side of the SASL handshake (EXTERNAL, OK, BEGIN), parses requests with jeepney's
Parser, and answers with messages built by jeepney. Socket paths live under a short mkdtemp directory in /tmp
because AF_UNIX paths are limited to about 108 bytes.
"""

from binascii import hexlify
from collections.abc import Callable, Iterator
from os import geteuid
from pathlib import Path
from shutil import rmtree
from socket import AF_UNIX, SOCK_STREAM, socket
from tempfile import mkdtemp
from threading import Thread
from typing import Any, Self

from jeepney import DBusAddress, Message, new_error, new_method_call, new_method_return, new_signal
from jeepney.low_level import HeaderFields, Parser
from pytest import fixture, raises

from margot.infra.dbus import DBusConnection, DBusError

PROPERTIES = DBusAddress(
    "/org/freedesktop/systemd1",
    bus_name="org.freedesktop.systemd1",
    interface="org.freedesktop.systemd1.Manager",
)
Responder = Callable[[Message], list[bytes]]


@fixture
def socket_path() -> Iterator[str]:
    """A socket path short enough for AF_UNIX, removed after the test."""
    directory = Path(mkdtemp(dir="/tmp", prefix="margot-dbus-"))
    try:
        yield str(directory / "bus")
    finally:
        rmtree(directory, ignore_errors=True)


def _read_line(conn: socket) -> bytes:
    """Read one CRLF-terminated SASL line byte by byte, so nothing past it is consumed."""
    line = b""
    while not line.endswith(b"\r\n"):
        chunk = conn.recv(1)
        if not chunk:
            raise OSError("client closed during authentication")
        line += chunk
    return line


class _Stub:
    """One accepted client, served by ``script`` in a background thread."""

    def __init__(self, path: str, script: Callable[["_Stub", socket], None]) -> None:
        self.members: list[str] = []
        self.auth_line = b""
        self._script = script
        self._listener = socket(AF_UNIX, SOCK_STREAM)
        self._listener.bind(path)
        self._listener.listen(1)
        self._thread = Thread(target=self._run, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._listener.close()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            return
        with conn:
            try:
                self._script(self, conn)
            except OSError:
                return

    def handshake(self, conn: socket, *, reject: bool = False) -> bool:
        """Answer the SASL exchange. Returns False when the server rejects EXTERNAL."""
        conn.recv(1)  # the leading NUL byte
        self.auth_line = _read_line(conn)
        if reject:
            conn.sendall(b"REJECTED EXTERNAL\r\n")
            return False
        conn.sendall(b"OK " + b"0" * 32 + b"\r\n")
        _read_line(conn)  # BEGIN
        return True

    def requests(self, conn: socket) -> Iterator[Message]:
        """Yield each complete request. Stops when the client closes the connection."""
        parser = Parser()
        while True:
            data = conn.recv(4096)
            if not data:
                return
            parser.add_data(data)
            while (message := parser.get_next_message()) is not None:
                self.members.append(str(message.header.fields.get(HeaderFields.member)))
                yield message


def _serve(responder: Responder, *, reject: bool = False) -> Callable[[_Stub, socket], None]:
    """A script that completes the handshake and answers every request with ``responder``."""

    def script(stub: _Stub, conn: socket) -> None:
        if not stub.handshake(conn, reject=reject):
            return
        for request in stub.requests(conn):
            for raw in responder(request):
                conn.sendall(raw)

    return script


def _returns(signature: str, body: tuple[Any, ...]) -> Responder:
    return lambda request: [new_method_return(request, signature, body).serialise(serial=1)]


def _hello_then(responder: Responder) -> Responder:
    """Answer Hello with a unique name, every other call with ``responder``."""

    def answer(request: Message) -> list[bytes]:
        if request.header.fields.get(HeaderFields.member) == "Hello":
            return [new_method_return(request, "s", (":1.42",)).serialise(serial=1)]
        return responder(request)

    return answer


class TestHandshake:
    """Authentication with EXTERNAL and the connection's first exchange."""

    def test_external_auth_uses_the_process_uid(self, socket_path: str) -> None:
        """Should send AUTH EXTERNAL with the hex-encoded effective uid, then BEGIN, and accept OK."""
        with (
            _Stub(socket_path, _serve(_returns("as", (["A=1"],)))) as stub,
            DBusConnection.connect(socket_path, hello=False, timeout=5),
        ):
            pass

        assert stub.auth_line == b"AUTH EXTERNAL " + hexlify(str(geteuid()).encode("ascii")) + b"\r\n"

    def test_rejected_auth_names_the_userns_fix(self, socket_path: str) -> None:
        """Should raise DBusError saying the server rejected EXTERNAL and suggesting --userns=keep-id."""
        with _Stub(socket_path, _serve(_returns("as", ([],)), reject=True)), raises(DBusError, match=r"REJECTED.*keep-id"):
            DBusConnection.connect(socket_path, hello=False, timeout=5)

    def test_missing_socket_is_a_dbus_error(self, socket_path: str) -> None:
        """Should raise DBusError when nothing listens on the path."""
        with raises(DBusError, match="could not connect"):
            DBusConnection.connect(socket_path, hello=False, timeout=5)

    def test_server_closing_during_auth_is_a_dbus_error(self, socket_path: str) -> None:
        """Should raise DBusError, not loop, when the server closes before answering AUTH."""

        def hang_up(_stub: _Stub, conn: socket) -> None:
            conn.recv(1)
            _read_line(conn)

        with _Stub(socket_path, hang_up), raises(DBusError, match="closed"):
            DBusConnection.connect(socket_path, hello=False, timeout=5)


class TestHello:
    """Hello() is sent on the session bus only: the user manager's private socket does not answer it."""

    def test_hello_is_sent_when_requested(self, socket_path: str) -> None:
        """Should send org.freedesktop.DBus.Hello first when hello=True."""
        with (
            _Stub(socket_path, _serve(_hello_then(_returns("as", ([],))))) as stub,
            DBusConnection.connect(socket_path, hello=True, timeout=5),
        ):
            assert stub.members == ["Hello"]

    def test_hello_is_not_sent_by_default(self, socket_path: str) -> None:
        """Should send no Hello when hello=False: the first request is the caller's own call."""
        with (
            _Stub(socket_path, _serve(_returns("as", (["A=1"],)))) as stub,
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
        ):
            connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5)

        assert stub.members == ["Reload"]


class TestCall:
    """Method calls: replies are matched by serial, errors are raised, and every wait has a deadline."""

    def test_method_return_body_is_returned(self, socket_path: str) -> None:
        """Should return the parsed body of the matching method return."""
        with (
            _Stub(socket_path, _serve(_returns("as", (["A=1", "B=2"],)))),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
        ):
            body = connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5)

        assert body == (["A=1", "B=2"],)

    def test_error_reply_raises_with_name_and_message(self, socket_path: str) -> None:
        """Should raise DBusError carrying the D-Bus error name and the error message."""

        def fail(request: Message) -> list[bytes]:
            error = new_error(request, "org.freedesktop.systemd1.NoSuchUnit", "s", ("Unit foo not loaded.",))
            return [error.serialise(serial=1)]

        with (
            _Stub(socket_path, _serve(fail)),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
            raises(DBusError, match=r"org\.freedesktop\.systemd1\.NoSuchUnit.*Unit foo not loaded"),
        ):
            connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5)

    def test_error_reply_without_text_raises_with_the_name_only(self, socket_path: str) -> None:
        """Should raise DBusError with just the error name when the error carries no message text."""

        def fail(request: Message) -> list[bytes]:
            return [new_error(request, "org.freedesktop.DBus.Error.AccessDenied").serialise(serial=1)]

        with (
            _Stub(socket_path, _serve(fail)),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
            raises(DBusError, match=r"^org\.freedesktop\.DBus\.Error\.AccessDenied$"),
        ):
            connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5)

    def test_signal_before_the_reply_is_ignored(self, socket_path: str) -> None:
        """Should skip a signal that arrives before the reply and return the reply's body."""
        emitter = DBusAddress("/org/freedesktop/systemd1", interface="org.freedesktop.systemd1.Manager")

        def signal_then_reply(request: Message) -> list[bytes]:
            signal = new_signal(emitter, "UnitNew", "ss", ("a.service", "/x")).serialise(serial=1)
            return [signal, new_method_return(request, "as", (["ok"],)).serialise(serial=2)]

        with (
            _Stub(socket_path, _serve(signal_then_reply)),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
        ):
            assert connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5) == (["ok"],)

    def test_server_closing_before_the_reply_is_a_dbus_error(self, socket_path: str) -> None:
        """Should raise DBusError when the server closes the socket instead of replying."""

        def drop(stub: _Stub, conn: socket) -> None:
            if stub.handshake(conn):
                next(stub.requests(conn))

        with (
            _Stub(socket_path, drop),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
            raises(DBusError, match="closed"),
        ):
            connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5)

    def test_no_reply_before_the_deadline_is_a_dbus_error(self, socket_path: str) -> None:
        """Should raise DBusError with a timeout message when no reply arrives within the call's timeout."""
        with (
            _Stub(socket_path, _serve(lambda _request: [])),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
            raises(DBusError, match="timed out"),
        ):
            connection.call(new_method_call(PROPERTIES, "Reload"), timeout=0.2)

    def test_context_manager_closes_the_socket(self, socket_path: str) -> None:
        """Should refuse further calls once the with-block has closed the connection."""
        with (
            _Stub(socket_path, _serve(_returns("as", ([],)))),
            DBusConnection.connect(socket_path, hello=False, timeout=5) as connection,
        ):
            pass
        with raises(DBusError):
            connection.call(new_method_call(PROPERTIES, "Reload"), timeout=5)
