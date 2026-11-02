"""
MODULE:    qambit.core.device
AUTHOR(S): Yann Chemin
PURPOSE:   Detects a connected Suunto watch from sysfs, without talking to it.
SPDX-License-Identifier: Unlicense

openambit2 listens to udev; reading /sys/class/hidraw gives the same answer
and needs no extra module. The watch itself is only opened by
openambit-cli.
"""

import glob
import os

SUUNTO_VENDOR_ID = 0x1493


def _uevent(path):
    values = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                values[key] = value
    except OSError:
        pass
    return values


def find_watches(sysfs_root="/sys/class/hidraw"):
    """
    Lists the connected Suunto HID devices.

    :return: List of dicts with "node" (/dev/hidrawN), "name" and "product_id"
    """
    watches = []
    for device_dir in sorted(glob.glob(os.path.join(sysfs_root, "hidraw*"))):
        info = _uevent(os.path.join(device_dir, "device", "uevent"))
        # HID_ID is "bus:vendor:product" in hexadecimal
        parts = info.get("HID_ID", "").split(":")
        if len(parts) != 3:
            continue
        try:
            vendor, product = int(parts[1], 16), int(parts[2], 16)
        except ValueError:
            continue
        if vendor == SUUNTO_VENDOR_ID:
            watches.append(
                {
                    "node": "/dev/" + os.path.basename(device_dir),
                    "name": info.get("HID_NAME", "Suunto"),
                    "product_id": product,
                }
            )
    return watches
