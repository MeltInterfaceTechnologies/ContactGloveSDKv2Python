"""Basic usage example for contactglovesdk.

Run this after starting DivingStation (DS must be reachable at ds_host:25791).

DivingStation listens on port 25791 (default).
This script listens on an OS-assigned local port.
"""

import argparse
import threading
import time
from typing import Dict, Optional

from contactglovesdk import (
    ContactGloveClient,
    DeviceConnectedState,
    Host,
    GloveData,
    ErgonomicsData,
    ErgonomicsIndex,
    InvalidIDError,
)

DEFAULT_DS_HOST = "127.0.0.1"
DEFAULT_DS_PORT = 25791


class GloveSelector:
    def __init__(self, requested: Optional[str] = None) -> None:
        self._requested = requested
        self._selected_id: Optional[str] = None
        self._devices_by_id: Dict[str, GloveData] = {}
        self._lock = threading.Lock()

    @property
    def selected_id(self) -> Optional[str]:
        with self._lock:
            return self._selected_id

    def on_glove(self, glove: GloveData) -> None:
        with self._lock:
            self._devices_by_id[glove.id] = glove
            if self._selected_id is not None:
                return
            if self._requested is not None:
                if glove.id != self._requested and glove.name != self._requested:
                    return
            elif glove.connected_state != DeviceConnectedState.Connected:
                return
            self._select_locked(glove.id)

    def on_ergonomics(self, ergonomics: ErgonomicsData) -> None:
        with self._lock:
            if self._selected_id is not None:
                return
            if self._requested is not None and not self._matches_requested_locked(
                ergonomics.id
            ):
                return
            self._select_locked(ergonomics.id)

    def label_for_selected(self) -> str:
        with self._lock:
            if self._selected_id is None:
                return self._requested or "auto"
            device = self._devices_by_id.get(self._selected_id)
            if device and device.name:
                return f"{device.name} ({self._selected_id})"
            return self._selected_id

    def _matches_requested_locked(self, glove_id: str) -> bool:
        if self._requested is None:
            return True
        if glove_id == self._requested:
            return True
        device = self._devices_by_id.get(glove_id)
        return device is not None and device.name == self._requested

    def _select_locked(self, glove_id: str) -> None:
        self._selected_id = glove_id
        device = self._devices_by_id.get(glove_id)
        if device and device.name:
            label = f"{device.name} ({glove_id})"
        else:
            label = glove_id
        print(f"[select]   {label}")


def on_glove(g: GloveData) -> None:
    print(
        f"[device]   id={g.id}  battery={g.battery_percentage}%"
        f"  left={g.is_left}  state={g.connected_state.name}"
    )


def on_ergonomics(e: ErgonomicsData) -> None:
    thumb = e.values[ErgonomicsIndex.ThumbCMC]
    index = e.values[ErgonomicsIndex.IndexMCP]
    print(f"[ergo]     id={e.id}  thumb_cmc={thumb:.1f}°  index_mcp={index:.1f}°")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Basic contactglovesdk usage example")
    parser.add_argument(
        "--ds-host",
        default=DEFAULT_DS_HOST,
        help=f"DivingStation IP address (default: {DEFAULT_DS_HOST})",
    )
    parser.add_argument(
        "--ds-port",
        type=int,
        default=DEFAULT_DS_PORT,
        help=f"DivingStation OSC port (default: {DEFAULT_DS_PORT})",
    )
    parser.add_argument(
        "--glove",
        metavar="ID_OR_NAME",
        help="Device id or /DS2/HC/Device name to poll. Auto-selects if omitted.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    host = Host("localhost", args.ds_host, args.ds_port)
    selector = GloveSelector(args.glove)

    with ContactGloveClient() as client:
        # Register callbacks before connecting so no updates are missed
        def _on_glove(g: GloveData) -> None:
            selector.on_glove(g)
            on_glove(g)

        def _on_ergonomics(e: ErgonomicsData) -> None:
            selector.on_ergonomics(e)
            on_ergonomics(e)

        client.register_callback_for_glove_data_stream(_on_glove)
        client.register_callback_for_ergonomics_stream(_on_ergonomics)

        client.connect_to_host(host)
        print(f"Listening on local port {client.local_port} …")
        print(f"Polling target: {args.glove or 'auto'}")

        for _ in range(5):
            time.sleep(1)

            # Poll-style access
            glove_id = selector.selected_id
            if glove_id is None:
                print(f"[poll]     {selector.label_for_selected()}: no data yet")
                continue

            try:
                glove = client.get_data_for_glove(glove_id)
                print(f"[poll]     id={glove.id}  battery={glove.battery_percentage}%")
            except InvalidIDError:
                print(f"[poll]     {selector.label_for_selected()}: no data yet")

        client.disconnect(host)


if __name__ == "__main__":
    main()
