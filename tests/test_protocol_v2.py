import math
import pickle
import socket
import threading
import time
import unittest
import types
from enum import IntEnum
from unittest.mock import MagicMock, patch

from pythonosc.osc_message_builder import OscMessageBuilder

from contactglovesdk import (
    ContactGloveClient,
    ControllerData,
    DeviceConnectedState,
    DeviceColor,
    ErgonomicsData,
    GloveData,
    Host,
    RawSensorData,
    RawSkeletonData,
    SkeletonData,
    TrackingState,
)
from contactglovesdk._parsers import (
    parse_device_message,
    parse_controller_message,
    parse_ergonomics_message,
    parse_handskeleton_message,
    parse_rawsensor_message,
    parse_rawskeleton_message,
    parse_retarget_profile_info_message,
)


PROFILE_UUID = "12345678-1234-4abc-8def-1234567890ab"


def _skeleton_values():
    values = [0.0] * (25 * 3)
    for _ in range(19):
        values.extend((1.0, 0.0, 0.0, 0.0))
    return values


def _handskeleton_args():
    return [
        2,
        "CG3-LEFT-001",
        PROFILE_UUID,
        1,
        1,
        2,
        TrackingState.IkFailed,
        *_skeleton_values(),
    ]


def _rawskeleton_args():
    return [
        2,
        "CG3-LEFT-001",
        1,
        1,
        2,
        TrackingState.NotAttempted,
        *_skeleton_values(),
    ]


def _rawsensor_args():
    return [
        2,
        "CG3-LEFT-001",
        1,
        1,
        2,
        *([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0] * 5),
    ]


def _device_args(glove_id: str, connected_state: DeviceConnectedState):
    return [
        2,
        glove_id,
        "",
        50,
        1,
        1,
        3,
        4,
        connected_state,
        "ContactGlove3",
        0,
    ]


def _populate_all_stream_caches(client: ContactGloveClient, glove_id: str) -> None:
    with client._data_lock:
        client._gloves[glove_id] = GloveData(id=glove_id)
        client._controllers[glove_id] = ControllerData(id=glove_id)
        client._ergonomics[glove_id] = ErgonomicsData(id=glove_id)
        client._skeletons[glove_id] = SkeletonData(id=glove_id)
        client._rawskeletons[glove_id] = RawSkeletonData(id=glove_id)
        client._rawsensors[glove_id] = RawSensorData(id=glove_id)


def _assert_all_stream_caches_empty(test: unittest.TestCase, client: ContactGloveClient) -> None:
    with client._data_lock:
        for cache in (
            client._gloves,
            client._controllers,
            client._ergonomics,
            client._skeletons,
            client._rawskeletons,
            client._rawsensors,
        ):
            test.assertEqual(cache, {})


def _mark_client_connected(client: ContactGloveClient) -> Host:
    host = Host("DivingStation", "127.0.0.1", 25791)
    with client._conn_lock:
        client._connected_hosts[(host.ip_address, host.port)] = host
        client._enable_callbacks_locked()
    return host


class ProtocolV2ParserTests(unittest.TestCase):
    def test_color_pickle_supports_consumers_without_device_color(self) -> None:
        from contactglovesdk import _models

        payloads = [pickle.dumps(DeviceColor.Green), pickle.dumps(GloveData(color=DeviceColor.Green))]
        legacy = types.ModuleType(_models.__name__)
        legacy.__dict__.update(vars(_models))
        del legacy.DeviceColor
        legacy.LedColor = IntEnum("LedColor", {c.name: c.value for c in DeviceColor},
                                 module=_models.__name__)
        with patch.dict("sys.modules", {_models.__name__: legacy}):
            self.assertIs(pickle.loads(payloads[0]), legacy.LedColor.Green)
            self.assertIs(pickle.loads(payloads[1]).color, legacy.LedColor.Green)
            old_payload = pickle.dumps(legacy.LedColor.Green)
        self.assertIs(pickle.loads(old_payload), DeviceColor.Green)

    def test_old_color_import_remains_compatible(self) -> None:
        from contactglovesdk import LedColor
        from contactglovesdk._models import LedColor as ModelLedColor

        self.assertIs(LedColor, DeviceColor)
        self.assertIs(ModelLedColor, DeviceColor)
        self.assertIs(parse_device_message(tuple(_device_args(
            "CG3-LEFT-001", DeviceConnectedState.Connected)))[0].color, LedColor.Green)

    def test_device_uses_the_ten_field_v2_layout(self) -> None:
        parsed = parse_device_message(
            (
                2,
                "CG3-LEFT-001",
                "CG3-RIGHT-001",
                -1,
                1,
                1,
                3,
                4,
                1,
                "ContactGlove3 Left",
                1,
            )
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].battery_percentage, -1)
        self.assertTrue(parsed[0].is_external_power_present)

    def test_device_color_preserves_wire_values_and_public_type(self) -> None:
        self.assertIs(GloveData().color, DeviceColor.Achromatic)
        expected = ("Magenta", "Red", "Orange", "Yellow", "Green", "Cyan", "Blue", "Achromatic")
        for wire_value, name in enumerate(expected):
            with self.subTest(wire_value=wire_value):
                args = _device_args("CG3-LEFT-001", DeviceConnectedState.Connected)
                args[7] = wire_value
                parsed = parse_device_message(tuple(args))
                self.assertEqual(len(parsed), 1)
                self.assertIs(parsed[0].color, DeviceColor[name])
                self.assertEqual(int(parsed[0].color), wire_value)

    def test_ergonomics_uses_tracking_state_instead_of_profile_index(self) -> None:
        parsed = parse_ergonomics_message(
            (2, "CG3-LEFT-001", 1, 1, 2, TrackingState.IkFailed, *([0.0] * 20))
        )

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].timestamp_ms, (1 << 32) | 2)
        self.assertEqual(parsed[0].tracking_state, TrackingState.IkFailed)
        self.assertFalse(hasattr(parsed[0], "profile_index"))

    def test_skeleton_and_raw_skeleton_follow_v2_layouts(self) -> None:
        skeleton = parse_handskeleton_message(tuple(_handskeleton_args()))
        raw = parse_rawskeleton_message(tuple(_rawskeleton_args()))

        self.assertEqual(len(skeleton), 1)
        self.assertEqual(skeleton[0].profile_uuid, PROFILE_UUID)
        self.assertEqual(skeleton[0].tracking_state, TrackingState.IkFailed)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0].tracking_state, TrackingState.NotAttempted)

    def test_skeleton_rejects_invalid_uuid_and_quaternion(self) -> None:
        invalid_uuid = _handskeleton_args()
        invalid_uuid[2] = "not-a-uuid"
        self.assertEqual(parse_handskeleton_message(tuple(invalid_uuid)), [])

        invalid_quaternion = _handskeleton_args()
        invalid_quaternion[-4:] = [2.0, 0.0, 0.0, 0.0]
        self.assertEqual(parse_handskeleton_message(tuple(invalid_quaternion)), [])

    def test_skeleton_and_raw_skeleton_reject_trailing_arguments(self) -> None:
        self.assertEqual(
            parse_handskeleton_message(tuple(_handskeleton_args() + ["trailing"])), []
        )
        self.assertEqual(
            parse_rawskeleton_message(tuple(_rawskeleton_args() + ["trailing"])), []
        )

    def test_device_rejects_out_of_spec_v2_values(self) -> None:
        valid = [
            2,
            "CG3-LEFT-001",
            "CG3-RIGHT-001",
            -1,
            1,
            1,
            3,
            4,
            1,
            "ContactGlove3 Left",
            0,
        ]
        invalid_values = {
            3: (-2, 101),  # battery_percentage
            4: (2,),  # is_haptics
            5: (-1,),  # is_left
            6: (2, 99),  # device_type
            7: (8,),  # color
            8: (4,),  # connected_state
            10: (2,),  # is_external_power_present
        }

        for index, values in invalid_values.items():
            for value in values:
                with self.subTest(field=index, value=value):
                    args = valid.copy()
                    args[index] = value
                    self.assertEqual(parse_device_message(tuple(args)), [])

    def test_controller_validates_buttons_and_analog_ranges(self) -> None:
        valid = [
            2,
            "CG3-LEFT-001",
            1,
            0,
            1,
            2,
            0,
            1,
            2,
            1.0,
            0.5,
            0.0,
            -1.0,
            1.0,
            0.0,
            -1.0,
        ]
        self.assertEqual(len(parse_controller_message(tuple(valid))), 1)

        invalid_is_left = valid.copy()
        invalid_is_left[2] = 2
        self.assertEqual(parse_controller_message(tuple(invalid_is_left)), [])

        invalid_button = valid.copy()
        invalid_button[3] = 3
        self.assertEqual(parse_controller_message(tuple(invalid_button)), [])

        invalid_analog = valid.copy()
        invalid_analog[9] = 1.1
        self.assertEqual(parse_controller_message(tuple(invalid_analog)), [])

    def test_all_is_left_fields_require_zero_or_one(self) -> None:
        ergonomics = [
            2,
            "CG3-LEFT-001",
            2,
            1,
            2,
            TrackingState.IkFailed,
            *([0.0] * 20),
        ]
        skeleton = _handskeleton_args()
        skeleton[3] = 2
        raw_skeleton = _rawskeleton_args()
        raw_skeleton[2] = 2
        raw_sensor = _rawsensor_args()
        raw_sensor[2] = 2

        self.assertEqual(parse_ergonomics_message(tuple(ergonomics)), [])
        self.assertEqual(parse_handskeleton_message(tuple(skeleton)), [])
        self.assertEqual(parse_rawskeleton_message(tuple(raw_skeleton)), [])
        self.assertEqual(parse_rawsensor_message(tuple(raw_sensor)), [])

    def test_profile_response_validates_status_specific_fields(self) -> None:
        found = parse_retarget_profile_info_message(
            (2, 9, PROFILE_UUID, 0, "Default", "Standard profile")
        )
        missing = parse_retarget_profile_info_message((2, 10, PROFILE_UUID, 1, "", ""))
        rejected = parse_retarget_profile_info_message((2, 11, "", 2, "", ""))

        self.assertEqual(found[0].request_id, 9)
        self.assertEqual(missing[0].status, 1)
        self.assertEqual(rejected[0].status, 2)
        self.assertEqual(
            parse_retarget_profile_info_message((2, 12, PROFILE_UUID, 1, "name", "")),
            [],
        )


class ProtocolV2ClientTests(unittest.TestCase):
    def test_last_disconnect_waits_for_callback_dispatch(self) -> None:
        client = ContactGloveClient()
        host = _mark_client_connected(client)
        callback_started = threading.Event()
        allow_callback_to_finish = threading.Event()
        second_callback_called = threading.Event()
        disconnect_finished = threading.Event()

        def blocking_callback(_: GloveData) -> None:
            callback_started.set()
            allow_callback_to_finish.wait(1.0)

        client.register_callback_for_glove_data_stream(blocking_callback)
        client.register_callback_for_glove_data_stream(
            lambda _: second_callback_called.set()
        )
        receiver = threading.Thread(
            target=client._on_device,
            args=(
                "/DS2/HC/Device",
                *_device_args("CG3-CALLBACK", DeviceConnectedState.Connected),
            ),
        )
        disconnector = threading.Thread(
            target=lambda: (client.disconnect(host), disconnect_finished.set()),
        )

        try:
            receiver.start()
            self.assertTrue(callback_started.wait(1.0))
            disconnector.start()

            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                with client._callback_condition:
                    if not client._callbacks_enabled:
                        break
                time.sleep(0.01)
            else:
                self.fail("disconnect() did not disable callback dispatch")

            self.assertFalse(disconnect_finished.is_set())
            allow_callback_to_finish.set()
            disconnector.join(1.0)
            receiver.join(1.0)
            self.assertFalse(disconnector.is_alive())
            self.assertFalse(receiver.is_alive())
            self.assertTrue(disconnect_finished.is_set())
            self.assertFalse(second_callback_called.is_set())
        finally:
            allow_callback_to_finish.set()
            disconnector.join(1.0)
            receiver.join(1.0)
            client.close()

    def test_polling_and_each_callback_own_nested_snapshots(self) -> None:
        glove_id = "CG3-LEFT-001"
        streams = (
            ("glove", "_on_device", "register_callback_for_glove_data_stream",
             "get_data_for_glove", parse_device_message,
             _device_args(glove_id, DeviceConnectedState.Connected)),
            ("controller", "_on_controller", "register_callback_for_controller_data_stream",
             "get_controller_data_for_glove", parse_controller_message,
             [2, glove_id, 1, 0, 0, 0, 0, 0, 0, *([0.0] * 7)]),
            ("ergonomics", "_on_ergonomics", "register_callback_for_ergonomics_stream",
             "get_ergonomics_data_for_glove", parse_ergonomics_message,
             [2, glove_id, 1, 1, 2, 0, *[float(i) for i in range(20)]]),
            ("skeleton", "_on_handskeleton", "register_callback_for_skeleton_stream",
             "get_skeleton_data_for_glove", parse_handskeleton_message, _handskeleton_args()),
            ("raw_skeleton", "_on_rawskeleton", "register_callback_for_raw_skeleton_stream",
             "get_raw_skeleton_data_for_glove", parse_rawskeleton_message, _rawskeleton_args()),
            ("raw_sensor", "_on_rawsensor", "register_callback_for_rawsensor_stream",
             "get_rawsensor_data_for_glove", parse_rawsensor_message, _rawsensor_args()),
        )

        def mutate(value):
            value.id = "consumer-mutated"
            for field in ("battery_percentage", "trigger"):
                if hasattr(value, field):
                    setattr(value, field, 99)
            if hasattr(value, "values"):
                value.values[0] = 99.0
            if hasattr(value, "positions"):
                value.positions[0].x = 99.0
                value.rotations[0].w = 0.5
            if hasattr(value, "transforms"):
                value.transforms[0].position.x = 99.0
                value.transforms[0].rotation.w = 0.5

        for name, handler, register, getter, parser, args in streams:
            with self.subTest(stream=name):
                client = ContactGloveClient()
                self.addCleanup(client.close)
                _mark_client_connected(client)
                expected = parser(tuple(args))[0]
                observed = []
                getattr(client, register)(mutate)
                getattr(client, register)(observed.append)
                getattr(client, handler)("unused-address", *args)
                self.assertEqual(observed, [expected])
                snapshot = getattr(client, getter)(glove_id)
                self.assertEqual(snapshot, expected)
                mutate(snapshot)
                self.assertEqual(getattr(client, getter)(glove_id), expected)
                self.assertEqual(observed, [expected])
                mutate(observed[0])
                self.assertEqual(getattr(client, getter)(glove_id), expected)
                # A retained snapshot remains independent of later frames too.
                retained = getattr(client, getter)(glove_id)
                getattr(client, handler)("unused-address", *args)
                self.assertEqual(retained, expected)
                self.assertEqual(observed[1], expected)

    def test_profile_callbacks_receive_independent_snapshots(self) -> None:
        client = ContactGloveClient()
        self.addCleanup(client.close)
        _mark_client_connected(client)
        args = (2, 42, PROFILE_UUID, 0, "profile", "description")
        expected = parse_retarget_profile_info_message(args)[0]
        seen = []

        def mutate(info):
            info.name = "consumer-mutated"

        client.register_callback_for_retarget_profile_info_stream(mutate)
        client.register_callback_for_retarget_profile_info_stream(seen.append)
        client._on_retarget_profile_info("unused-address", *args)
        self.assertEqual(seen, [expected])

    def test_callback_exception_is_logged_without_skipping_other_callbacks(self) -> None:
        client = ContactGloveClient()
        self.addCleanup(client.close)
        _mark_client_connected(client)
        received = []

        def failing_callback(_: GloveData) -> None:
            raise ValueError("callback failure")

        client.register_callback_for_glove_data_stream(failing_callback)
        client.register_callback_for_glove_data_stream(
            lambda glove: received.append(glove.id)
        )

        with self.assertLogs("contactglovesdk", level="ERROR") as logs:
            client._on_device(
                "/DS2/HC/Device",
                *_device_args("CG3-CALLBACK", DeviceConnectedState.Connected),
            )

        self.assertEqual(received, ["CG3-CALLBACK"])
        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        self.assertIn("failing_callback", record.getMessage())
        self.assertIn("GloveData", record.getMessage())
        self.assertIsInstance(record.exc_info[1], ValueError)

    def test_reconnect_does_not_resume_old_callbacks_or_block_old_disconnect(self) -> None:
        client = ContactGloveClient()
        host = _mark_client_connected(client)
        client._actual_local_port = 49100
        client._ensure_server = MagicMock(return_value=49100)
        old_callback_started = threading.Event()
        allow_old_callback_to_finish = threading.Event()
        new_callback_started = threading.Event()
        allow_new_callback_to_finish = threading.Event()
        stale_callback_called = threading.Event()
        disconnect_sent = threading.Event()
        disconnect_finished = threading.Event()

        def first_callback(glove: GloveData) -> None:
            if glove.id == "CG3-OLD-CALLBACK":
                old_callback_started.set()
                allow_old_callback_to_finish.wait(1.0)
            elif glove.id == "CG3-NEW-CALLBACK":
                new_callback_started.set()
                allow_new_callback_to_finish.wait(1.0)

        def second_callback(glove: GloveData) -> None:
            if glove.id == "CG3-OLD-CALLBACK":
                stale_callback_called.set()

        def record_send(
            _ip: str, _port: int, address: str, _args: list
        ) -> None:
            if address == "/DS2/HC/Disconnect":
                disconnect_sent.set()

        client._send_osc = MagicMock(side_effect=record_send)
        client.register_callback_for_glove_data_stream(first_callback)
        client.register_callback_for_glove_data_stream(second_callback)
        old_receiver = threading.Thread(
            target=client._on_device,
            args=(
                "/DS2/HC/Device",
                *_device_args("CG3-OLD-CALLBACK", DeviceConnectedState.Connected),
            ),
        )
        disconnector = threading.Thread(
            target=lambda: (client.disconnect(host), disconnect_finished.set()),
        )
        new_receiver = threading.Thread(
            target=client._on_device,
            args=(
                "/DS2/HC/Device",
                *_device_args("CG3-NEW-CALLBACK", DeviceConnectedState.Connected),
            ),
        )

        try:
            old_receiver.start()
            self.assertTrue(old_callback_started.wait(1.0))
            disconnector.start()
            self.assertTrue(disconnect_sent.wait(1.0))
            self.assertFalse(disconnect_finished.is_set())

            client.connect_to_host(host)
            self.assertEqual(
                [call.args[2] for call in client._send_osc.call_args_list],
                ["/DS2/HC/Disconnect", "/DS2/HC/Connect"],
            )

            new_receiver.start()
            self.assertTrue(new_callback_started.wait(1.0))
            allow_old_callback_to_finish.set()

            self.assertTrue(disconnect_finished.wait(1.0))
            self.assertTrue(new_receiver.is_alive())
            self.assertFalse(stale_callback_called.is_set())
            disconnector.join(1.0)
            old_receiver.join(1.0)
            self.assertFalse(disconnector.is_alive())
            self.assertFalse(old_receiver.is_alive())
            self.assertTrue(disconnect_finished.is_set())

            allow_new_callback_to_finish.set()
            new_receiver.join(1.0)
            self.assertFalse(new_receiver.is_alive())
        finally:
            allow_old_callback_to_finish.set()
            allow_new_callback_to_finish.set()
            disconnector.join(1.0)
            old_receiver.join(1.0)
            new_receiver.join(1.0)
            client.close()

    def test_callback_can_disconnect_its_own_last_connection(self) -> None:
        client = ContactGloveClient()
        host = _mark_client_connected(client)
        callback_finished = threading.Event()

        def disconnect_from_callback(_: GloveData) -> None:
            client.disconnect(host)
            callback_finished.set()

        client.register_callback_for_glove_data_stream(disconnect_from_callback)
        receiver = threading.Thread(
            target=client._on_device,
            args=(
                "/DS2/HC/Device",
                *_device_args("CG3-SELF-DISCONNECT", DeviceConnectedState.Connected),
            ),
        )
        try:
            receiver.start()
            receiver.join(1.0)
            self.assertFalse(receiver.is_alive())
            self.assertTrue(callback_finished.is_set())
        finally:
            client.close()

    def test_close_waits_for_callback_dispatch(self) -> None:
        client = ContactGloveClient()
        _mark_client_connected(client)
        callback_started = threading.Event()
        allow_callback_to_finish = threading.Event()
        close_finished = threading.Event()

        def blocking_callback(_: GloveData) -> None:
            callback_started.set()
            allow_callback_to_finish.wait(1.0)

        client.register_callback_for_glove_data_stream(blocking_callback)
        receiver = threading.Thread(
            target=client._on_device,
            args=(
                "/DS2/HC/Device",
                *_device_args("CG3-CLOSE-CALLBACK", DeviceConnectedState.Connected),
            ),
        )
        closer = threading.Thread(target=lambda: (client.close(), close_finished.set()))

        try:
            receiver.start()
            self.assertTrue(callback_started.wait(1.0))
            closer.start()

            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                with client._callback_condition:
                    if not client._callbacks_enabled:
                        break
                time.sleep(0.01)
            else:
                self.fail("close() did not disable callback dispatch")

            self.assertFalse(close_finished.is_set())
            allow_callback_to_finish.set()
            closer.join(1.0)
            receiver.join(1.0)
            self.assertFalse(closer.is_alive())
            self.assertFalse(receiver.is_alive())
            self.assertTrue(close_finished.is_set())
        finally:
            allow_callback_to_finish.set()
            closer.join(1.0)
            receiver.join(1.0)
            client.close()

    def test_close_stops_local_listener_before_waiting_for_callback(self) -> None:
        client = ContactGloveClient()
        _mark_client_connected(client)
        client._actual_local_port = 49100
        server = MagicMock()
        client._server = server
        callback_started = threading.Event()
        listener_stopped = threading.Event()

        def wait_for_local_listener_to_stop(_: GloveData) -> None:
            callback_started.set()
            while client.local_port is not None:
                time.sleep(0.01)
            listener_stopped.set()

        client.register_callback_for_glove_data_stream(wait_for_local_listener_to_stop)
        receiver = threading.Thread(
            target=client._on_device,
            args=(
                "/DS2/HC/Device",
                *_device_args("CG3-CLOSE-LISTENER", DeviceConnectedState.Connected),
            ),
        )
        closer = threading.Thread(target=client.close)

        try:
            receiver.start()
            self.assertTrue(callback_started.wait(1.0))
            closer.start()

            self.assertTrue(listener_stopped.wait(1.0))
            closer.join(1.0)
            receiver.join(1.0)
            self.assertFalse(closer.is_alive())
            self.assertFalse(receiver.is_alive())
            server.shutdown.assert_called_once()
            server.server_close.assert_called_once()
        finally:
            # 旧実装でもテスト失敗後に受信スレッドを終了できるようにする。
            client._actual_local_port = None
            closer.join(1.0)
            receiver.join(1.0)
            client.close()

    def test_callback_can_close_real_server_without_joining_itself(self) -> None:
        client = ContactGloveClient(local_host="127.0.0.1")
        local_port = client.start_server()
        _mark_client_connected(client)
        callback_finished = threading.Event()
        callback_close_errors = []

        def close_from_callback(_: GloveData) -> None:
            try:
                client.close()
            except Exception as exc:
                callback_close_errors.append(exc)
            finally:
                callback_finished.set()

        client.register_callback_for_glove_data_stream(close_from_callback)
        with client._server_lock:
            self.assertTrue(client._server.daemon_threads)  # type: ignore[union-attr]
            self.assertFalse(client._server.block_on_close)  # type: ignore[union-attr]

        message = OscMessageBuilder(address="/DS2/HC/Device")
        for argument in _device_args(
            "CG3-CALLBACK-CLOSE", DeviceConnectedState.Connected
        ):
            value = (
                int(argument)
                if isinstance(argument, DeviceConnectedState)
                else argument
            )
            message.add_arg(value)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(message.build().dgram, ("127.0.0.1", local_port))

        try:
            self.assertTrue(callback_finished.wait(2.0))
            self.assertEqual(callback_close_errors, [])
            self.assertIsNone(client.local_port)
        finally:
            client.close()

    def test_unconnected_device_evicts_all_stream_caches_and_frees_a_slot(self) -> None:
        client = ContactGloveClient()
        glove_updates = []
        client.register_callback_for_glove_data_stream(glove_updates.append)
        _mark_client_connected(client)
        disconnected_id = "CG3-DISCONNECTED"
        _populate_all_stream_caches(client, disconnected_id)
        with client._data_lock:
            for index in range(15):
                glove_id = f"CG3-ACTIVE-{index}"
                client._gloves[glove_id] = GloveData(id=glove_id)

        try:
            client._on_device(
                "/DS2/HC/Device",
                *_device_args(disconnected_id, DeviceConnectedState.Unconnected),
            )

            with client._data_lock:
                for cache in (
                    client._gloves,
                    client._controllers,
                    client._ergonomics,
                    client._skeletons,
                    client._rawskeletons,
                    client._rawsensors,
                ):
                    self.assertNotIn(disconnected_id, cache)
                self.assertEqual(len(client._gloves), 15)

            self.assertEqual(len(glove_updates), 1)
            self.assertEqual(
                glove_updates[0].connected_state, DeviceConnectedState.Unconnected
            )

            new_id = "CG3-NEW"
            client._on_device(
                "/DS2/HC/Device",
                *_device_args(new_id, DeviceConnectedState.Connected),
            )
            with client._data_lock:
                self.assertIn(new_id, client._gloves)
                self.assertEqual(len(client._gloves), 16)
        finally:
            client.close()

    def test_last_disconnect_and_close_clear_all_stream_caches(self) -> None:
        client = ContactGloveClient()
        first_host = Host("First", "127.0.0.1", 25791)
        second_host = Host("Second", "127.0.0.2", 25791)
        with client._conn_lock:
            client._connected_hosts[(first_host.ip_address, first_host.port)] = first_host
            client._connected_hosts[(second_host.ip_address, second_host.port)] = second_host
        _populate_all_stream_caches(client, "CG3-CACHED")

        try:
            client.disconnect(first_host)
            with client._data_lock:
                self.assertIn("CG3-CACHED", client._gloves)

            client.disconnect(second_host)
            _assert_all_stream_caches_empty(self, client)

            client._on_device(
                "/DS2/HC/Device",
                *_device_args("CG3-DELAYED", DeviceConnectedState.Connected),
            )
            _assert_all_stream_caches_empty(self, client)

            _populate_all_stream_caches(client, "CG3-CACHED-AFTER-RECONNECT")
            client.close()
            _assert_all_stream_caches_empty(self, client)
        finally:
            client.close()

    def test_device_records_are_processed_in_wire_order(self) -> None:
        client = ContactGloveClient()
        _mark_client_connected(client)
        glove_id = "CG3-ORDERED"
        try:
            client._on_device(
                "/DS2/HC/Device",
                2,
                *_device_args(glove_id, DeviceConnectedState.Connected)[1:],
                *_device_args(glove_id, DeviceConnectedState.Unconnected)[1:],
            )
            with client._data_lock:
                self.assertNotIn(glove_id, client._gloves)

            client._on_device(
                "/DS2/HC/Device",
                2,
                *_device_args(glove_id, DeviceConnectedState.Unconnected)[1:],
                *_device_args(glove_id, DeviceConnectedState.Connected)[1:],
            )
            with client._data_lock:
                self.assertEqual(
                    client._gloves[glove_id].connected_state,
                    DeviceConnectedState.Connected,
                )
        finally:
            client.close()

    def test_vibrate_glove_validates_protocol_ranges(self) -> None:
        client = ContactGloveClient()
        host = Host("DivingStation", "127.0.0.1", 25791)
        client._send_osc = MagicMock()
        with client._data_lock:
            client._gloves["CG3-LEFT-001"] = GloveData(id="CG3-LEFT-001")
        with client._conn_lock:
            client._connected_hosts[(host.ip_address, host.port)] = host

        try:
            for values in (
                (99.9, 0.5, 0.5),
                (500.1, 0.5, 0.5),
                (100.0, -0.1, 0.5),
                (100.0, 1.1, 0.5),
                (100.0, 0.5, 0.0009),
                (100.0, 0.5, 1.1),
                (math.nan, 0.5, 0.5),
            ):
                with self.subTest(values=values):
                    with self.assertRaises(ValueError):
                        client.vibrate_glove("CG3-LEFT-001", *values)

            client.vibrate_glove("CG3-LEFT-001", 100, 1, 0.001)
            self.assertEqual(
                client._send_osc.call_args.args,
                (
                    "127.0.0.1",
                    25791,
                    "/DS2/HC/CG3-LEFT-001/Haptics/Body",
                    [("i", 2), ("f", 100.0), ("f", 1.0), ("f", 0.001)],
                ),
            )
        finally:
            client.close()

    def test_raw_skeleton_and_profile_response_are_exposed_by_client(self) -> None:
        client = ContactGloveClient()
        raw_updates = []
        profile_updates = []
        client.register_callback_for_raw_skeleton_stream(raw_updates.append)
        client.register_callback_for_retarget_profile_info_stream(profile_updates.append)
        _mark_client_connected(client)

        try:
            client._on_rawskeleton("/DS2/HC/HandSkeletonRaw", *_rawskeleton_args())
            client._on_retarget_profile_info(
                "/DS2/HC/HandSkeleton/Profile",
                2,
                1,
                PROFILE_UUID,
                0,
                "Default",
                "Standard profile",
            )

            raw = client.get_raw_skeleton_data_for_glove("CG3-LEFT-001")
            self.assertEqual(raw.id, "CG3-LEFT-001")
            self.assertEqual(raw.tracking_state, TrackingState.NotAttempted)
            self.assertEqual(len(raw_updates), 1)
            self.assertEqual(profile_updates[0].profile_uuid, PROFILE_UUID)
        finally:
            client.close()

    def test_profile_request_and_keepalive_use_the_persistent_connection(self) -> None:
        client = ContactGloveClient()
        host = Host("DivingStation", "127.0.0.1", 25791)
        client._ensure_server = MagicMock(return_value=49100)
        client._actual_local_port = 49100
        client._send_osc = MagicMock()

        try:
            with patch("contactglovesdk._client._KEEPALIVE_INTERVAL_SECONDS", 0.01):
                client.connect_to_host(host)
                deadline = time.monotonic() + 1.0
                while client._send_osc.call_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.01)

                self.assertGreaterEqual(client._send_osc.call_count, 2)
                self.assertEqual(
                    client._send_osc.call_args_list[0].args,
                    ("127.0.0.1", 25791, "/DS2/HC/Connect", [("i", 49100)]),
                )

                client.request_retarget_profile_info(PROFILE_UUID, -7)
                self.assertEqual(
                    client._send_osc.call_args.args,
                    (
                        "127.0.0.1",
                        25791,
                        "/DS2/HC/HandSkeleton/Profile/Get",
                        [("i", 2), ("i", -7), ("s", PROFILE_UUID)],
                    ),
                )
                with self.assertRaises(ValueError):
                    client.request_retarget_profile_info("invalid", 1)

                client.disconnect(host)
                after_disconnect = client._send_osc.call_count
                time.sleep(0.04)
                self.assertEqual(client._send_osc.call_count, after_disconnect)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
