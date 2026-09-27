"""gex_core squeeze score — desk formula unit tests."""
from edge.daily_plays.gex_core import compute_squeeze_score, directional_walls, near_spot_net_gex


def _score(**over):
    kw = dict(
        spot=100.0,
        call_wall=103.0,
        put_wall=90.0,
        flip=98.0,
        near_net=-50.0,
        net_dealer=-60.0,
        otm_call_weight=400.0,
        otm_put_weight=100.0,
        total_weight=1000.0,
        by_strike=[
            {"strike": 103.0, "call_gex": -30.0, "put_gex": 0.0},
            {"strike": 90.0, "call_gex": 0.0, "put_gex": -10.0},
        ],
        expected_move_pct=4.0,
        expected_move_low=96.0,
        expected_move_high=104.0,
    )
    kw.update(over)
    return compute_squeeze_score(**kw)


def test_bullish_setup_scores_bullish():
    out = _score()
    assert out["squeeze_score"] >= 20
    assert out["squeeze_label"] == "bullish_squeeze"


def test_positive_gex_is_dampened_not_erased():
    """Long gamma dampens final score but keeps structure for UI boards."""
    out = _score(near_net=50.0, net_dealer=60.0)
    assert out["squeeze_label"] == "neutral"
    assert out["long_gamma_dampened"] is True
    assert abs(out["squeeze_score"]) < 20
    # Structure still present so factor meters are not all-zero dead boards.
    structure = out["structure_components"]
    assert abs(structure["call_prox_score"]) > 0 or abs(structure["call_conc_score"]) > 0


def test_bearish_mirror_scores_bearish():
    out = _score(
        call_wall=110.0,
        put_wall=97.0,
        otm_call_weight=100.0,
        otm_put_weight=400.0,
        by_strike=[
            {"strike": 110.0, "call_gex": -10.0, "put_gex": 0.0},
            {"strike": 97.0, "call_gex": 0.0, "put_gex": -30.0},
        ],
    )
    assert out["squeeze_score"] <= -20
    assert out["squeeze_label"] == "bearish_squeeze"


def test_directional_walls_stay_on_correct_side():
    rows = [
        {"strike": 95.0, "call_gex_m": 50.0, "put_gex_m": -2.0},  # call mass below spot — wrong for resistance
        {"strike": 105.0, "call_gex_m": 10.0, "put_gex_m": 0.0},
        {"strike": 90.0, "call_gex_m": 0.0, "put_gex_m": -20.0},
    ]
    cw, pw = directional_walls(rows, spot=100.0, call_wall=95.0, put_wall=105.0)
    assert cw == 105.0
    assert pw == 90.0


def test_near_spot_net_gex_band():
    rows = [
        {"strike": 100.0, "net_gex_m": -5.0},
        {"strike": 120.0, "net_gex_m": -100.0},
    ]
    assert near_spot_net_gex(rows, spot=100.0, band_pct=0.05) == -5.0
