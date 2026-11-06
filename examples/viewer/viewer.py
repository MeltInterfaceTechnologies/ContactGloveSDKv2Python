#!/usr/bin/env python3
"""Hand skeleton viewer – receives /DS2/HC/HandSkeleton via contactglovesdk and draws it.

Usage:
    python viewer.py
    python viewer.py --left <device-id-or-name> --right <device-id-or-name>

Left and right hands are shown side by side.
Each finger chain is drawn in a different colour; joint dots are white.
"""

import argparse
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

# Make the SDK importable when running from any working directory.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 – required for projection='3d'

from contactglovesdk import ContactGloveClient, GloveData, Host, SkeletonData, SkeletonNode

# ---------------------------------------------------------------------------
# Connection settings
# ---------------------------------------------------------------------------

DEFAULT_DS_IP = "127.0.0.1"
DEFAULT_DS_PORT = 25791

# ---------------------------------------------------------------------------
# Skeleton topology
# ---------------------------------------------------------------------------

# Each entry is a chain of SkeletonNode indices that form a continuous bone path.
BONE_CHAINS = [
    # Thumb
    [SkeletonNode.Wrist, SkeletonNode.ThumbCMC, SkeletonNode.ThumbMCP,
     SkeletonNode.ThumbIP, SkeletonNode.ThumbTip],
    # Index
    [SkeletonNode.Wrist, SkeletonNode.IndexCMC, SkeletonNode.IndexMCP,
     SkeletonNode.IndexPIP, SkeletonNode.IndexDIP, SkeletonNode.IndexTip],
    # Middle
    [SkeletonNode.Wrist, SkeletonNode.MiddleCMC, SkeletonNode.MiddleMCP,
     SkeletonNode.MiddlePIP, SkeletonNode.MiddleDIP, SkeletonNode.MiddleTip],
    # Ring
    [SkeletonNode.Wrist, SkeletonNode.RingCMC, SkeletonNode.RingMCP,
     SkeletonNode.RingPIP, SkeletonNode.RingDIP, SkeletonNode.RingTip],
    # Little (pinky)
    [SkeletonNode.Wrist, SkeletonNode.LittleCMC, SkeletonNode.LittleMCP,
     SkeletonNode.LittlePIP, SkeletonNode.LittleDIP, SkeletonNode.LittleTip],
    # Palm (lateral CMC bar)
    [SkeletonNode.IndexCMC, SkeletonNode.MiddleCMC,
     SkeletonNode.RingCMC, SkeletonNode.LittleCMC],
]

BONE_COLORS = [
    "#e74c3c",   # thumb   – red
    "#e67e22",   # index   – orange
    "#2ecc71",   # middle  – green
    "#3498db",   # ring    – blue
    "#9b59b6",   # little  – purple
    "#7f8c8d",   # palm    – grey
]

AXIS_HALF = 0.22   # ± metres shown on each axis


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _setup_ax(ax: "Axes3D", title: str, elev: float, azim: float) -> None:
    """Apply fixed axis styling once at startup."""
    ax.set_title(title, fontsize=11)
    ax.set_xlim(-AXIS_HALF, AXIS_HALF)
    ax.set_ylim(-AXIS_HALF, AXIS_HALF)
    ax.set_zlim(-AXIS_HALF, AXIS_HALF)
    ax.set_xlabel("X (m)", fontsize=7)
    ax.set_ylabel("Y (m)", fontsize=7)
    ax.set_zlabel("Z (m)", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.view_init(elev=elev, azim=azim)


class _HandArtists:
    def __init__(self, ax: "Axes3D", title: str) -> None:
        self._ax = ax
        self._title = title
        self._last_skeleton: Optional[SkeletonData] = None
        self._lines = [
            ax.plot([], [], [], color=color, linewidth=2.2)[0]
            for color in BONE_COLORS
        ]
        self._joints = ax.scatter(
            [], [], [], color="white", s=18, zorder=5, depthshade=False
        )
        self._waiting_text = ax.text(
            0, 0, 0, "Waiting for data...",
            color="gray", ha="center", va="center", fontsize=9,
        )

    def update(self, skel: Optional[SkeletonData], title: str) -> None:
        if title != self._title:
            self._title = title
            self._ax.set_title(title, fontsize=11)

        if skel is None:
            if self._last_skeleton is not None:
                self._last_skeleton = None
                for line in self._lines:
                    line.set_data([], [])
                    line.set_3d_properties([])
                self._joints._offsets3d = ([], [], [])
            self._waiting_text.set_visible(True)
            return

        self._waiting_text.set_visible(False)
        if skel is self._last_skeleton:
            return
        self._last_skeleton = skel

        positions = skel.positions
        for line, chain in zip(self._lines, BONE_CHAINS):
            xs = [positions[n].x for n in chain]
            ys = [positions[n].y for n in chain]
            zs = [positions[n].z for n in chain]
            line.set_data(xs, ys)
            line.set_3d_properties(zs)

        xs = [p.x for p in positions]
        ys = [p.y for p in positions]
        zs = [p.z for p in positions]
        self._joints._offsets3d = (xs, ys, zs)


def _create_hand_artists(ax: "Axes3D", title: str) -> _HandArtists:
    _setup_ax(ax, title, 25.0, -70.0)
    return _HandArtists(ax, title)


# ---------------------------------------------------------------------------
# Main viewer class
# ---------------------------------------------------------------------------

_Side = bool
_LEFT: _Side = True
_RIGHT: _Side = False


def _side_name(side: _Side) -> str:
    return "left" if side else "right"


class SkeletonViewer:
    def __init__(
        self,
        host: Host,
        left_device: Optional[str] = None,
        right_device: Optional[str] = None,
    ) -> None:
        self._host = host
        self._requested: Dict[_Side, Optional[str]] = {
            _LEFT: left_device,
            _RIGHT: right_device,
        }
        self._selected_ids: Dict[_Side, Optional[str]] = {
            _LEFT: None,
            _RIGHT: None,
        }
        self._latest: Dict[_Side, Optional[SkeletonData]] = {
            _LEFT: None,
            _RIGHT: None,
        }
        self._devices_by_id: Dict[str, GloveData] = {}
        self._lock = threading.Lock()
        self._client = ContactGloveClient()

    def _on_device(self, glove: GloveData) -> None:
        with self._lock:
            self._devices_by_id[glove.id] = glove

    def _device_label(self, device_id: Optional[str]) -> str:
        if not device_id:
            return ""
        device = self._devices_by_id.get(device_id)
        if device and device.name:
            return f"{device.name} ({device_id})"
        return device_id

    def _matches_requested_device(self, skel: SkeletonData, requested: str) -> bool:
        if skel.id == requested:
            return True
        device = self._devices_by_id.get(skel.id)
        return device is not None and device.name == requested

    def _on_skeleton(self, skel: SkeletonData) -> None:
        side = _LEFT if skel.is_left else _RIGHT

        with self._lock:
            selected_id = self._selected_ids[side]
            requested = self._requested[side]

            if selected_id is not None:
                if skel.id != selected_id:
                    return
            elif requested is not None:
                if not self._matches_requested_device(skel, requested):
                    return
                self._selected_ids[side] = skel.id
                print(
                    f"[viewer] Selected {_side_name(side)} hand: "
                    f"{self._device_label(skel.id)}"
                )
            else:
                self._selected_ids[side] = skel.id
                print(
                    f"[viewer] Auto-selected {_side_name(side)} hand: "
                    f"{self._device_label(skel.id)}"
                )

            self._latest[side] = skel

    def run(self) -> None:
        self._client.register_callback_for_glove_data_stream(self._on_device)
        self._client.register_callback_for_skeleton_stream(self._on_skeleton)
        self._client.connect_to_host(self._host)
        print(f"[viewer] Connected to {self._host.ip_address}:{self._host.port}")
        print(f"[viewer] Local OSC port: {self._client.local_port}")
        if self._requested[_LEFT] or self._requested[_RIGHT]:
            print(
                "[viewer] Requested devices: "
                f"left={self._requested[_LEFT] or 'auto'}, "
                f"right={self._requested[_RIGHT] or 'auto'}"
            )
        print("[viewer] Close the window or press Ctrl+C to quit.\n")

        fig = plt.figure(figsize=(13, 6.5))
        fig.suptitle("ContactGlove3 Hand Skeleton Viewer", fontsize=12, y=0.98)

        ax_left = fig.add_subplot(121, projection="3d")
        ax_right = fig.add_subplot(122, projection="3d")
        left_artists = _create_hand_artists(ax_left, "Left Hand")
        right_artists = _create_hand_artists(ax_right, "Right Hand")

        def _update(frame_idx: int) -> None:
            with self._lock:
                left = self._latest[_LEFT]
                right = self._latest[_RIGHT]
                left_label = self._device_label(self._selected_ids[_LEFT])
                right_label = self._device_label(self._selected_ids[_RIGHT])

            left_title = f"Left Hand\n{left_label}" if left_label else "Left Hand"
            right_title = f"Right Hand\n{right_label}" if right_label else "Right Hand"

            left_artists.update(left, left_title)
            right_artists.update(right, right_title)

        ani = FuncAnimation(  # noqa: F841 – must be kept alive
            fig, _update, interval=16, cache_frame_data=False
        )
        plt.tight_layout(rect=[0, 0, 1, 0.96])
        plt.show()

        # Cleanup after window is closed
        try:
            self._client.disconnect(self._host)
        except Exception:
            pass
        self._client.close()
        print("[viewer] Done.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ContactGlove3 hand skeleton viewer")
    parser.add_argument(
        "--ds-host",
        default=DEFAULT_DS_IP,
        help=f"DivingStation IP address (default: {DEFAULT_DS_IP})",
    )
    parser.add_argument(
        "--ds-port",
        type=int,
        default=DEFAULT_DS_PORT,
        help=f"DivingStation OSC port (default: {DEFAULT_DS_PORT})",
    )
    parser.add_argument(
        "--left",
        metavar="ID_OR_NAME",
        help="Left-hand device id or /DS2/HC/Device name. Auto-selects if omitted.",
    )
    parser.add_argument(
        "--right",
        metavar="ID_OR_NAME",
        help="Right-hand device id or /DS2/HC/Device name. Auto-selects if omitted.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    viewer = SkeletonViewer(
        Host("DivingStation", args.ds_host, args.ds_port),
        left_device=args.left,
        right_device=args.right,
    )
    viewer.run()
