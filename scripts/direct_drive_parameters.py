"""Direct press-fit prototype: millimeters; fit dimensions require inspection."""
PILOT_DIAMETER=5.70
PILOT_TRIAL_DIAMETERS=[5.60,5.70,5.80,5.90]
SHAFT_TIP_SEAT_Y=148.70
# Hitec's H25T manufacturer drawing specifies 3.70 mm horn spline depth
# (2026 horn/spline technical data sheet, printed page 75). This is the
# selected family reference, not an INJORA-published axial shaft dimension.
PILOT_DEPTH=3.70
PILOT_REAR_Y=SHAFT_TIP_SEAT_Y+PILOT_DEPTH
PILOT_LEAD_IN=.15
BOSS_DIAMETER=24.0
BOSS_ROOT_Y=146.0
BOSS_TRANSITION_END_Y=148.0
CASE_FACE_REFERENCE_Y=SHAFT_TIP_SEAT_Y+4.0
MIN_STATIONARY_CLEARANCE=.20
H25T_DEPTH_SOURCE='https://shop.multiplex-rc.de/userdata/files/HITEC%20SERVO%20ACTUATOR%20HORN%20%26%20SPLINE%20TECHNICAL%20DATA%20SHEET_v3_0_1_26C.pdf'
HEAD_SEAT_Y=146.10
SCREW_CLEARANCE=3.40
HEAD_ACCESS=6.40
UNDERHEAD_RELIEF_DIAMETER=4.00
UNDERHEAD_RELIEF_DEPTH=.30
SCREW_TRIAL_LENGTH=6.00
SCREW_MEASURED_LENGTH_RANGE=[5.90,6.10]
SEAT_TO_TIP_ACCEPTANCE=[2.40,2.80]
USABLE_THREAD_DEPTH_MIN=4.00
PRINT_TOLERANCE=.10
REQUIRED_EXPOSED_SHAFT_MIN=PILOT_DEPTH+PRINT_TOLERANCE+MIN_STATIONARY_CLEARANCE


def pilot_profile(diameter=PILOT_DIAMETER,front=SHAFT_TIP_SEAT_Y,depth=PILOT_DEPTH):
    rear=front+depth
    return [(front,0),(front,diameter/2),
            (rear-PILOT_LEAD_IN,diameter/2),
            (rear,diameter/2+PILOT_LEAD_IN),
            (rear+.05,diameter/2+PILOT_LEAD_IN),(rear+.05,0)]


def screw_stack():
    nominal_seat=SHAFT_TIP_SEAT_Y-HEAD_SEAT_Y
    engagement=SCREW_TRIAL_LENGTH-nominal_seat
    engagement_min=SCREW_MEASURED_LENGTH_RANGE[0]-SEAT_TO_TIP_ACCEPTANCE[1]
    engagement_max=SCREW_MEASURED_LENGTH_RANGE[1]-SEAT_TO_TIP_ACCEPTANCE[0]
    return {'screw':'M3 x 6 ISO4762/DIN912 envelope, full thread; verify factory thread compatibility',
        'nominal_length_under_head_mm':SCREW_TRIAL_LENGTH,
        'length_acceptance_measured_mm':SCREW_MEASURED_LENGTH_RANGE,
        'seat_to_tip_nominal_mm':nominal_seat,
        'seat_to_tip_acceptance_mm':SEAT_TO_TIP_ACCEPTANCE,
        'nominal_thread_entry_length_mm':engagement,
        'thread_entry_length_min_mm':engagement_min,
        'thread_entry_length_max_mm':engagement_max,
        'required_usable_thread_depth_mm':USABLE_THREAD_DEPTH_MIN,
        'nominal_bottom_room_if_usable_depth_4_mm':USABLE_THREAD_DEPTH_MIN-engagement,
        'minimum_bottom_room_if_inspections_pass_mm':USABLE_THREAD_DEPTH_MIN-engagement_max,
        'head_envelope_diameter_mm':5.5,'head_envelope_height_mm':3.0,
        'head_access_diameter_mm':HEAD_ACCESS,
        'head_radial_clearance_nominal_mm':(HEAD_ACCESS-5.5)/2,
        'head_radial_clearance_min_with_print_allowance_mm':(HEAD_ACCESS-PRINT_TOLERANCE-5.5)/2,
        'shaft_passage_diameter_mm':SCREW_CLEARANCE,
        'shaft_radial_clearance_nominal_mm':(SCREW_CLEARANCE-3)/2,
        'shaft_radial_clearance_min_with_print_allowance_mm':(SCREW_CLEARANCE-PRINT_TOLERANCE-3)/2,
        'underhead_relief_diameter_mm':UNDERHEAD_RELIEF_DIAMETER,
        'underhead_relief_depth_mm':UNDERHEAD_RELIEF_DEPTH,
        'limitation':'Thread entry length is not a guarantee of full-thread engagement. INJORA does not publish entry chamfer, thread depth or factory screw length; inspect actual screw and usable thread.'}
