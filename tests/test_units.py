from ros2_interaction_lint import units


def rules(src, registry=None):
    return {f.rule for f in units.check_source(src, registry)}


def test_deg_into_rad_is_caught():
    assert "units.deg-into-rad" in rules("q_rad = angle_deg\n")


def test_converted_deg_is_not_flagged():
    assert "units.deg-into-rad" not in rules("import math\nq_rad = math.radians(angle_deg)\n")


def test_factor_token_conversion_clears_it():
    assert "units.deg-into-rad" not in rules("q_rad = angle_deg * DEG2RAD\n")


def test_reannotation_comment_clears_it():
    # the source is re-declared as rad on the assignment line
    src = "q_rad = compute()  # unit: rad\n"
    assert "units.deg-into-rad" not in rules(src)


def test_mm_into_m_is_caught():
    assert "units.mm-into-m" in rules("reach_m = span_mm\n")


def test_mm_plus_m_arithmetic_is_caught():
    assert "units.mixed-scale-arithmetic" in rules("total = x_mm + reach_m\n")


def test_division_by_1000_clears_mm_into_m():
    assert "units.mm-into-m" not in rules("reach_m = span_mm / 1000.0\n")


def test_dimension_mismatch_time_into_length():
    got = rules("dist_m = wait_s\n")
    assert "units.dimension-mismatch" in got


def test_jointstate_position_is_radians():
    # a deg-suffixed value into a field the registry knows is radians
    src = "js.position = angle_deg\n"
    # field key resolves via registry only when we can name the type; here the
    # attribute name 'position' alone maps through '*.position' if registered.
    r = rules(src, registry={"*.position": "rad"})
    assert "units.deg-into-rad" in r


def test_same_unit_is_silent():
    assert rules("q_rad = other_rad\n") == set()


def test_no_units_is_silent():
    assert rules("x = y + z\n") == set()


def test_syntax_error_is_info_not_crash():
    assert "units.parse-error" in rules("def (:\n")
