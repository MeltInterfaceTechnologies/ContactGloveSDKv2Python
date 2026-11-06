"""Exercise Connect retries against a loopback OSC peer, without DivingStation."""

import socket
import threading
import time
import unittest
from unittest.mock import patch

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from contactglovesdk import ContactGloveClient, Host


CONNECT = "/DS2/HC/Connect"
DISCONNECT = "/DS2/HC/Disconnect"


class ConnectionRetryTests(unittest.TestCase):
    def _receiver(self, port: int = 0) -> socket.socket:
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(receiver.close)
        receiver.bind(("127.0.0.1", port))
        receiver.settimeout(2.0)
        return receiver

    def _client(self, fixed_port: bool) -> ContactGloveClient:
        send_port = 0
        if fixed_port:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserver:
                reserver.bind(("127.0.0.1", 0))
                send_port = reserver.getsockname()[1]
        client = ContactGloveClient(local_host="127.0.0.1", send_port=send_port)
        self.addCleanup(client.close)
        return client

    def _receive_connect(self, receiver, client, expected_source=None):
        packet, source = receiver.recvfrom(65535)
        message = OscMessage(packet)
        self.assertEqual(message.address, CONNECT)
        self.assertEqual(message.params, [client.local_port])
        self.assertEqual(source[1], client.send_port)
        if expected_source is not None:
            self.assertEqual(source, expected_source)
        return source

    def _send_device(self, receiver, client, glove_id):
        builder = OscMessageBuilder(address="/DS2/HC/Device")
        for value in [2, glove_id, "", 50, 1, 1, 3, 4, 1, "ContactGlove3", 0]:
            builder.add_arg(value)
        receiver.sendto(builder.build().dgram, ("127.0.0.1", client.local_port))

    def _disconnect(self, receiver, client, host, expected_source):
        client.disconnect(host)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            packet, source = receiver.recvfrom(65535)
            message = OscMessage(packet)
            self.assertEqual(source, expected_source)
            self.assertEqual(message.params, [client.local_port])
            if message.address == DISCONNECT:
                break
            self.assertEqual(message.address, CONNECT)
        else:
            self.fail("Explicit disconnect did not send Disconnect")
        receiver.settimeout(0.15)
        with self.assertRaises(socket.timeout):
            receiver.recvfrom(65535)

    def test_manual_retries_preserve_endpoint_until_delayed_approval(self):
        for fixed_port in (False, True):
            with self.subTest(fixed_port=fixed_port):
                receiver = self._receiver()
                client = self._client(fixed_port)
                host = Host("DivingStation", "127.0.0.1", receiver.getsockname()[1])
                received = threading.Event()
                client.register_callback_for_glove_data_stream(lambda _g: received.set())
                client.connect_to_host(host)
                source = self._receive_connect(receiver, client)
                send_socket = client._osc_sender._socket
                receive_server = client._server
                key = (host.ip_address, host.port)
                worker = client._keepalive_workers[key]
                callback_generation = client._callback_generation

                # Withhold data across five retries, as when LAN approval is pending.
                for _ in range(5):
                    client.connect_to_host(Host("Renamed DS", host.ip_address, host.port))
                    self._receive_connect(receiver, client, source)
                    self.assertFalse(received.is_set())
                    self.assertIs(client._osc_sender._socket, send_socket)
                    self.assertIs(client._server, receive_server)
                    self.assertIs(client._keepalive_workers[key], worker)
                    self.assertIs(client._connected_hosts[key], host)
                    self.assertEqual(client._callback_generation, callback_generation)

                self._send_device(receiver, client, "CG3-APPROVED")
                self.assertTrue(received.wait(2.0), "No data after simulated approval")
                glove = client.get_data_for_glove("CG3-APPROVED")
                client.connect_to_host(host)
                self._receive_connect(receiver, client, source)
                snapshot = client.get_data_for_glove("CG3-APPROVED")
                self.assertEqual(snapshot, glove)
                self.assertIsNot(snapshot, glove)
                self._disconnect(receiver, client, host, source)
                client.close()
                receiver.close()

    def test_automatic_retries_survive_peer_restart(self):
        for fixed_port in (False, True):
            with self.subTest(fixed_port=fixed_port):
                receiver = self._receiver()
                ds_port = receiver.getsockname()[1]
                client = self._client(fixed_port)
                host = Host("DivingStation", "127.0.0.1", ds_port)
                received = threading.Event()
                client.register_callback_for_glove_data_stream(lambda _g: received.set())
                # Shorten only the interval; use the real worker and UDP sockets.
                with patch("contactglovesdk._client._KEEPALIVE_INTERVAL_SECONDS", 0.05):
                    client.connect_to_host(host)
                    source = self._receive_connect(receiver, client)
                    for _ in range(5):
                        self._receive_connect(receiver, client, source)
                        self.assertFalse(received.is_set())
                    self._send_device(receiver, client, "CG3-BEFORE-RESTART")
                    self.assertTrue(received.wait(2.0))

                    receiver.close()
                    received.clear()
                    time.sleep(0.15)  # Let retries run while the DS endpoint is absent.
                    receiver = self._receiver(ds_port)
                    self._receive_connect(receiver, client, source)
                    self._send_device(receiver, client, "CG3-AFTER-RESTART")
                    self.assertTrue(received.wait(2.0), "No data after peer restart")
                    self.assertEqual(
                        client.get_data_for_glove("CG3-AFTER-RESTART").id,
                        "CG3-AFTER-RESTART",
                    )
                    self._disconnect(receiver, client, host, source)
                    client.close()
                receiver.close()

    def test_failed_retry_keeps_session_and_automatic_retries_running(self):
        receiver = self._receiver()
        client = self._client(False)
        host = Host("DivingStation", "127.0.0.1", receiver.getsockname()[1])
        with patch("contactglovesdk._client._KEEPALIVE_INTERVAL_SECONDS", 0.05):
            client.connect_to_host(host)
            source = self._receive_connect(receiver, client)
            key = (host.ip_address, host.port)
            worker = client._keepalive_workers[key]
            original_send = client._send_osc
            retried = threading.Event()
            manual_thread = threading.current_thread()
            failed_threads = set()

            def fail_once_then_send(*args):
                current_thread = threading.current_thread()
                if current_thread not in failed_threads:
                    failed_threads.add(current_thread)
                    raise OSError("send failed")
                original_send(*args)
                if current_thread is not manual_thread:
                    retried.set()

            # Fail the manual retry and one keepalive; the same worker must recover.
            with patch.object(client, "_send_osc", side_effect=fail_once_then_send):
                with self.assertRaises(OSError):
                    client.connect_to_host(host)
                self.assertIs(client._connected_hosts[key], host)
                self.assertIs(client._keepalive_workers[key], worker)
                self.assertTrue(retried.wait(2.0))
                self._receive_connect(receiver, client, source)
                self.assertIs(client._keepalive_workers[key], worker)
                self._disconnect(receiver, client, host, source)


if __name__ == "__main__":
    unittest.main()
