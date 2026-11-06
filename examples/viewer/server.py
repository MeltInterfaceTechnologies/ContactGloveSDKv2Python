#!/usr/bin/env python3
"""Mock DivingStation server that replays fbx-hand-timeline JSON as OSC streams.

Usage:
    python viewer/server.py <path/to/fbx-hand-timeline.json>

Listens on UDP port 25791 (DivingStation default).
Accepts /DS2/HC/Connect <port> and streams /DS2/HC/HandSkeleton to registered clients.
Loops the recording indefinitely.
"""

import argparse
import json
import socket
import threading
import time
from pathlib import Path

from pythonosc import dispatcher
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_server import ThreadingOSCUDPServer

DS_PORT = 25791
DEVICE_ID_LEFT = "CG3-LEFT-001"
DEVICE_ID_RIGHT = "CG3-RIGHT-001"
PROFILE_UUID = "00000000-0000-4000-8000-000000000001"

_IDENTITY_QUAT = {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0}


def _send_osc(ip: str, port: int, address: str, args: list) -> None:
    builder = OscMessageBuilder(address=address)
    for tag, value in args:
        builder.add_arg(value, tag)
    msg = builder.build()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.sendto(msg.dgram, (ip, port))
        except OSError:
            pass


def _hand_to_skeleton_record(hand: dict, device_id: str, is_left: bool, timestamp_ms: int) -> list:
    """Return the 157 OSC args for one HandSkeleton record (without the leading version int).

    Node order matches SkeletonNode enum (25 positions):
        wrist, thumb_cmc..tip, index_cmc..tip, middle_cmc..tip, ring_cmc..tip, little_cmc..tip

    Rotation order matches SkeletonRotationNode enum (19 rotations):
        thumb_cmc/mcp/ip, index_cmc/mcp/pip/dip, middle_cmc/mcp/pip/dip,
        ring_cmc/mcp/pip/dip, little_cmc/mcp/pip/dip
    """
    joints = hand["joint_positions"]
    quats = hand.get("hand_quaternions", {})

    def q(finger: str, joint_name: str) -> dict:
        return quats.get(finger, {}).get(joint_name, _IDENTITY_QUAT)

    def pos(chain: list, i: int) -> list:
        return chain[i] if i < len(chain) else [0.0, 0.0, 0.0]

    thumb = joints.get("thumb", [])    # [wrist_origin, cmc, mcp, ip, tip] = 5 entries
    index = joints.get("index", [])    # [wrist_origin, cmc, mcp, pip, dip, tip] = 6 entries
    middle = joints.get("middle", [])
    ring = joints.get("ring", [])
    pinky = joints.get("pinky", [])    # JSON uses "pinky"; maps to "little" in the protocol

    # 25 positions in SkeletonNode index order.
    # JSON position[0] is always [0,0,0] (wrist origin); joints start at index 1.
    positions = [
        [0.0, 0.0, 0.0],                                              # wrist
        pos(thumb, 1), pos(thumb, 2), pos(thumb, 3), pos(thumb, 4),  # thumb cmc..tip
        pos(index, 1), pos(index, 2), pos(index, 3), pos(index, 4), pos(index, 5),
        pos(middle, 1), pos(middle, 2), pos(middle, 3), pos(middle, 4), pos(middle, 5),
        pos(ring, 1), pos(ring, 2), pos(ring, 3), pos(ring, 4), pos(ring, 5),
        pos(pinky, 1), pos(pinky, 2), pos(pinky, 3), pos(pinky, 4), pos(pinky, 5),
    ]

    # 19 local quaternions in SkeletonRotationNode index order.
    # CMC rotations for index/middle/ring/little are not in the JSON; use identity.
    rotations = [
        q("thumb", "cmc"), q("thumb", "mcp"), q("thumb", "ip"),
        _IDENTITY_QUAT, q("index", "mcp"), q("index", "pip"), q("index", "dip"),
        _IDENTITY_QUAT, q("middle", "mcp"), q("middle", "pip"), q("middle", "dip"),
        _IDENTITY_QUAT, q("ring", "mcp"), q("ring", "pip"), q("ring", "dip"),
        _IDENTITY_QUAT, q("pinky", "mcp"), q("pinky", "pip"), q("pinky", "dip"),
    ]

    hi = (timestamp_ms >> 32) & 0xFFFF_FFFF
    lo = timestamp_ms & 0xFFFF_FFFF

    args: list = [
        ("s", device_id),
        ("s", PROFILE_UUID),          # profile_uuid
        ("i", 1 if is_left else 0),  # is_left
        ("i", hi), ("i", lo),        # generated_at_ms hi/lo
        ("i", 0),                    # tracking_state (Tracked)
    ]
    for px, py, pz in positions:
        args += [("f", float(px)), ("f", float(py)), ("f", float(pz))]
    for rot in rotations:
        args += [
            ("f", float(rot["w"])), ("f", float(rot["x"])),
            ("f", float(rot["y"])), ("f", float(rot["z"])),
        ]
    return args  # 157 args total per the spec


class MockDivingStationServer:
    def __init__(self, data: dict) -> None:
        self._data = data
        self._clients: dict = {}   # (ip, port) -> True
        self._lock = threading.Lock()
        self._running = False

    # ------------------------------------------------------------------
    # OSC command handlers (called from the server receive thread)
    # ------------------------------------------------------------------

    def _on_connect(self, address: str, *args: object) -> None:
        if not args or not isinstance(args[0], int):
            return
        port = int(args[0])
        with self._lock:
            self._clients[("127.0.0.1", port)] = True
        print(f"[server] Client registered at 127.0.0.1:{port}")

    def _on_disconnect(self, address: str, *args: object) -> None:
        if not args or not isinstance(args[0], int):
            return
        port = int(args[0])
        with self._lock:
            self._clients.pop(("127.0.0.1", port), None)
        print(f"[server] Client unregistered from 127.0.0.1:{port}")

    # ------------------------------------------------------------------
    # Frame streaming thread
    # ------------------------------------------------------------------

    def _stream_frames(self) -> None:
        frames = self._data["frames"]
        interval_s = self._data["sample_interval_ms"] / 1000.0
        frame_idx = 0

        while self._running:
            frame = frames[frame_idx]
            ts = frame["captured_at_ms"]
            hands = frame["hands"]

            skeleton_messages: list = []
            if "left" in hands:
                skeleton_messages.append(
                    [("i", 2)] + _hand_to_skeleton_record(
                        hands["left"], DEVICE_ID_LEFT, True, ts
                    )
                )
            if "right" in hands:
                skeleton_messages.append(
                    [("i", 2)] + _hand_to_skeleton_record(
                        hands["right"], DEVICE_ID_RIGHT, False, ts
                    )
                )

            # Device info: 2 records for left and right gloves.
            device_args: list = [
                ("i", 2),
                ("s", DEVICE_ID_LEFT), ("s", ""), ("i", 100), ("i", 0), ("i", 1),
                ("i", 3), ("i", 4), ("i", 1), ("s", "ContactGlove3 Left"), ("i", 0),
                ("s", DEVICE_ID_RIGHT), ("s", ""), ("i", 100), ("i", 0), ("i", 0),
                ("i", 3), ("i", 6), ("i", 1), ("s", "ContactGlove3 Right"), ("i", 0),
            ]

            with self._lock:
                clients = list(self._clients.keys())

            for ip, port in clients:
                for skeleton_args in skeleton_messages:
                    _send_osc(ip, port, "/DS2/HC/HandSkeleton", skeleton_args)
                _send_osc(ip, port, "/DS2/HC/Device", device_args)

            frame_idx = (frame_idx + 1) % len(frames)
            time.sleep(interval_s)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def start(self) -> None:
        disp = dispatcher.Dispatcher()
        disp.map("/DS2/HC/Connect", self._on_connect)
        disp.map("/DS2/HC/Disconnect", self._on_disconnect)

        server = ThreadingOSCUDPServer(("0.0.0.0", DS_PORT), disp)
        frame_count = len(self._data["frames"])
        duration_s = self._data["recording_duration_ms"] / 1000.0
        print(f"[server] Mock DivingStation server starting on UDP port {DS_PORT}")
        print(f"[server] Loaded {frame_count} frames  ({duration_s:.1f} s, looping)")
        print("[server] Press Ctrl+C to stop.\n")

        self._running = True
        threading.Thread(target=self._stream_frames, daemon=True).start()

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[server] Stopping.")
        finally:
            self._running = False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mock DivingStation server – replays an fbx-hand-timeline JSON recording."
    )
    parser.add_argument("data_file", type=Path, help="Path to the fbx-hand-timeline JSON file")
    args = parser.parse_args()

    with open(args.data_file) as f:
        data = json.load(f)
    MockDivingStationServer(data).start()
