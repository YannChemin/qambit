"""Tests of qambit.core.device on a fake sysfs."""

from qambit.core.device import find_watches


def _hidraw(root, name, hid_id, hid_name):
    device = root / name / "device"
    device.mkdir(parents=True)
    (device / "uevent").write_text(
        "DRIVER=hid-generic\nHID_ID={}\nHID_NAME={}\n".format(hid_id, hid_name)
    )


def test_find_watches(tmp_path):
    _hidraw(tmp_path, "hidraw0", "0018:000004F3:00003124", "ELAN touchpad")
    _hidraw(tmp_path, "hidraw3", "0003:00001493:0000001B", "Suunto Ambit3 Sport")
    _hidraw(tmp_path, "hidraw4", "garbage", "Broken")
    watches = find_watches(str(tmp_path))
    assert watches == [{"node": "/dev/hidraw3", "name": "Suunto Ambit3 Sport", "product_id": 0x1B}]


def test_no_sysfs(tmp_path):
    assert find_watches(str(tmp_path / "missing")) == []
