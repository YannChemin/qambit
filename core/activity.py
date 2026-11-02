"""
MODULE:    qambit.core.activity
AUTHOR(S): Yann Chemin
PURPOSE:   Groups activities by how they move through space (ground, water,
           air sports, vertical, underwater) and provides the air sports
           sport mode templates of openambit2.
SPDX-License-Identifier: Unlicense

"Air sports" is the FAI umbrella term for every flying discipline; "3D
activities" covers them plus the vertical and underwater ones. The rules are
those of openambit2's src/openambit/activitycategory.cpp, so both programs
classify a log the same way.
"""

import unicodedata

GROUND, WATER, AIR, VERTICAL, UNDERWATER = range(5)

# Suunto activity type of paragliding (0x5c), the only air sport the Ambit
# firmware knows; other foot-launched wings reuse it.
ACTIVITY_PARAGLIDING = 92
# "Unspecified sport" (0x01), used for aircraft the firmware has no type for.
ACTIVITY_UNSPECIFIED = 1

_AIR_WORDS = (
    "paraglid", "parapent", "gleitschirm", "parapendio",
    "hang glid", "hangegleit", "hanggleit", "deltaplan", "drachen",
    "speed fly", "speedfly", "speed rid", "speedrid",
    "paramot", "ppg",
    "glider", "gliding", "sailplane", "soaring", "planeur", "vol a voile",
    "segelflug", "volo a vela", "vuelo a vela", "velero",
    "ulm", "microlight", "ultralight", "ultraleger", "ultraleicht",
    "gyrocopt", "autogir", "autogyr", "tragschrauber",
    "helicopt", "helico", "heli ", "hubschrauber", "elicottero",
    "powered flight", "aeroplane", "airplane", "aircraft", "avion",
    "flugzeug", "aereo", "aviation", "flight", "flug", "vol moteur",
    "vol libre", "free flight",
    "balloon", "montgolf", "ballon", "mongolfiera", "globo",
    "skydiv", "parachut", "chute libre", "fallschirm", "paracaid", "paracadut",
    "wingsuit", "base jump",
)  # fmt: skip
_VERTICAL_WORDS = (
    "climb", "escalad", "klettern", "arrampic", "bloc", "boulder",
    "via ferrata", "klettersteig", "alpinis", "mountaineer", "bergsteig",
)  # fmt: skip
_UNDERWATER_WORDS = (
    "scuba", "dive", "diving", "plongee", "apnea", "apnee", "tauchen", "buceo", "immersion",
)  # fmt: skip
_WATER_WORDS = (
    "swim", "natation", "kayak", "canoe", "row", "aviron", "sail", "voile",
    "surf", "paddl", "stand up",
)  # fmt: skip
_WATER_TYPES = {0x06, 0x0D, 0x0E, 0x0F, 0x36, 0x48, 0x53, 0x56, 0x59, 0x5B}


def _fold(text):
    """Lower case without accents, so that "Hélicoptère" matches "helicopt"."""
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def classify(activity_type, name):
    """
    Classifies a log or sport mode.

    :param activity_type: Suunto activity type (log header or mode ActivityID)
    :param name: Activity or sport mode name, in any language
    :return: One of GROUND, WATER, AIR, VERTICAL, UNDERWATER
    """
    if activity_type == 0x5C:
        return AIR
    if activity_type in (0x10, 0x4A):  # Climbing, mountaineering
        return VERTICAL
    if activity_type in (0x33, 0x34, 0x35):  # Scuba, free diving, snorkeling
        return UNDERWATER

    # The trailing space lets short words such as "heli " match at the end;
    # the most specific kind is checked first ("vol a voile" before "voile").
    folded = _fold(name) + " "
    if any(w in folded for w in _AIR_WORDS):
        return AIR
    if any(w in folded for w in _UNDERWATER_WORDS):
        return UNDERWATER
    if any(w in folded for w in _VERTICAL_WORDS):
        return VERTICAL
    if activity_type in _WATER_TYPES or any(w in folded for w in _WATER_WORDS):
        return WATER
    return GROUND


def prefers_3d(kind):
    """Air sports are shown in 3D; climbing routes are too small for the DEMs."""
    return kind == AIR


def category_key(kind):
    """Stable, untranslated key of a kind, stored in the attribute tables."""
    return {
        WATER: "water",
        AIR: "air",
        VERTICAL: "vertical",
        UNDERWATER: "underwater",
    }.get(kind, "ground")


# Air sports templates: name, activity type, GPS interval (s), recording
# interval (s). Flying needs a dense track (thermal circles), and the
# altimeter is locked in Altitude mode (1) because FusedAlti would read climbs
# and descents as weather changes. Names fit the watch's 15 characters.
AIR_SPORT_PRESETS = (
    ("Paragliding", ACTIVITY_PARAGLIDING, 1, 1),
    ("Hang Gliding", ACTIVITY_PARAGLIDING, 1, 1),
    ("Speed Flying", ACTIVITY_PARAGLIDING, 1, 1),
    ("Paramotor", ACTIVITY_PARAGLIDING, 1, 1),
    ("Gliding", ACTIVITY_PARAGLIDING, 1, 1),
    ("Microlight ULM", ACTIVITY_UNSPECIFIED, 1, 1),
    ("Gyrocopter", ACTIVITY_UNSPECIFIED, 1, 1),
    ("Powered Flight", ACTIVITY_UNSPECIFIED, 1, 1),
    ("Helicopter", ACTIVITY_UNSPECIFIED, 1, 1),
    ("Balloon", ACTIVITY_UNSPECIFIED, 5, 5),
    ("Skydiving", ACTIVITY_UNSPECIFIED, 1, 1),
    ("Wingsuit", ACTIVITY_UNSPECIFIED, 1, 1),
)

WATCH_NAME_LENGTH = 15


def make_mode(
    name,
    activity_id,
    custom_mode_id,
    gps_interval=1,
    recording_interval=1,
    alti_baro_mode=0,
):
    """
    A sport mode in the format of ~/.openambit/sport_modes.json, the file the
    openambit2 editor and "openambit-cli --sport-modes" read.
    """
    return {
        "Name": name[:WATCH_NAME_LENGTH],
        "ActivityID": activity_id,
        "CustomModeID": custom_mode_id,
        "GPSInterval": gps_interval,
        "RecordingInterval": recording_interval,
        "AltiBaroMode": alti_baro_mode,
        "UseHRBelt": False,
        "UseFootPOD": False,
        "UseBikePOD": False,
        "UseCadencePOD": False,
        "UseAccelerometer": False,
        "UsePowerPOD": False,
        "UseAutolap": False,
        "AutolapDistance": 0,
        "HRLimitHigh": 180,
        "HRLimitLow": 120,
        "UseHRLimits": False,
        "AutoPauseSpeed": 0.0,
        "AutoScrolling": 0,
        "BacklightMode": 0,
        "DisplayIsNegative": 0,
        "ShowNavigationSelection": 0,
        "UseIntervals": False,
        "IntervalRepetitions": 0,
        "Interval1Time": 0,
        "Interval2Time": 0,
        "Interval1Distance": 0,
        "Interval2Distance": 0,
        "Displays": [],
        "DisplayedRuleIDs": [],
        "LoggedRuleIDs": [],
    }


# Suunto activity types, as named by openambit2 (src/movescount/movescountxml.cpp).
ACTIVITY_NAMES = {
    1: "Unspecified sport",
    2: "Multisport",
    3: "Running",
    4: "Cycling",
    5: "Mountain biking",
    6: "Pool swimming",
    8: "Roller skating",
    9: "Aerobics",
    10: "Yoga / pilates",
    11: "Trekking",
    12: "Walking",
    13: "Sailing",
    14: "Kayaking",
    15: "Rowing",
    16: "Climbing",
    17: "Indoor cycling",
    18: "Circuit training",
    19: "Triathlon",
    20: "Alpine skiing",
    21: "Snowboarding",
    22: "Cross-country skiing",
    23: "Weight training",
    24: "Basketball",
    25: "Soccer / football",
    26: "Ice Hockey",
    27: "Volleyball",
    28: "American football",
    29: "Softball",
    30: "Cheerleading",
    31: "Baseball",
    32: "UNDEFINED32",
    33: "Tennis",
    34: "Badminton",
    35: "Table tennis",
    36: "Racquet ball",
    37: "Squash",
    38: "Martial arts",
    39: "Boxing",
    40: "Floorball",
    41: "UNDEFINED41",
    42: "UNDEFINED42",
    43: "UNDEFINED43",
    44: "UNDEFINED44",
    45: "UNDEFINED45",
    46: "UNDEFINED46",
    47: "UNDEFINED47",
    48: "UNDEFINED48",
    49: "UNDEFINED49",
    50: "UNDEFINED50",
    51: "Scuba Diving",
    52: "Free Diving",
    53: "Snorkeling",
    54: "Surfing",
    55: "SwimRun",
    56: "Duathlon",
    57: "Aquathlon",
    58: "Obstacle racing",
    59: "UNDEFINED59",
    60: "UNDEFINED60",
    61: "Adventure racing",
    62: "Bowling",
    63: "Cricket",
    64: "Crosstrainer",
    65: "Dancing",
    66: "Golf",
    67: "Gymnastics",
    68: "Handball",
    69: "Horseback riding",
    70: "Ice skating",
    71: "Indoor rowing",
    72: "Canoeing",
    73: "Motorsports",
    74: "Mountaineering",
    75: "Orienteering",
    76: "Rugby",
    77: "UNDEFINED77",
    78: "Ski touring",
    79: "Stretching",
    80: "Telemark skiing",
    81: "Track and field",
    82: "Trail running",
    83: "Openwater swimming",
    84: "Nordic walking",
    85: "Snow shoeing",
    86: "Windsurfing/Surfing",
    87: "Kettlebell",
    88: "Roller skiing",
    89: "Standup paddling (SUP)",
    90: "Crosffit",
    91: "Kitesurfing/Kiting",
    92: "Paragliding",
    93: "Treadmill",
    94: "Frisbee",
    95: "Indoor training",
    96: "Hiking",
    97: "Fishing",
    98: "Hunting",
    99: "Transition",
    100: "Butterfly",
    101: "Backstroke",
    102: "Breaststroke",
    103: "Freestyle",
    104: "Drill",
}


def activity_name(activity_id):
    return ACTIVITY_NAMES.get(activity_id, "Activity {}".format(activity_id))
