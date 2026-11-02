"""
MODULE:    qambit.core.logparser
AUTHOR(S): Yann Chemin
PURPOSE:   Reads the exercise logs that openambit2 stores in ~/.openambit
           (one "openambitlog" XML file per move) into plain Python objects.
SPDX-License-Identifier: Unlicense

The files are streamed with iterparse, since a long log holds tens of
thousands of samples (50 MB and more). Units follow libambit's
ambit_log_sample_t: positions in 1e-7 degrees, speeds in 0.01 m/s, the GPS
altitude in 0.01 m, the temperature in 0.1 degree Celsius.
"""

import datetime
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .activity import category_key, classify, prefers_3d

# Values the watch writes when a sensor gives no reading
NO_SPEED = 65535
NO_HR = 255
NO_CADENCE = 255

POSITION_TYPES = ("gps-base", "gps-small", "gps-tiny", "position")


@dataclass
class TrackPoint:
    """One position fix, with the latest sensor values logged before it."""

    utc: datetime.datetime
    elapsed_s: float
    lat: float
    lon: float
    alt_m: float = None
    hr_bpm: int = None
    speed_kmh: float = None
    cadence_rpm: int = None
    distance_m: float = None
    vertical_speed_ms: float = None
    temperature_c: float = None
    ehpe_m: float = None
    satellites: int = None


@dataclass
class Lap:
    """A lap event (start, manual, distance, pause...)."""

    kind: str
    utc: datetime.datetime
    elapsed_s: float
    duration_s: float
    distance_m: float


@dataclass
class AmbitLog:
    """Header values and track of one log file."""

    path: str
    log_id: str
    serial: str = ""
    device_name: str = ""
    model: str = ""
    start: datetime.datetime = None
    activity: str = ""
    activity_type: int = 0
    activity_type_name: str = ""
    duration_s: float = 0.0
    distance_m: float = 0.0
    ascent_m: float = 0.0
    descent_m: float = 0.0
    alt_min_m: float = None
    alt_max_m: float = None
    energy_kcal: float = None
    hr_avg: int = None
    hr_max: int = None
    points: list = field(default_factory=list)
    laps: list = field(default_factory=list)

    @property
    def category(self):
        """Stable category key: ground, water, air, vertical or underwater."""
        return category_key(classify(self.activity_type, self.activity))

    @property
    def prefers_3d(self):
        """True for air sports, whose tracks are best seen in 3D."""
        return prefers_3d(classify(self.activity_type, self.activity))


def _text(elem, tag, default=None):
    child = elem.find(tag)
    if child is None or child.text is None or child.text.strip() == "":
        return default
    return child.text.strip()


def _int(elem, tag, default=None):
    value = _text(elem, tag)
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _utc(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return None


def _local(value):
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def log_id_from_path(path):
    """Identifier of a log: its file name without extension."""
    return os.path.splitext(os.path.basename(path))[0]


def _read_header(log, header):
    log.start = _local(_text(header, "DateTime"))
    log.duration_s = (_int(header, "Duration", 0) or 0) / 1000.0
    log.distance_m = float(_int(header, "Distance", 0) or 0)
    log.ascent_m = float(_int(header, "Ascent", 0) or 0)
    log.descent_m = float(_int(header, "Descent", 0) or 0)
    log.activity_type = _int(header, "ActivityType", 0) or 0
    log.activity = _text(header, "Activity", "") or ""
    log.activity_type_name = _text(header, "ActivityTypeName", "") or ""
    energy = _int(header, "Energy")
    log.energy_kcal = float(energy) if energy is not None else None
    altitude = header.find("Altitude")
    if altitude is not None:
        # The int16 limits mean "no altitude recorded"
        alt_max, alt_min = _int(altitude, "Max"), _int(altitude, "Min")
        log.alt_max_m = None if alt_max in (None, 32767, -32768) else alt_max
        log.alt_min_m = None if alt_min in (None, 32767, -32768) else alt_min
    hr = header.find("HR")
    if hr is not None:
        # Zero means "no HR belt"
        log.hr_avg = _int(hr, "Avg") or None
        log.hr_max = _int(hr, "Max") or None


class _State:
    """Latest periodic values, carried forward onto the next position fix."""

    def __init__(self):
        self.baro_alt = None
        self.gps_alt = None
        self.hr = None
        self.speed = None
        self.cadence = None
        self.distance = None
        self.vspeed = None
        self.temperature = None

    @property
    def altitude(self):
        # The pressure altitude (what the watch shows) beats the noisier GPS one
        return self.baro_alt if self.baro_alt is not None else self.gps_alt

    def read_periodic(self, sample):
        """Updates the state; returns the (lat, lon) the sample carries, if any."""
        alt = _int(sample, "Altitude")
        if alt is not None:
            self.baro_alt = float(alt)
        gps_alt = _int(sample, "GPSAltitude")
        if gps_alt is not None:
            self.gps_alt = gps_alt / 100.0
        hr = _int(sample, "HR")
        if hr is not None:
            self.hr = None if hr in (0, NO_HR) else hr
        speed = _int(sample, "Speed")
        if speed is not None:
            self.speed = None if speed == NO_SPEED else speed * 0.036
        cadence = _int(sample, "Cadence")
        if cadence is None:
            cadence = _int(sample, "WristCadence")
        if cadence is not None:
            self.cadence = None if cadence in (NO_CADENCE, 0xFFFF) else cadence
        distance = _int(sample, "Distance")
        if distance is not None:
            self.distance = float(distance)
        vspeed = _int(sample, "VerticalSpeed")
        if vspeed is not None:
            self.vspeed = vspeed / 100.0
        temperature = _int(sample, "Temperature")
        if temperature is not None:
            self.temperature = temperature / 10.0
        lat, lon = _int(sample, "Latitude"), _int(sample, "Longitude")
        if lat is not None and lon is not None:
            return lat, lon
        return None


def _make_point(state, utc, elapsed_ms, lat, lon, ehpe=None, satellites=None):
    return TrackPoint(
        utc=utc,
        elapsed_s=(elapsed_ms or 0) / 1000.0,
        lat=lat / 1e7,
        lon=lon / 1e7,
        alt_m=state.altitude,
        hr_bpm=state.hr,
        speed_kmh=state.speed,
        cadence_rpm=state.cadence,
        distance_m=state.distance,
        vertical_speed_ms=state.vspeed,
        temperature_c=state.temperature,
        ehpe_m=ehpe / 100.0 if ehpe is not None else None,
        satellites=satellites,
    )


def read_log(path, header_only=False):
    """
    Reads one openambit log file.

    :param path: Path of a ~/.openambit/log_*.log file
    :param header_only: Stop after the header, without reading the samples
    :return: AmbitLog
    :raises ValueError: If the file is not an openambit log
    """
    log = AmbitLog(path=path, log_id=log_id_from_path(path))
    state = _State()
    last_fix = None
    root_seen = False

    try:
        for event, elem in ET.iterparse(path, events=("start", "end")):
            if event == "start":
                if not root_seen:
                    if elem.tag != "openambitlog":
                        raise ValueError("{} is not an openambit log".format(path))
                    root_seen = True
                continue

            if elem.tag == "DeviceInfo":
                log.serial = _text(elem, "Serial", "") or ""
                log.model = _text(elem, "Model", "") or ""
                log.device_name = _text(elem, "Name", "") or ""
            elif elem.tag == "Header":
                _read_header(log, elem)
                elem.clear()
                if header_only:
                    break
            elif elem.tag == "Sample":
                kind = _text(elem, "Type")
                utc = _utc(_text(elem, "UTC"))
                elapsed = _int(elem, "Time", 0)
                if kind == "periodic":
                    fix = state.read_periodic(elem)
                    if fix and fix != (0, 0) and fix != last_fix:
                        log.points.append(_make_point(state, utc, elapsed, *fix))
                        last_fix = fix
                elif kind in POSITION_TYPES:
                    fix = (_int(elem, "Latitude"), _int(elem, "Longitude"))
                    valid = None not in fix and fix != (0, 0)
                    if kind == "gps-base" and valid and state.baro_alt is None:
                        gps_alt = _int(elem, "GPSAltitude")
                        if gps_alt is not None:
                            state.gps_alt = gps_alt / 100.0
                    # A "position" sample repeats the fix of the "gps-base" before it
                    if valid and fix != last_fix:
                        log.points.append(
                            _make_point(
                                state,
                                utc,
                                elapsed,
                                *fix,
                                _int(elem, "EHPE"),
                                _int(elem, "NumberOfSatellites"),
                            )
                        )
                        last_fix = fix
                elif kind == "lap-info":
                    lap = elem.find("Lap")
                    if lap is not None:
                        log.laps.append(
                            Lap(
                                kind=_text(lap, "Type", "") or "",
                                utc=utc,
                                elapsed_s=(elapsed or 0) / 1000.0,
                                duration_s=(_int(lap, "Duration", 0) or 0) / 1000.0,
                                distance_m=float(_int(lap, "Distance", 0) or 0),
                            )
                        )
                elem.clear()
    except ET.ParseError as e:
        raise ValueError("{} is not a readable openambit log: {}".format(path, e)) from e

    if not root_seen:
        raise ValueError("{} is empty".format(path))

    # Points logged before the first altitude take that altitude
    first_alt = next((p.alt_m for p in log.points if p.alt_m is not None), None)
    if first_alt is not None:
        for p in log.points:
            if p.alt_m is not None:
                break
            p.alt_m = first_alt
    return log


def find_logs(directory):
    """
    Lists the openambit log files of a directory, oldest first.

    The movescount/ sub-directory holds Movescount XML copies of the same
    moves and is not read.
    """
    if not os.path.isdir(directory):
        return []
    names = sorted(n for n in os.listdir(directory) if n.startswith("log_") and n.endswith(".log"))
    return [os.path.join(directory, n) for n in names]
