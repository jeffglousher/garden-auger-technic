"""Current direct-drive dimensions in millimeters.

The user-confirmed INJORA diagram controls the servo envelope. Printed fit
limits are acceptance requirements, not measured printer capability.
"""

PEG=14.0
SOCKET=14.4
PEG_RADIUS=1.0
SOCKET_RADIUS=1.2
SOCKET_DEPTH=12.0
PEG_TIP_Y=129.5
PEG_ROOT_Y=141.1
FLANGE_DIAMETER=28.0
FLANGE_THICKNESS=5.0
# Keep the installed shaft-tip datum independent of the flange thickness.
SERVO_TRANSLATION_Y=148.7
SERVO_SHIFT=SERVO_TRANSLATION_Y-141.3
SLEEVE_BODY=221
SLEEVE_FRONT=120.6
SLEEVE_REAR=131.0
SLEEVE_BORE=28.6
SLEEVE_OD=34.0
JOURNAL_DIAMETER=28.0
HOUSING_JOURNAL_DIAMETER=29.6
COLLAR_DIAMETER=34.0
COLLAR_FRONT=114.0
COLLAR_REAR=117.0
HOUSING_FRONT_STOP=113.7
HOUSING_REAR_STOP=117.3
HOUSING_RING_CAVITY=35.6
REAR_SCREW_Y=196.8
PRINT_SIZE_TOLERANCE=.10
MAX_DRIVE_AXIS_OFFSET=.50


def housing_profile():
    """Construction profile; nested_housing applies the final entrance taper."""
    return [(110.9,0),(110.9,14.8),(112.9,14.8),(113.7,15.6),
            (113.7,17.8),(117.3,17.8),(117.3,15.5),(118.5,14.8),
            (120.3,14.8),(120.3,17.8),(131.2,17.8),(131.2,14.8),
            (153,14.8),(153,0)]
