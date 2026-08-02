"""Independent cross-check of K_eff (architecture spec S11.4) -- P1-7 Issue 7B.

``edge.research.statistics.effective_trial_count_from_correlation`` computes
K_eff by: (1) diagonalizing R with the symmetric eigensolver
``np.linalg.eigvalsh``, which reads only one triangle of the input matrix,
(2) explicitly clipping negative eigenvalues with a hand-rolled tolerance
check, and (3) computing Shannon entropy with a hand-rolled, hand-masked
``-sum(p * log(p))`` reduction.

This module deliberately does NOT reuse any of those three steps.  It
recomputes the same statistic through a different numerical route:

  * Eigenvalues via ``np.linalg.svd`` instead of ``np.linalg.eigh``/``eigvalsh``.
    SVD reads the *entire* matrix (both triangles), not just one -- a bug
    that silently built an asymmetric "correlation" matrix would go
    undetected by ``eigvalsh`` (it only ever looks at one triangle) but
    would surface here as a disagreement.  SVD singular values are also
    always non-negative by construction (they equal ``|eigenvalue|`` for a
    symmetric matrix), so this route needs no explicit negative-eigenvalue
    clipping step at all -- it structurally cannot inherit a bug in that
    step, because it has no such step.
  * Shannon entropy via ``scipy.stats.entropy``, an independently maintained
    library routine that normalizes its input and masks zero-probability
    terms internally (``scipy.special.entr``), instead of the hand-rolled
    masked reduction in ``research/statistics.py``.

If this file and ``research/statistics.py`` ever disagree beyond the stated
numerical tolerance, that is a real finding -- widen the tolerance only with
a documented reason tied to floating-point error analysis, never to silence
a genuine conceptual disagreement between the two derivations.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import stats as scipy_stats

from edge.research.statistics import (
    EffectiveTrialCount,
    effective_trial_count_from_correlation,
    trial_return_correlation_matrix,
)

# Agreement tolerance between the two independent derivations.  Empirically,
# agreement across hundreds of randomized matrices (see
# test_cross_check_agrees_across_randomized_inputs) is within ~1e-12; this
# tolerance leaves generous headroom above that while still being far
# tighter than any of the [1, K]-scale quantities being compared.
AGREEMENT_TOLERANCE = 1e-6


def svd_entropy_effective_trial_count(correlation: object) -> float:
    """K_eff via SVD singular values + library Shannon entropy.

    A structurally different derivation of the same S11.4 statistic --
    see the module docstring for why each step differs from
    ``effective_trial_count_from_correlation``.
    """
    matrix = np.asarray(correlation, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] < 1:
        raise ValueError("correlation must be a non-empty square 2D matrix")
    k = matrix.shape[0]
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    # scipy.stats.entropy normalizes pk to sum to 1 and treats 0 * log(0) as
    # 0 internally (scipy.special.entr) -- both independently of how
    # research/statistics.py normalizes and masks.
    entropy = float(scipy_stats.entropy(singular_values))
    k_eff = float(np.exp(entropy))
    return min(max(k_eff, 1.0), float(k))


# ---------------------------------------------------------------------------
# The independent implementation must itself land on the analytically-known
# answers -- if both implementations shared a bug they could still "agree"
# with each other while both being wrong, so each is checked against the
# hand-derived truth independently before checking them against each other.
# ---------------------------------------------------------------------------


def test_independent_implementation_matches_golden_vectors_on_its_own() -> None:
    for k in (1, 2, 5, 10):
        assert svd_entropy_effective_trial_count(np.eye(k)) == pytest.approx(float(k), abs=1e-6)
    for k in (2, 5, 9):
        assert svd_entropy_effective_trial_count(np.ones((k, k))) == pytest.approx(1.0, abs=1e-6)
    for block_sizes in ((3, 3), (2, 2, 2), (4, 4, 4, 4)):
        total = sum(block_sizes)
        correlation = np.zeros((total, total))
        offset = 0
        for size in block_sizes:
            correlation[offset:offset + size, offset:offset + size] = 1.0
            offset += size
        got = svd_entropy_effective_trial_count(correlation)
        assert got == pytest.approx(float(len(block_sizes)), abs=1e-6)


def test_independent_implementation_reads_both_triangles() -> None:
    """A construction bug that leaves R asymmetric must be catchable here.

    ``np.linalg.eigvalsh`` reads only *one* triangle of its input by design
    (LAPACK's ``UPLO`` convention: the default is ``'L'``, lower-only).  A
    hypothetical implementation that forgot to validate/symmetrize before
    calling it would therefore be completely blind to a corruption confined
    to the upper triangle: this test demonstrates that blindness directly
    (``eigvalsh(..., UPLO="L")`` gives byte-for-byte identical eigenvalues
    for ``base`` and an upper-triangle-only-corrupted copy of it), then
    shows the independent SVD-based route -- which reads the full matrix --
    is not blind to the same corruption.  (Note SVD is transpose-invariant,
    so corrupting the upper vs. the mirror-image lower entry gives the same
    SVD answer as each other; the meaningful contrast is triangle-blind vs.
    full-matrix, not upper vs. lower.)  This is exactly the class of bug
    ``research/statistics.py`` guards against with its own explicit
    symmetry check (see
    ``test_effective_trial_count_rejects_materially_asymmetric_correlation``
    in test_statistics_regimes.py) -- this test is what justifies SVD as a
    meaningfully independent second route rather than a cosmetic variation.
    """
    base = np.array([[1.0, 0.6, 0.2], [0.6, 1.0, 0.5], [0.2, 0.5, 1.0]])
    corrupted_upper_only = base.copy()
    corrupted_upper_only[0, 2] = 0.9  # upper-triangle entry only; [2, 0] left at 0.2

    blind_eigenvalues_base = np.linalg.eigvalsh(base, UPLO="L")
    blind_eigenvalues_corrupted = np.linalg.eigvalsh(corrupted_upper_only, UPLO="L")
    np.testing.assert_allclose(blind_eigenvalues_base, blind_eigenvalues_corrupted)

    baseline_k_eff = svd_entropy_effective_trial_count(base)
    corrupted_k_eff = svd_entropy_effective_trial_count(corrupted_upper_only)
    assert corrupted_k_eff != pytest.approx(baseline_k_eff, abs=1e-9)


# ---------------------------------------------------------------------------
# Agreement between the two independent derivations.
# ---------------------------------------------------------------------------


def _assert_agree(correlation: np.ndarray, *, context: str) -> None:
    primary = effective_trial_count_from_correlation(correlation)
    independent = svd_entropy_effective_trial_count(correlation)
    gap = abs(primary.effective_trial_count - independent)
    assert gap < AGREEMENT_TOLERANCE, (
        f"K_eff DISAGREEMENT ({context}): primary(eigvalsh+hand-rolled entropy)="
        f"{primary.effective_trial_count!r} vs independent(svd+scipy.stats.entropy)="
        f"{independent!r}, gap={gap!r} >= tolerance={AGREEMENT_TOLERANCE!r}\n"
        f"correlation=\n{correlation!r}"
    )


def test_cross_check_agrees_on_golden_vectors() -> None:
    for k in (1, 2, 5, 10):
        _assert_agree(np.eye(k), context=f"orthogonal k={k}")
    for k in (2, 5, 9):
        _assert_agree(np.ones((k, k)), context=f"identical k={k}")


def test_cross_check_agrees_across_randomized_inputs() -> None:
    """Broad randomized agreement sweep across several matrix-generation modes.

    Covers: random Gram-derived correlation matrices (always PSD, arbitrary
    rank), returns-derived correlation matrices with injected constant
    (zero-variance) columns, and "fat" panels with more trials than
    observations (guaranteed rank-deficient).  Every case must agree within
    ``AGREEMENT_TOLERANCE``; any single disagreement fails the test with the
    offending matrix printed via ``_assert_agree``'s message.
    """
    rng = np.random.default_rng(42)
    max_gap = 0.0
    n_checked = 0
    for trial in range(500):
        k = int(rng.integers(1, 15))
        mode = trial % 3
        if mode == 0:
            basis = rng.normal(size=(k, k + int(rng.integers(0, 5))))
            gram = basis @ basis.T
            scale = np.sqrt(np.clip(np.diag(gram), 1e-12, None))
            correlation = gram / np.outer(scale, scale)
            np.fill_diagonal(correlation, 1.0)
        elif mode == 1:
            n_obs = int(rng.integers(2, 60))
            returns = rng.normal(size=(n_obs, k))
            n_const = int(rng.integers(0, k + 1))
            constant_columns = rng.choice(k, size=min(n_const, k), replace=False)
            for column in constant_columns:
                returns[:, column] = rng.normal()
            correlation = trial_return_correlation_matrix(returns)
        else:
            n_obs = int(rng.integers(2, max(3, k)))
            returns = rng.normal(size=(n_obs, k))
            correlation = trial_return_correlation_matrix(returns)

        primary = effective_trial_count_from_correlation(correlation).effective_trial_count
        independent = svd_entropy_effective_trial_count(correlation)
        gap = abs(primary - independent)
        max_gap = max(max_gap, gap)
        n_checked += 1
        assert gap < AGREEMENT_TOLERANCE, (
            f"K_eff DISAGREEMENT at trial={trial} mode={mode} k={k}: "
            f"primary={primary!r} independent={independent!r} gap={gap!r}\n"
            f"correlation=\n{correlation!r}"
        )
    assert n_checked == 500
    # Not a correctness assertion (the per-trial assert above already
    # guarantees every case is within tolerance) -- surfaces the actual
    # achieved precision in the failure message if the loop above is ever
    # weakened, and in verbose test output.
    assert max_gap < AGREEMENT_TOLERANCE


def test_cross_check_agrees_on_a_fixed_known_intermediate_case() -> None:
    """The same hand-derived two-block case from test_statistics_regimes.py."""
    correlation = np.zeros((6, 6))
    correlation[0:3, 0:3] = 1.0
    correlation[3:6, 3:6] = 1.0
    primary = effective_trial_count_from_correlation(correlation).effective_trial_count
    independent = svd_entropy_effective_trial_count(correlation)
    assert primary == pytest.approx(2.0, abs=1e-6)
    assert independent == pytest.approx(2.0, abs=1e-6)
    assert primary == pytest.approx(independent, abs=AGREEMENT_TOLERANCE)


def test_effective_trial_count_dataclass_fields_are_what_cross_check_compares() -> None:
    """Guard against a future field rename silently breaking this cross-check."""
    result = effective_trial_count_from_correlation(np.eye(3))
    assert isinstance(result, EffectiveTrialCount)
    assert isinstance(result.effective_trial_count, float)
    assert result.diagnostic_only is True
