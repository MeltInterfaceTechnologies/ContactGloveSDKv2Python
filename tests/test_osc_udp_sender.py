import socket
import threading
import unittest
from unittest.mock import MagicMock, patch

from contactglovesdk import ContactGloveClient, Host, SDKNotAvailableError
from contactglovesdk._client import _OscUdpSender


class OscUdpSenderTests(unittest.TestCase):
    def test_reuses_one_socket_for_multiple_messages(self) -> None:
        fake_socket = MagicMock()
        fake_socket.getsockname.return_value = ("0.0.0.0", 46123)
        sender = _OscUdpSender()

        with patch("contactglovesdk._client.socket.socket", return_value=fake_socket) as factory:
            sender.send("127.0.0.1", 25791, "/first", [("i", 1)])
            sender.send("127.0.0.1", 25791, "/second", [("i", 2)])

        factory.assert_called_once_with(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )
        self.assertEqual(fake_socket.sendto.call_count, 2)
        self.assertEqual(sender.port, 46123)
        sender.close()
        fake_socket.close.assert_called_once()

    def test_retains_socket_after_send_failure(self) -> None:
        failed_socket = MagicMock()
        failed_socket.sendto.side_effect = [OSError("send failed"), None]
        failed_socket.getsockname.return_value = ("0.0.0.0", 46124)
        sender = _OscUdpSender()

        with patch(
            "contactglovesdk._client.socket.socket",
            return_value=failed_socket,
        ) as factory:
            sender.send("127.0.0.1", 25791, "/first", [])
            sender.send("127.0.0.1", 25791, "/second", [])

        factory.assert_called_once()
        self.assertEqual(failed_socket.sendto.call_count, 2)
        self.assertEqual(sender.port, 46124)
        sender.close()
        failed_socket.close.assert_called_once()

    def test_keeps_the_same_source_port(self) -> None:
        sender = _OscUdpSender()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(1)
            destination = receiver.getsockname()

            try:
                sender.send(destination[0], destination[1], "/first", [])
                _, first_source = receiver.recvfrom(65535)
                sender.send(destination[0], destination[1], "/second", [])
                _, second_source = receiver.recvfrom(65535)
            finally:
                sender.close()

        self.assertEqual(first_source, second_source)

    def test_client_binds_the_requested_send_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(1)
            destination = receiver.getsockname()

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserver:
                reserver.bind(("127.0.0.1", 0))
                requested_port = reserver.getsockname()[1]

            client = ContactGloveClient(send_port=requested_port)
            try:
                client._send_osc(destination[0], destination[1], "/test", [])
                _, source = receiver.recvfrom(65535)
                self.assertEqual(client.send_port, requested_port)
            finally:
                client.close()

        self.assertEqual(source[1], requested_port)
        self.assertEqual(client.send_port, None)

    def test_client_reports_an_unavailable_send_port(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blocker:
            blocker.bind(("0.0.0.0", 0))
            client = ContactGloveClient(send_port=blocker.getsockname()[1])
            try:
                with self.assertRaises(SDKNotAvailableError):
                    client._send_osc("127.0.0.1", 25791, "/test", [])
            finally:
                client.close()

    def test_connect_registers_host_before_sending(self) -> None:
        client = ContactGloveClient()
        host = Host("DivingStation", "127.0.0.1", 25791)
        client._ensure_server = MagicMock(return_value=49100)

        def assert_host_is_registered(*_args: object) -> None:
            # _send_osc は _conn_lock を保持したまま呼ばれる。
            self.assertIs(client._connected_hosts.get((host.ip_address, host.port)), host)

        client._send_osc = MagicMock(side_effect=assert_host_is_registered)
        try:
            client.connect_to_host(host)
        finally:
            client.close()

    def test_connect_rolls_back_host_on_send_port_bind_failure(self) -> None:
        client = ContactGloveClient()
        host = Host("DivingStation", "127.0.0.1", 25791)
        client._ensure_server = MagicMock(return_value=49100)
        client._send_osc = MagicMock(
            side_effect=SDKNotAvailableError("send port unavailable")
        )

        try:
            with self.assertRaises(SDKNotAvailableError):
                client.connect_to_host(host)
            with client._conn_lock:
                self.assertNotIn((host.ip_address, host.port), client._connected_hosts)
        finally:
            client.close()

    def test_concurrent_failed_connects_leave_no_host_registered(self) -> None:
        client = ContactGloveClient()
        hosts = [
            Host("DivingStation A", "127.0.0.1", 25791),
            Host("DivingStation B", "127.0.0.1", 25791),
        ]
        client._ensure_server = MagicMock(return_value=49100)
        client._send_osc = MagicMock(
            side_effect=SDKNotAvailableError("send port unavailable")
        )
        start = threading.Barrier(len(hosts) + 1)
        failures = []

        def connect(host: Host) -> None:
            start.wait()
            try:
                client.connect_to_host(host)
            except SDKNotAvailableError as exc:
                failures.append(exc)

        threads = [threading.Thread(target=connect, args=(host,)) for host in hosts]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()

        try:
            self.assertEqual(len(failures), len(hosts))
            with client._conn_lock:
                self.assertNotIn(("127.0.0.1", 25791), client._connected_hosts)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
