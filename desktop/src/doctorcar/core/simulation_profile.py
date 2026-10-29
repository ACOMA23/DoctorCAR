"""Public toy-model calibration, identical for normal and disturbed streams.

These relations describe DoctorCAR's demonstration generator, not vehicle specifications.
No schedule, injected identity, or latent fault parameter belongs in this module.
"""

PROFILE = "DOCTORCAR_CORRELATED_MODEL_1"


def expected_maf(rpm: float, load: float) -> float:
    return rpm * (0.002 + load * 0.00008)


def expected_map(load: float) -> float:
    return 30 + load * 0.65
