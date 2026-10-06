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
# Include transfer to the actual front chassis thrust face. The former
# +/-0.40 absolute-coordinate budget omitted that face's +/-0.10 allowance
# when it was presented as a measurement from the printed thrust face.
INSTALLED_ADAPTER_AXIAL_TOLERANCE=.50
REAR_ADAPTER_CHAMBER_END_Y=153.6


def square_fit_stack():
    """Conservative extrema stack; each named surface allowance counted once."""
    collar_shift=max(COLLAR_FRONT-HOUSING_FRONT_STOP,
                     HOUSING_REAR_STOP-COLLAR_REAR)+2*PRINT_SIZE_TOLERANCE
    socket_face=collar_shift+PRINT_SIZE_TOLERANCE
    peg_tip=INSTALLED_ADAPTER_AXIAL_TOLERANCE+PRINT_SIZE_TOLERANCE
    engagement=139.5-PEG_TIP_Y
    return {'required_flange_face_y':[PEG_ROOT_Y-INSTALLED_ADAPTER_AXIAL_TOLERANCE,
                                      PEG_ROOT_Y+INSTALLED_ADAPTER_AXIAL_TOLERANCE],
        'required_flange_face_from_front_chassis_thrust_stop':[
            PEG_ROOT_Y-HOUSING_FRONT_STOP-INSTALLED_ADAPTER_AXIAL_TOLERANCE,
            PEG_ROOT_Y-HOUSING_FRONT_STOP+INSTALLED_ADAPTER_AXIAL_TOLERANCE],
        'required_drive_axis_offset_max':MAX_DRIVE_AXIS_OFFSET,
        'engagement_min':engagement-socket_face-peg_tip,
        'engagement_max':engagement+socket_face+peg_tip,
        'tip_bottom_gap_min':PEG_TIP_Y-(139.5-SOCKET_DEPTH)-socket_face-peg_tip,
        'hub_flange_gap_min':PEG_ROOT_Y-139.5-socket_face-INSTALLED_ADAPTER_AXIAL_TOLERANCE,
        'auger_motion_extrema_mm':[-collar_shift,collar_shift],
        'socket_functional_face_location_allowance_mm':socket_face,
        'adapter_peg_tip_location_allowance_mm':peg_tip,
        'installed_adapter_axial_allowance_derivation':
            '0.20 nominal ear-face gap +0.10 ear-stop extrema +0.10 adapter seat-to-flange extrema +0.10 transfer to front chassis thrust face =0.50 mm',
        'coordinate_note':'World Y values locate the nominal CAD model. Inspect the installed flange from the actual front chassis thrust face; do not treat nominal world coordinates as a physical datum.',
        'relative_square_alignment':'Common axis offset from the housing is not relative peg/socket offset. Assemble coaxially and check free axial sliding over the engagement length.',
        'note':'Conditional on +/-0.10 mm critical printed functional-face extrema; nominal hardware dimensions follow the supplied drawing. Inspect finished surfaces and installed alignment.'}


def housing_profile():
    """Construction profile; nested_housing applies the final entrance taper."""
    return [(110.9,0),(110.9,14.8),(112.9,14.8),(113.7,15.6),
            (113.7,17.8),(117.3,17.8),(117.3,15.5),(118.5,14.8),
            (120.3,14.8),(120.3,17.8),(131.2,17.8),(131.2,14.8),
            (REAR_ADAPTER_CHAMBER_END_Y,14.8),(REAR_ADAPTER_CHAMBER_END_Y,0)]
