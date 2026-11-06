from __future__ import annotations

import atexit
from copy import deepcopy
import logging
import math
import socket
import threading
from typing import Callable, Dict, List, Optional, Tuple

from pythonosc import dispatcher
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_server import ThreadingOSCUDPServer

from ._exceptions import InvalidIDError, NotConnectedError, SDKNotAvailableError
from ._models import (
    ControllerData,
    DeviceConnectedState,
    ErgonomicsData,
    GloveData,
    Host,
    RawSensorData,
    RawSkeletonData,
    RetargetProfileInfo,
    SkeletonData,
)
from ._parsers import (
    _is_valid_profile_uuid,
    parse_controller_message,
    parse_device_message,
    parse_ergonomics_message,
    parse_handskeleton_message,
    parse_rawskeleton_message,
    parse_rawsensor_message,
    parse_retarget_profile_info_message,
)

_logger = logging.getLogger("contactglovesdk")
_PROTOCOL_VERSION = 2
_HostKey = Tuple[str, int]  # (ip_address, ds_port)
_KEEPALIVE_INTERVAL_SECONDS = 30.0
_MAX_CACHED_DEVICES = 16


class ContactGloveClient:
    """Main class of ContactGlove Python SDK V2

    Polling results and each stream callback receive independent snapshots,
    including nested lists and geometry values. Modifying one does not change
    the SDK cache or values delivered to other callbacks.

    Usage:

    ```python
    import time

    from contactglovesdk import ContactGloveClient, Host, InvalidIDError

    host = Host("localhost", "127.0.0.1", 25791)
    with ContactGloveClient() as client:
        # Register before connecting so the first update is not missed.
        client.register_callback_for_glove_data_stream(
            lambda g: print(g.id, g.battery_percentage)
        )
        client.connect_to_host(host)
        try:
            # Poll until an ID arrives or the five-second deadline expires.
            deadline = time.monotonic() + 5.0
            glove_ids = client.get_ids_of_available_gloves()
            while not glove_ids and time.monotonic() < deadline:
                time.sleep(0.1)
                glove_ids = client.get_ids_of_available_gloves()

            if glove_ids:
                try:
                    glove = client.get_data_for_glove(glove_ids[0])
                    print(glove.id)
                except InvalidIDError:
                    print("The glove is no longer available")
            else:
                print("No glove data received within 5 seconds")
        finally:
            client.disconnect(host)
    ```

    Args:
        local_host: Network interface the local OSC server binds to (`"0.0.0.0"` for every interface).
        local_port: Port number the local OSC server binds to (`0` lets the OS pick a free port automatically).
        send_port: Local UDP port number used to send OSC to DS (`0` lets the OS pick a free port automatically).
    """

    DEFAULT_DS_PORT: int = 25791
    """Default OSC receive port number on the DivingStation side"""

    def __init__(
        self,
        local_host: str = "0.0.0.0",
        local_port: int = 0,
        send_port: int = 0,
    ) -> None:
        self._local_host = local_host
        self._local_port_hint = local_port
        self._osc_sender = _OscUdpSender(send_port)

        self._server: Optional[ThreadingOSCUDPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._actual_local_port: Optional[int] = None
        self._server_lock = threading.Lock()

        self._connected_hosts: Dict[_HostKey, Host] = {}
        self._conn_lock = threading.Lock()
        self._keepalive_workers: Dict[
            _HostKey, Tuple[threading.Event, threading.Thread]
        ] = {}
        self._callback_condition = threading.Condition()
        self._callbacks_enabled = False
        self._callback_generation = 0
        self._active_callback_dispatches: Dict[int, int] = {}
        self._callback_dispatch_state = threading.local()

        self._gloves: Dict[str, GloveData] = {}
        self._controllers: Dict[str, ControllerData] = {}
        self._ergonomics: Dict[str, ErgonomicsData] = {}
        self._skeletons: Dict[str, SkeletonData] = {}
        self._rawskeletons: Dict[str, RawSkeletonData] = {}
        self._rawsensors: Dict[str, RawSensorData] = {}

        self._glove_cbs: List[Callable[[GloveData], None]] = []
        self._controller_cbs: List[Callable[[ControllerData], None]] = []
        self._ergonomics_cbs: List[Callable[[ErgonomicsData], None]] = []
        self._skeleton_cbs: List[Callable[[SkeletonData], None]] = []
        self._rawskeleton_cbs: List[Callable[[RawSkeletonData], None]] = []
        self._rawsensor_cbs: List[Callable[[RawSensorData], None]] = []
        self._retarget_profile_info_cbs: List[Callable[[RetargetProfileInfo], None]] = []

        self._data_lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Local server management
    # -------------------------------------------------------------------------

    def _ensure_server(self) -> int:
        """Start the local OSC server if it is not running yet.

        Returns:
            The port number that was actually bound.
        Raises:
            SDKNotAvailableError: If binding the port failed.
        """
        with self._server_lock:
            if self._server is not None:
                return self._actual_local_port  # type: ignore[return-value]

            disp = dispatcher.Dispatcher()
            disp.map("/DS2/HC/Device", self._on_device)
            disp.map("/DS2/HC/Controller", self._on_controller)
            disp.map("/DS2/HC/HandSkeleton", self._on_handskeleton)
            disp.map("/DS2/HC/HandSkeletonRaw", self._on_rawskeleton)
            disp.map("/DS2/HC/HandSkeleton/Profile", self._on_retarget_profile_info)
            disp.map("/DS2/HC/Ergonomics", self._on_ergonomics)
            disp.map("/DS2/HC/RawSensorTransforms", self._on_rawsensor)

            try:
                self._server = ThreadingOSCUDPServer(
                    (self._local_host, self._local_port_hint), disp
                )
            except OSError as exc:
                raise SDKNotAvailableError(
                    f"Failed to bind local UDP socket on port "
                    f"{self._local_port_hint}: {exc}"
                ) from exc

            # Keep ``server_close`` from joining the current handler thread
            # even when ``close`` is called from a callback.
            self._server.daemon_threads = True
            self._server.block_on_close = False
            self._actual_local_port = self._server.server_address[1]
            self._server_thread = threading.Thread(
                target=self._server.serve_forever, daemon=True
            )
            self._server_thread.start()

        return self._actual_local_port  # type: ignore[return-value]

    def start_server(self) -> int:
        """Start the local OSC server without connecting to any host.

        Use this when the local port number is needed before calling
        `connect_to_host`.

        Returns:
            The port number the server actually bound to.
        Raises:
            SDKNotAvailableError: If binding the port failed.
        """
        return self._ensure_server()

    @property
    def local_port(self) -> Optional[int]:
        """Port number used by the local OSC server. `None` while it is not running."""
        return self._actual_local_port

    @property
    def send_port(self) -> Optional[int]:
        """Port number used by the OSC send socket. `None` before the first send."""
        return self._osc_sender.port

    def close(self) -> None:
        """Stop the local OSC server and the send socket.

        If any stream callback is still running, this waits for it to finish
        before returning.
        """
        with self._conn_lock:
            self._connected_hosts.clear()
            callback_generation = self._disable_callbacks_locked()
            with self._data_lock:
                self._clear_stream_caches_locked()
            keepalive_threads = self._stop_all_keepalives_locked()
        _join_keepalive_threads(keepalive_threads)

        with self._server_lock:
            server = self._server
            self._server = None
            self._server_thread = None
            # Announce the shutdown before waiting, so that a callback waiting
            # for local receiving to stop also observes it.
            self._actual_local_port = None
            if server is not None:
                server.shutdown()
                server.server_close()
        self._osc_sender.close()
        self._wait_for_callback_dispatches(callback_generation)

    # -------------------------------------------------------------------------
    # Connection management
    # -------------------------------------------------------------------------

    def connect_to_host(self, host: Host) -> None:
        """Connect to DivingStation and start the data streams.

        Starts the local OSC server if it is not running yet, then sends
        `/DS2/HC/Connect <local_port>` to `host`. While the connection is kept
        alive, Connect is re-sent every 30 seconds from the same send socket.

        Calling again for the same IP address and DS port resends Connect
        without sending Disconnect or replacing the send socket, receive port,
        or keepalive worker. Use this to retry while awaiting LAN approval or
        recovering from lost data. The OS-selected source port is retained even
        when `send_port` is `0`. Returning does not confirm LAN approval.
        After DS restarts, Connect retries can restore the session; approve it
        again in DS if required. Explicit `disconnect` ends the session and can
        revoke pending or granted approval.

        Args:
            host: Host information of the DS to connect to.
        Raises:
            SDKNotAvailableError: If binding the local receive or send port failed.
        """
        local_port = self._ensure_server()
        key: _HostKey = (host.ip_address, host.port)
        with self._conn_lock:
            if key in self._connected_hosts:
                # Retry registration without changing the pending/approved
                # session's endpoint or restarting its connection lifecycle.
                self._send_osc(
                    host.ip_address, host.port, "/DS2/HC/Connect", [("i", local_port)]
                )
                return
            # Register first, so that haptics can be sent before the Connect
            # response arrives.
            self._connected_hosts[key] = host
            try:
                self._send_osc(
                    host.ip_address, host.port, "/DS2/HC/Connect", [("i", local_port)]
                )
            except Exception:
                # Restore the pre-registration state when the send fails.
                del self._connected_hosts[key]
                raise
            self._enable_callbacks_locked()
            self._start_keepalive_locked(key)

    def disconnect(self, host: Host) -> None:
        """Disconnect from a DS.

        Sends `/DS2/HC/Disconnect <local_port>` to `host`. When the last
        connection is closed, this waits until the stream callbacks that are
        still running have finished.

        Args:
            host: The same host information that was passed to `connect_to_host`.
        Raises:
            NotConnectedError: If no connection to the given host exists.
        """
        key: _HostKey = (host.ip_address, host.port)
        with self._conn_lock:
            if key not in self._connected_hosts:
                raise NotConnectedError(
                    f"Not connected to {host.ip_address}:{host.port}"
                )
            del self._connected_hosts[key]
            keepalive_thread = self._stop_keepalive_locked(key)
            last_connection = not self._connected_hosts
            callback_generation = None
            if last_connection:
                callback_generation = self._disable_callbacks_locked()
                # Clearing while ``_conn_lock`` is held prevents a handler that
                # received a late UDP packet from recreating the caches right
                # after the disconnect.
                with self._data_lock:
                    self._clear_stream_caches_locked()

            # Serialising the Connect/Disconnect order through ``_conn_lock``
            # keeps a reconnect made while waiting for callbacks to finish from
            # being cancelled by a stale Disconnect.
            local_port = self._actual_local_port
            if local_port is not None:
                self._send_osc(
                    host.ip_address, host.port,
                    "/DS2/HC/Disconnect", [("i", local_port)],
                )

        _join_keepalive_threads([keepalive_thread] if keepalive_thread is not None else [])
        if callback_generation is not None:
            self._wait_for_callback_dispatches(callback_generation)

    def _start_keepalive_locked(self, key: _HostKey) -> None:
        """Start the connection's keepalive worker while ``_conn_lock`` is held."""
        if key in self._keepalive_workers:
            return
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._run_keepalive,
            args=(key, stop_event),
            daemon=True,
        )
        self._keepalive_workers[key] = (stop_event, thread)
        thread.start()

    def _stop_keepalive_locked(self, key: _HostKey) -> Optional[threading.Thread]:
        """Stop one keepalive worker while ``_conn_lock`` is held."""
        worker = self._keepalive_workers.pop(key, None)
        if worker is None:
            return None
        stop_event, thread = worker
        stop_event.set()
        return thread

    def _stop_all_keepalives_locked(self) -> List[threading.Thread]:
        """Stop all keepalive workers while ``_conn_lock`` is held."""
        workers = list(self._keepalive_workers.values())
        self._keepalive_workers.clear()
        for stop_event, _ in workers:
            stop_event.set()
        return [thread for _, thread in workers]

    def _run_keepalive(self, key: _HostKey, stop_event: threading.Event) -> None:
        while not stop_event.wait(_KEEPALIVE_INTERVAL_SECONDS):
            with self._conn_lock:
                host = self._connected_hosts.get(key)
                local_port = self._actual_local_port
                if host is None:
                    return
                if local_port is not None:
                    try:
                        # Serialise the order against the Disconnect sent by
                        # ``disconnect``.
                        self._send_osc(
                            host.ip_address,
                            host.port,
                            "/DS2/HC/Connect",
                            [("i", local_port)],
                        )
                    except Exception:
                        # A failed keepalive must not terminate the connection's
                        # retry loop; the next interval can restore the session.
                        pass

    def _enable_callbacks_locked(self) -> None:
        """Enable callback dispatch while ``_conn_lock`` is held."""
        with self._callback_condition:
            self._callbacks_enabled = True

    def _disable_callbacks_locked(self) -> int:
        """Disable callbacks and advance their generation while ``_conn_lock`` is held."""
        with self._callback_condition:
            callback_generation = self._callback_generation
            self._callbacks_enabled = False
            self._callback_generation += 1
            return callback_generation

    def _reserve_callback_dispatch_locked(
        self, callbacks: list, updates: list
    ) -> Optional[int]:
        """Reserve one callback dispatch generation while ``_conn_lock`` is held."""
        if not callbacks or not updates:
            return None
        with self._callback_condition:
            if not self._callbacks_enabled:
                return None
            callback_generation = self._callback_generation
            self._active_callback_dispatches[callback_generation] = (
                self._active_callback_dispatches.get(callback_generation, 0) + 1
            )
        return callback_generation

    def _dispatch_callbacks(
        self, callbacks: list, updates: list, callback_generation: int
    ) -> None:
        """Invoke a reserved callback dispatch only while its generation is active."""
        current_dispatches = getattr(
            self._callback_dispatch_state, "active_dispatches", {}
        )
        next_dispatches = dict(current_dispatches)
        next_dispatches[callback_generation] = (
            next_dispatches.get(callback_generation, 0) + 1
        )
        self._callback_dispatch_state.active_dispatches = next_dispatches
        try:
            for update in updates:
                for callback in callbacks:
                    with self._callback_condition:
                        if (
                            not self._callbacks_enabled
                            or self._callback_generation != callback_generation
                        ):
                            return
                    try:
                        callback(deepcopy(update))
                    except Exception:
                        # Keep one failing callback from skipping the others.
                        _logger.exception(
                            "Unhandled exception in callback %r for %s",
                            callback,
                            type(update).__name__,
                        )
        finally:
            self._callback_dispatch_state.active_dispatches = current_dispatches
            with self._callback_condition:
                active_dispatches = self._active_callback_dispatches.get(
                    callback_generation, 0
                )
                if active_dispatches <= 1:
                    self._active_callback_dispatches.pop(callback_generation, None)
                else:
                    self._active_callback_dispatches[callback_generation] = (
                        active_dispatches - 1
                    )
                self._callback_condition.notify_all()

    def _wait_for_callback_dispatches(self, callback_generation: int) -> None:
        """Wait for foreign dispatches in one disabled callback generation."""
        own_dispatches = getattr(
            self._callback_dispatch_state, "active_dispatches", {}
        ).get(callback_generation, 0)
        with self._callback_condition:
            while (
                self._active_callback_dispatches.get(callback_generation, 0)
                > own_dispatches
            ):
                self._callback_condition.wait()

    def _clear_stream_caches_locked(self) -> None:
        """Clear the caches of every stream. Must be called with ``_data_lock`` held."""
        self._gloves.clear()
        self._controllers.clear()
        self._ergonomics.clear()
        self._skeletons.clear()
        self._rawskeletons.clear()
        self._rawsensors.clear()

    def _remove_glove_from_stream_caches_locked(self, glove_id: str) -> None:
        """Remove the given ID from every stream. Must be called with ``_data_lock`` held."""
        self._gloves.pop(glove_id, None)
        self._controllers.pop(glove_id, None)
        self._ergonomics.pop(glove_id, None)
        self._skeletons.pop(glove_id, None)
        self._rawskeletons.pop(glove_id, None)
        self._rawsensors.pop(glove_id, None)

    # -------------------------------------------------------------------------
    # Glove data queries
    # -------------------------------------------------------------------------

    def does_glove_support_haptics(self, glove_id: str) -> bool:
        """Check whether the glove supports haptics.

        Args:
            glove_id: ID of the glove to check.
        Returns:
            Whether the haptics feature is present.
        Raises:
            InvalidIDError: If no glove with the given ID exists.
        """
        with self._data_lock:
            if glove_id not in self._gloves:
                raise InvalidIDError(f"Glove not found: {glove_id!r}")
            return self._gloves[glove_id].is_haptics

    def get_data_for_glove(self, glove_id: str) -> GloveData:
        """Read the glove information for a glove ID.

        Args:
            glove_id: ID of the glove to read.
        Returns:
            A snapshot of the glove information.
        Raises:
            InvalidIDError: If no glove with the given ID exists.
        """
        with self._data_lock:
            if glove_id not in self._gloves:
                raise InvalidIDError(f"Glove not found: {glove_id!r}")
            return deepcopy(self._gloves[glove_id])

    def get_controller_data_for_glove(self, glove_id: str) -> ControllerData:
        """Read the controller input data for a glove ID.

        Args:
            glove_id: ID of the glove to read.
        Returns:
            A snapshot of the controller input data.
        Raises:
            InvalidIDError: If no data for the given ID has been received yet.
        """
        with self._data_lock:
            if glove_id not in self._controllers:
                raise InvalidIDError(
                    f"Controller data not found for glove: {glove_id!r}"
                )
            return deepcopy(self._controllers[glove_id])

    def get_ergonomics_data_for_glove(self, glove_id: str) -> ErgonomicsData:
        """Read the finger opening and bending angle data for a glove ID.

        Args:
            glove_id: ID of the glove to read.
        Returns:
            A snapshot of the ergonomics data.
        Raises:
            InvalidIDError: If no data for the given ID has been received yet.
        """
        with self._data_lock:
            if glove_id not in self._ergonomics:
                raise InvalidIDError(
                    f"Ergonomics data not found for glove: {glove_id!r}"
                )
            return deepcopy(self._ergonomics[glove_id])

    def get_skeleton_data_for_glove(self, glove_id: str) -> SkeletonData:
        """Read the joint position and rotation data for a glove ID.

        Args:
            glove_id: ID of the glove to read.
        Returns:
            A snapshot of the skeleton data.
        Raises:
            InvalidIDError: If no data for the given ID has been received yet.
        """
        with self._data_lock:
            if glove_id not in self._skeletons:
                raise InvalidIDError(
                    f"Skeleton data not found for glove: {glove_id!r}"
                )
            return deepcopy(self._skeletons[glove_id])

    def get_raw_skeleton_data_for_glove(self, glove_id: str) -> RawSkeletonData:
        """Read the pre-retarget hand skeleton for a glove ID.

        Returns:
            An independent snapshot, including positions and rotations.

        Raises:
            InvalidIDError: If no data for the given ID has been received yet.
        """
        with self._data_lock:
            if glove_id not in self._rawskeletons:
                raise InvalidIDError(
                    f"Raw skeleton data not found for glove: {glove_id!r}"
                )
            return deepcopy(self._rawskeletons[glove_id])

    def get_rawsensor_data_for_glove(self, glove_id: str) -> RawSensorData:
        """Read the raw sensor Transform data for a glove ID.

        Args:
            glove_id: ID of the glove to read.
        Returns:
            A snapshot of the raw sensor Transform data.
        Raises:
            InvalidIDError: If no data for the given ID has been received yet.
        """
        with self._data_lock:
            if glove_id not in self._rawsensors:
                raise InvalidIDError(
                    f"Raw sensor data not found for glove: {glove_id!r}"
                )
            return deepcopy(self._rawsensors[glove_id])

    def get_ids_of_available_gloves(self) -> List[str]:
        """Read the IDs of every glove that is currently known.

        Returns:
            A list of glove IDs.
        """
        with self._data_lock:
            return list(self._gloves.keys())

    def get_number_of_available_gloves(self) -> int:
        """Read the total number of gloves that are currently known.

        Returns:
            The total number of gloves.
        """
        with self._data_lock:
            return len(self._gloves)

    # -------------------------------------------------------------------------
    # Haptics
    # -------------------------------------------------------------------------

    def vibrate_glove(
        self,
        glove_id: str,
        frequency: float,
        amplitude: float,
        duration: float,
    ) -> None:
        """Make the glove vibrate.

        The command is sent to every DS host that is currently connected.

        Args:
            glove_id: ID of the glove to vibrate.
            frequency: Vibration frequency (Hz, 100.0 to 500.0).
            amplitude: Vibration amplitude (0.0 to 1.0).
            duration: Vibration duration (seconds, 0.001 to 1.0).
        Raises:
            InvalidIDError: If no glove with the given ID exists.
            ValueError: If frequency, amplitude or duration is outside the range of the specification or is not a finite value.
        """
        _validate_haptics_argument("frequency", frequency, 100.0, 500.0)
        _validate_haptics_argument("amplitude", amplitude, 0.0, 1.0)
        _validate_haptics_argument("duration", duration, 0.001, 1.0)

        with self._data_lock:
            if glove_id not in self._gloves:
                raise InvalidIDError(f"Glove not found: {glove_id!r}")

        address = f"/DS2/HC/{glove_id}/Haptics/Body"
        osc_args: List[Tuple[str, object]] = [
            ("i", _PROTOCOL_VERSION),
            ("f", float(frequency)),
            ("f", float(amplitude)),
            ("f", float(duration)),
        ]

        with self._conn_lock:
            hosts = list(self._connected_hosts.values())

        for host in hosts:
            self._send_osc(host.ip_address, host.port, address, osc_args)

    def request_retarget_profile_info(self, profile_uuid: str, request_id: int) -> None:
        """Request the display name and description of a retarget profile from DivingStation.

        The response is delivered to the callback registered with
        :meth:`register_callback_for_retarget_profile_info_stream`.

        Args:
            profile_uuid: The 36-character UUID to query.
            request_id: Signed 32-bit integer that correlates a request with its response.
        Raises:
            ValueError: If the UUID or the request ID does not match the format of the protocol.
        """
        if not _is_valid_profile_uuid(profile_uuid):
            raise ValueError("profile_uuid must be a UUID in 8-4-4-4-12 format")
        if (
            not isinstance(request_id, int)
            or isinstance(request_id, bool)
            or not -(2 ** 31) <= request_id < 2 ** 31
        ):
            raise ValueError("request_id must be a signed 32-bit integer")

        osc_args: List[Tuple[str, object]] = [
            ("i", _PROTOCOL_VERSION),
            ("i", request_id),
            ("s", profile_uuid),
        ]
        with self._conn_lock:
            hosts = list(self._connected_hosts.values())
        for host in hosts:
            self._send_osc(
                host.ip_address,
                host.port,
                "/DS2/HC/HandSkeleton/Profile/Get",
                osc_args,
            )

    def _send_osc(
        self,
        ip: str,
        port: int,
        address: str,
        args: List[Tuple[str, object]],
    ) -> None:
        """Send an OSC message over this client's send socket."""
        self._osc_sender.send(ip, port, address, args)

    # -------------------------------------------------------------------------
    # Callback registration
    # -------------------------------------------------------------------------

    def register_callback_for_glove_data_stream(
        self, callback: Callable[[GloveData], None]
    ) -> None:
        """Register a callback invoked when the glove information is updated.

        Every time `/DS2/HC/Device` is received, the callback is invoked with
        the updated `GloveData` as its argument. The callback is invoked from
        the OSC receive thread. Records whose `connected_state` is
        `Unconnected` are passed as well, but the data for that ID can no
        longer be read at that point.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.

        Args:
            callback: Callback function to register.
        """
        with self._data_lock:
            self._glove_cbs.append(callback)

    def register_callback_for_controller_data_stream(
        self, callback: Callable[[ControllerData], None]
    ) -> None:
        """Register a callback invoked when the controller data is updated.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.

        Args:
            callback: Callback function to register.
        """
        with self._data_lock:
            self._controller_cbs.append(callback)

    def register_callback_for_ergonomics_stream(
        self, callback: Callable[[ErgonomicsData], None]
    ) -> None:
        """Register a callback invoked when the ergonomics data is updated.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.

        Args:
            callback: Callback function to register.
        """
        with self._data_lock:
            self._ergonomics_cbs.append(callback)

    def register_callback_for_skeleton_stream(
        self, callback: Callable[[SkeletonData], None]
    ) -> None:
        """Register a callback invoked when the skeleton data is updated.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.

        Args:
            callback: Callback function to register.
        """
        with self._data_lock:
            self._skeleton_cbs.append(callback)

    def register_callback_for_raw_skeleton_stream(
        self, callback: Callable[[RawSkeletonData], None]
    ) -> None:
        """Register a callback invoked when the pre-retarget skeleton is updated.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.
        """
        with self._data_lock:
            self._rawskeleton_cbs.append(callback)

    def register_callback_for_rawsensor_stream(
        self, callback: Callable[[RawSensorData], None]
    ) -> None:
        """Register a callback invoked when the raw sensor Transform data is updated.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.

        Args:
            callback: Callback function to register.
        """
        with self._data_lock:
            self._rawsensor_cbs.append(callback)

    def register_callback_for_retarget_profile_info_stream(
        self, callback: Callable[[RetargetProfileInfo], None]
    ) -> None:
        """Register a callback that receives the retarget profile information response.

        Exceptions raised by the callback are logged to the `contactglovesdk`
        logger and do not prevent other callbacks from being invoked.
        """
        with self._data_lock:
            self._retarget_profile_info_cbs.append(callback)

    # -------------------------------------------------------------------------
    # OSC receive handlers (called from the server thread)
    # -------------------------------------------------------------------------

    def _on_device(self, address: str, *args: object) -> None:
        updated = parse_device_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                callback_updates = []
                for glove in updated:
                    if glove.connected_state == DeviceConnectedState.Unconnected:
                        self._remove_glove_from_stream_caches_locked(glove.id)
                        callback_updates.append(glove)
                    elif _store_admitted_records(self._gloves, [glove]):
                        callback_updates.append(glove)
                cbs = list(self._glove_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(
                    cbs, callback_updates
                )
        if callback_generation is None:
            return
        self._dispatch_callbacks(cbs, callback_updates, callback_generation)

    def _on_controller(self, address: str, *args: object) -> None:
        updated = parse_controller_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                updated = _store_admitted_records(self._controllers, updated)
                cbs = list(self._controller_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(cbs, updated)
        if callback_generation is None:
            return
        self._dispatch_callbacks(cbs, updated, callback_generation)

    def _on_handskeleton(self, address: str, *args: object) -> None:
        updated = parse_handskeleton_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                updated = _store_admitted_records(self._skeletons, updated)
                cbs = list(self._skeleton_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(cbs, updated)
        if callback_generation is None:
            return
        self._dispatch_callbacks(cbs, updated, callback_generation)

    def _on_ergonomics(self, address: str, *args: object) -> None:
        updated = parse_ergonomics_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                updated = _store_admitted_records(self._ergonomics, updated)
                cbs = list(self._ergonomics_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(cbs, updated)
        if callback_generation is None:
            return
        self._dispatch_callbacks(cbs, updated, callback_generation)

    def _on_rawskeleton(self, address: str, *args: object) -> None:
        updated = parse_rawskeleton_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                updated = _store_admitted_records(self._rawskeletons, updated)
                cbs = list(self._rawskeleton_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(cbs, updated)
        if callback_generation is None:
            return
        self._dispatch_callbacks(cbs, updated, callback_generation)

    def _on_retarget_profile_info(self, address: str, *args: object) -> None:
        updated = parse_retarget_profile_info_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                cbs = list(self._retarget_profile_info_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(cbs, updated)
        if callback_generation is not None:
            self._dispatch_callbacks(cbs, updated, callback_generation)

    def _on_rawsensor(self, address: str, *args: object) -> None:
        updated = parse_rawsensor_message(args)
        if not updated:
            return
        with self._conn_lock:
            if not self._connected_hosts:
                return
            with self._data_lock:
                updated = _store_admitted_records(self._rawsensors, updated)
                cbs = list(self._rawsensor_cbs)
                callback_generation = self._reserve_callback_dispatch_locked(cbs, updated)
        if callback_generation is None:
            return
        self._dispatch_callbacks(cbs, updated, callback_generation)

    # -------------------------------------------------------------------------
    # Context manager
    # -------------------------------------------------------------------------

    def __enter__(self) -> "ContactGloveClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class _OscUdpSender:
    """Reuse one UDP send socket within the process."""

    def __init__(self, port: int = 0) -> None:
        self._port_hint = port
        self._socket: Optional[socket.socket] = None
        self._actual_port: Optional[int] = None
        self._lock = threading.Lock()

    @property
    def port(self) -> Optional[int]:
        """Port number used by the send socket. `None` while it has not been created."""
        with self._lock:
            return self._actual_port

    def send(
        self,
        ip: str,
        port: int,
        address: str,
        args: List[Tuple[str, object]],
    ) -> None:
        """Build an OSC message and send it."""
        builder = OscMessageBuilder(address=address)
        for tag, value in args:
            builder.add_arg(value, tag)
        msg = builder.build()

        with self._lock:
            if self._socket is None:
                self._create_socket()

            try:
                self._socket.sendto(msg.dgram, (ip, port))
            except OSError:
                # Keep the admitted source port across a transient UDP send
                # error.
                pass

    def _create_socket(self) -> None:
        sock: Optional[socket.socket] = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", self._port_hint))
        except OSError as exc:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            raise SDKNotAvailableError(
                f"Failed to bind local UDP send socket on port "
                f"{self._port_hint}: {exc}"
            ) from exc

        self._socket = sock
        self._actual_port = sock.getsockname()[1]

    def _close_locked(self) -> None:
        sock = self._socket
        self._socket = None
        self._actual_port = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def close(self) -> None:
        """Close the send socket that is being held."""
        with self._lock:
            self._close_locked()


_osc_sender = _OscUdpSender()
atexit.register(_osc_sender.close)


def _send_osc(
    ip: str,
    port: int,
    address: str,
    args: List[Tuple[str, object]],
) -> None:
    """Send an OSC message from the shared UDP socket kept for compatibility."""
    try:
        _osc_sender.send(ip, port, address, args)
    except SDKNotAvailableError:
        pass


def _validate_haptics_argument(
    name: str, value: object, minimum: float, maximum: float
) -> None:
    """Raise ValueError unless a haptics argument is finite and in range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between {minimum} and {maximum}")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be a finite number between {minimum} and {maximum}")


def _store_admitted_records(cache: Dict[str, object], records: list) -> list:
    """Store updates without allowing an unbounded number of device IDs.

    Existing IDs are always refreshed.  New IDs are admitted only until the
    C++ SDK's 16-device cache limit is reached; callbacks receive only those
    records that were admitted.
    """
    accepted = []
    for record in records:
        record_id = record.id
        if record_id in cache or len(cache) < _MAX_CACHED_DEVICES:
            cache[record_id] = record
            accepted.append(record)
    return accepted


def _join_keepalive_threads(threads: List[threading.Thread]) -> None:
    for thread in threads:
        if thread is not threading.current_thread():
            thread.join()
