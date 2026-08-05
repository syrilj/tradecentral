"""Bayesian Online Changepoint Detection (Adams & MacKay 2007, arXiv:0710.3742).

Implements the paper's Algorithm 1 exactly (steps 1-8, PDF page 3): a causal,
online estimate of the run-length posterior P(r_t | x_1:t), where r_t is the
number of observations since the last regime break. The recursion (eq. 3) is
kept separate from the observation model (eq. 2, conjugate-exponential §2.3)
because §4 of the paper explicitly calls for "an object-oriented, 'pluggable'
type architecture" -- `bocpd()` only ever talks to an `ObservationModel`
through `log_pred_prob` / `update` / `prune` / `pred_mean` / `pred_var`, so a
new conjugate family can be dropped in without touching the recursion.

Why this file exists: BOCPD is the closest thing to a principled answer to
"did the regime for this symbol just change" that doesn't require picking an
arbitrary lookback window. §3.2 of the paper runs exactly our use case --
DJIA daily returns, zero-mean Gaussian with piecewise-constant variance,
Gamma(a=1, b=1e-4) prior on the precision, hazard 1/250 -- which is why
`GaussianVarianceModel`'s defaults and `changepoints_from_prices` mirror it.

Two correctness traps this implementation deliberately guards against:
  1. Underflow: P(r_t, x_1:t) shrinks geometrically with t if computed in
     linear space, so everything here is done in log space with log-sum-exp.
  2. Run-length identity after truncation (§2.4): pruning drops whichever
     hypotheses currently carry the least posterior mass (see
     `_truncation_mask`), which is *not* always the largest-run-length end --
     in a stationary regime mass concentrates near the largest live run
     length and thins out toward 0, so the prunable tail is usually at the
     *small*-r end. Because pruning can therefore remove hypotheses from the
     middle of the array, `bocpd()` tracks each row's true run length in an
     explicit label array rather than assuming array position == run length;
     nothing is ever silently reindexed.

One property worth knowing before staring at `cp_prob` output: under a
CONSTANT hazard (`ConstantHazard`, i.e. H(tau) the same for every run
length), P(r_t = 0 | x_1:t) is provably equal to H at *every* bar,
independent of the data. This falls straight out of eq. 3-4: the same
pi_t^(r) predictive appears in both the "grow" and "reset" branches for a
given r_{t-1}, weighted only by (1-H) and H respectively, so those weights
factor out of both the numerator and the evidence and cancel exactly. What
*does* respond to the data under a constant hazard is how the growth mass
(1-H) redistributes across run lengths. `BocpdResult` exposes this as
`cp_prob_raw` (kept only as an implementation self-check -- assert it equals
the hazard rate) plus the actually-useful `break_prob` / `break_prob_20` /
`run_length_cdf(k)`, which are P(r_t <= k | x_1:t) for small k and DO
separate cleanly between stable and just-broken regimes. See
`tests/research/test_bocpd.py` for a standalone numerical confirmation of
the cp_prob_raw identity.

A second, unrelated pitfall: the paper's own default prior (a=1, so
dof=2*a=2) makes the Student-t predictive variance of the freshly-reset r=0
hypothesis genuinely undefined (infinite) -- see `pred_var` on both
observation models and `pred_var_defined_mass` below. Flooring that infinity
into a finite number produces a smooth-looking but fabricated constant that
never reflects the data; the correct handling is to exclude that hypothesis
from the eq. 1 variance mixture (renormalizing over what remains) rather
than disguise it.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

def _lgamma(x: np.ndarray) -> np.ndarray:
    """Vectorised log-gamma via the stdlib (no scipy dependency)."""
    return np.frompyfunc(math.lgamma, 1, 1)(x).astype(float)


def _student_t_logpdf(x: float, dof: np.ndarray, loc: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """log-density of a location-scale Student-t, elementwise, scipy-free.

    f(x) = Gamma((v+1)/2) / (Gamma(v/2) sqrt(v*pi) * s) * (1 + z^2/v)^(-(v+1)/2),
    z = (x - loc) / s. Used for both observation models' posterior predictive
    (paper §2.3: the Gaussian/NIG conjugate predictive is always Student-t).
    """
    z = (x - loc) / scale
    return (
        _lgamma(0.5 * (dof + 1.0))
        - _lgamma(0.5 * dof)
        - 0.5 * np.log(dof * np.pi)
        - np.log(scale)
        - 0.5 * (dof + 1.0) * np.log1p(z * z / dof)
    )


def _log_sum_exp(values: np.ndarray) -> float:
    """Numerically stable log(sum(exp(values))) for a 1D array."""
    peak = float(np.max(values))
    if not np.isfinite(peak):
        # Every entry is -inf (degenerate / impossible evidence); propagate
        # rather than producing NaN from log(0) - (-inf).
        return peak
    return peak + float(np.log(np.sum(np.exp(values - peak))))


# ---------------------------------------------------------------------------
# Observation models (paper §2.3, conjugate-exponential)
# ---------------------------------------------------------------------------


class ObservationModel(ABC):
    """A conjugate-exponential observation model over live run-length hypotheses.

    Holds vectorised sufficient statistics, one row per currently-live run
    length. `bocpd()` never inspects those statistics directly -- it only
    calls the five methods below -- so alternative conjugate families are a
    drop-in replacement (paper §4's "pluggable" architecture).

    Invariant every implementation MUST preserve: `prune` may only ever
    *remove* rows (via a boolean mask, `self.a = self.a[keep]` style); it must
    never reorder or renumber the survivors. `bocpd()` tracks the true
    run-length label of every row itself, externally, in lockstep with the
    exact same boolean mask -- that only stays correct if a model's rows
    survive pruning in their original relative order.
    """

    @property
    @abstractmethod
    def n_runs(self) -> int:
        """Number of live run-length hypotheses currently tracked."""

    @abstractmethod
    def log_pred_prob(self, x: float) -> np.ndarray:
        """log pi_t^(r) (paper step 3): log P(x_t | current sufficient stats)
        for every live run r, using statistics accumulated *before* this
        observation (i.e. from the data seen since that run's changepoint,
        not including x_t)."""

    @abstractmethod
    def update(self, x: float) -> None:
        """Grow sufficient statistics with x_t (paper step 8): update every
        existing row (its run has one more observation) and prepend a fresh
        prior row -- the r=0 hypothesis for the *next* bar, i.e. "a break
        happens right before the next observation"."""

    @abstractmethod
    def prune(self, keep: np.ndarray) -> None:
        """§2.4 truncation: keep only the rows where `keep` (boolean mask,
        same length as the current live-run arrays) is True."""

    @abstractmethod
    def pred_mean(self) -> np.ndarray:
        """Per-run predictive mean, for mixing into the eq. 1 marginal."""

    @abstractmethod
    def pred_var(self) -> np.ndarray:
        """Per-run predictive variance, for mixing into the eq. 1 marginal via
        the law of total variance (Var[X] = E[Var[X|r]] + Var[E[X|r]])."""


class GaussianVarianceModel(ObservationModel):
    """Zero-mean Gaussian, Gamma(a, b) prior on the precision (paper §3.2).

    This is the paper's own DJIA setup and our default: x_t | tau ~ N(0, 1/tau),
    tau ~ Gamma(shape=a, rate=b). The posterior predictive is a Student-t with
    2a degrees of freedom, scale sqrt(b/a), centred at 0. Conjugate update on
    observing x: a += 1/2, b += x^2/2 (standard Gaussian-Gamma conjugacy for a
    known-mean-zero likelihood).
    """

    def __init__(self, a: float = 1.0, b: float = 1e-4) -> None:
        if not (np.isfinite(a) and a > 0.0):
            raise ValueError("a (Gamma shape prior) must be finite and positive")
        if not (np.isfinite(b) and b > 0.0):
            raise ValueError("b (Gamma rate prior) must be finite and positive")
        self.a0 = float(a)
        self.b0 = float(b)
        self.a = np.array([self.a0], dtype=float)
        self.b = np.array([self.b0], dtype=float)

    @property
    def n_runs(self) -> int:
        return int(self.a.shape[0])

    def log_pred_prob(self, x: float) -> np.ndarray:
        dof = 2.0 * self.a
        scale = np.sqrt(self.b / self.a)
        return _student_t_logpdf(x, dof=dof, loc=0.0, scale=scale)

    def update(self, x: float) -> None:
        self.a = np.concatenate(([self.a0], self.a + 0.5))
        self.b = np.concatenate(([self.b0], self.b + 0.5 * x * x))

    def prune(self, keep: np.ndarray) -> None:
        self.a = self.a[keep]
        self.b = self.b[keep]

    def pred_mean(self) -> np.ndarray:
        return np.zeros_like(self.a)

    def pred_var(self) -> np.ndarray:
        """Var[Student-t(v=2a, scale^2=b/a)] = (b/a)*(2a)/(2a-2) = b/(a-1), a>1.

        At a<=1 (dof<=2) -- the freshly-reset r=0 row under the paper's own
        a0=1 default -- this variance is genuinely undefined, returned as
        +inf rather than a fabricated finite number (see module docstring).
        `bocpd()` excludes non-finite rows from the eq. 1 mixture instead of
        flooring them.
        """
        denom = self.a - 1.0
        var = np.full(self.a.shape, np.inf, dtype=float)
        defined = denom > 0.0
        var[defined] = self.b[defined] / denom[defined]
        return var


class StudentTModel(ObservationModel):
    """Normal-Inverse-Gamma prior on unknown mean AND variance (paper §3.1
    well-log style mean-shift case): mu, sigma^2 ~ NIG(mu0, kappa, alpha, beta).

    Posterior predictive is Student-t with 2*alpha degrees of freedom,
    location mu, scale sqrt(beta*(kappa+1)/(alpha*kappa)). Standard NIG
    conjugate update for a single new observation x:
      kappa' = kappa + 1
      mu'    = (kappa*mu + x) / kappa'
      alpha' = alpha + 1/2
      beta'  = beta + kappa*(x-mu)^2 / (2*kappa')
    """

    def __init__(self, mu: float = 0.0, kappa: float = 1.0, alpha: float = 1.0, beta: float = 1.0) -> None:
        if not np.isfinite(mu):
            raise ValueError("mu prior must be finite")
        if not (np.isfinite(kappa) and kappa > 0.0):
            raise ValueError("kappa (NIG pseudo-count prior) must be finite and positive")
        if not (np.isfinite(alpha) and alpha > 0.0):
            raise ValueError("alpha (Inverse-Gamma shape prior) must be finite and positive")
        if not (np.isfinite(beta) and beta > 0.0):
            raise ValueError("beta (Inverse-Gamma scale prior) must be finite and positive")
        self.mu0 = float(mu)
        self.kappa0 = float(kappa)
        self.alpha0 = float(alpha)
        self.beta0 = float(beta)
        self.mu = np.array([self.mu0], dtype=float)
        self.kappa = np.array([self.kappa0], dtype=float)
        self.alpha = np.array([self.alpha0], dtype=float)
        self.beta = np.array([self.beta0], dtype=float)

    @property
    def n_runs(self) -> int:
        return int(self.mu.shape[0])

    def log_pred_prob(self, x: float) -> np.ndarray:
        dof = 2.0 * self.alpha
        scale = np.sqrt(self.beta * (self.kappa + 1.0) / (self.alpha * self.kappa))
        return _student_t_logpdf(x, dof=dof, loc=self.mu, scale=scale)

    def update(self, x: float) -> None:
        kappa_new = self.kappa + 1.0
        mu_new = (self.kappa * self.mu + x) / kappa_new
        beta_new = self.beta + (self.kappa * (x - self.mu) ** 2) / (2.0 * kappa_new)
        alpha_new = self.alpha + 0.5
        self.mu = np.concatenate(([self.mu0], mu_new))
        self.kappa = np.concatenate(([self.kappa0], kappa_new))
        self.alpha = np.concatenate(([self.alpha0], alpha_new))
        self.beta = np.concatenate(([self.beta0], beta_new))

    def prune(self, keep: np.ndarray) -> None:
        self.mu = self.mu[keep]
        self.kappa = self.kappa[keep]
        self.alpha = self.alpha[keep]
        self.beta = self.beta[keep]

    def pred_mean(self) -> np.ndarray:
        return self.mu.copy()

    def pred_var(self) -> np.ndarray:
        """Var[Student-t(v=2*alpha, ...)] = beta*(kappa+1)/(kappa*(alpha-1)), alpha>1.

        Undefined (dof<=2) at alpha<=1, returned as +inf -- see
        GaussianVarianceModel.pred_var for why this is not floored.
        """
        denom = self.alpha - 1.0
        var = np.full(self.alpha.shape, np.inf, dtype=float)
        defined = denom > 0.0
        var[defined] = (self.beta[defined] * (self.kappa[defined] + 1.0)) / (self.kappa[defined] * denom[defined])
        return var


# ---------------------------------------------------------------------------
# Hazard (paper eq. 5)
# ---------------------------------------------------------------------------


class ConstantHazard:
    """Geometric gap prior: H(tau) = 1 / lambda_gap for every run length (eq. 5).

    Kept as a small callable object -- rather than a bare constant -- so a
    non-constant hazard (e.g. run-length-dependent) can be substituted later
    without changing `bocpd()`, per the paper's §4 pluggable-architecture goal.
    """

    def __init__(self, lambda_gap: float = 250.0) -> None:
        if not np.isfinite(lambda_gap) or lambda_gap <= 1.0:
            raise ValueError("lambda_gap must be finite and greater than 1")
        self.lambda_gap = float(lambda_gap)
        self._h = 1.0 / self.lambda_gap

    def __call__(self, run_lengths: np.ndarray) -> np.ndarray:
        """H(tau) for each tau in `run_lengths`; constant here, but the
        interface takes the run-length vector so future hazards can vary by
        run length without touching the caller."""
        run_lengths = np.asarray(run_lengths, dtype=float)
        return np.full(run_lengths.shape, self._h, dtype=float)


# ---------------------------------------------------------------------------
# §2.4 truncation
# ---------------------------------------------------------------------------


def _truncation_mask(log_posterior: np.ndarray, truncation_mass: float) -> np.ndarray:
    """§2.4 pruning: drop whichever run-length hypotheses currently carry the
    least posterior mass, as long as their COMBINED dropped mass stays below
    `truncation_mass`, for constant average per-step cost.

    Deliberately NOT "drop the largest-run-length suffix": in the common
    steady-state case (an established run with no break), probability mass
    concentrates near the *largest* live run length (it tracks elapsed time)
    and decays toward run length 0, so the negligible tail sits at the
    *small*-r end. Right after a genuine break the opposite can be true. The
    only robust rule is to rank by actual posterior probability, wherever it
    is in the array, and drop the least-probable hypotheses first.

    This can drop hypotheses from the middle of the array, not just one end,
    which is exactly why `bocpd()` tracks each row's true run length in an
    explicit label array rather than assuming array position == run length.

    Position 0 (the freshly-prepended r=0 "a break just happened" row) is
    always protected, so a break can always register.
    """
    n = log_posterior.shape[0]
    if truncation_mass <= 0.0 or n <= 1:
        return np.ones(n, dtype=bool)
    probs = np.exp(log_posterior)
    order = np.argsort(probs, kind="stable")  # ascending: least-probable first
    cumulative_dropped = np.cumsum(probs[order])
    drop_in_rank_order = cumulative_dropped < truncation_mass
    mask = np.ones(n, dtype=bool)
    mask[order[drop_in_rank_order]] = False
    mask[0] = True
    return mask


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BocpdResult:
    """Output of `bocpd()`. Every array has length T (one entry per input bar)
    and entry t is a pure function of x_1..x_t -- nothing here ever looks
    ahead.
    """

    cp_prob_raw: np.ndarray
    """P(r_t = 0 | x_1:t) per bar. Kept only as an implementation self-check:
    under a constant hazard this is IDENTICALLY the hazard rate H =
    1/lambda_gap at every bar, independent of the data (see module
    docstring for the derivation) -- it carries zero information about
    whether a break actually happened. Never use this as a detection signal;
    use `break_prob` / `break_prob_20` / `run_length_cdf(k)` instead."""

    break_prob: np.ndarray
    """P(r_t <= 5 | x_1:t) per bar: posterior probability that a changepoint
    occurred within the last 5 bars. Unlike `cp_prob_raw`, this genuinely
    responds to the data -- it collapses toward 0 in a stable regime and
    shoots toward 1 within a few bars of a real break, because it is a
    property of how the (1-H) growth mass redistributes across run lengths,
    not of the data-independent grow/reset split itself."""

    break_prob_20: np.ndarray
    """P(r_t <= 20 | x_1:t) per bar -- same idea as `break_prob` with a wider
    lookback, useful as a slower/less noisy companion signal."""

    map_run_length: np.ndarray
    """argmax_r P(r_t = r | x_1:t) per bar -- the single most likely number of
    bars since the last break (true run length, not a pruned-array index)."""

    expected_run_length: np.ndarray
    """Sum_r r * P(r_t = r | x_1:t) per bar."""

    pred_mean: np.ndarray
    """Mean of the eq. 1 marginal predictive for x_{t+1}, mixing each live
    run's predictive mean by the run-length posterior at bar t."""

    pred_std: np.ndarray
    """Std of the eq. 1 marginal predictive for x_{t+1}. This is the standard
    deviation of the *mixture* (law of total variance: E[Var] + Var[E]), not
    the posterior-weighted average of the per-run standard deviations -- the
    two differ whenever the per-run predictive means disagree, e.g. right
    after a genuine break.

    The freshly-reset r=0 hypothesis has a genuinely undefined (infinite)
    predictive variance under the paper's own a0=1 default (dof=2*a=2, see
    `GaussianVarianceModel.pred_var`), so it is excluded from this mixture
    and the remaining posterior mass is renormalized -- see
    `pred_var_defined_mass`. NaN at any bar where that excluded mass is the
    entire posterior (nothing left to mix)."""

    pred_var_defined_mass: np.ndarray
    """Posterior mass retained after excluding the undefined-variance r=0 row
    from the `pred_std` mixture at each bar (typically close to 1 -- P(r=0)
    is just the hazard rate). Lets a caller see how much was excluded."""

    run_length_posteriors: list[tuple[np.ndarray, np.ndarray]] = field(repr=False)
    """Internal: one (labels, probs) pair per bar, where `labels[i]` is the
    TRUE run length of hypothesis i and `probs[i]` its posterior mass --
    labels are not necessarily contiguous or position-aligned once §2.4
    pruning has dropped hypotheses out of the middle of the array. Use
    `run_length_posterior()` / `run_length_cdf()` instead of touching this
    directly."""

    @property
    def n_bars(self) -> int:
        return int(self.cp_prob_raw.shape[0])

    def run_length_cdf(self, k: int) -> np.ndarray:
        """P(r_t <= k | x_1:t) per bar -- the general form behind `break_prob`
        (k=5) and `break_prob_20` (k=20). Unlike the raw r=0 probability,
        this is a genuine, data-responsive break-detection statistic: it
        aggregates the posterior mass of "a break happened within the last k
        bars", which is exactly what shifts when the (1-H) growth mass
        redistributes toward small run lengths after a real regime change.
        """
        if k < 0:
            raise ValueError("k must be non-negative")
        out = np.empty(self.n_bars, dtype=float)
        for t, (labels, probs) in enumerate(self.run_length_posteriors):
            out[t] = float(np.sum(probs[labels <= k]))
        return out

    def run_length_posterior(self, max_run: int | None = None) -> np.ndarray:
        """Dense (max_run+1) x T matrix of P(run_length=row | x_1:col).

        Rows are run length, columns are time (bar index), matching the
        paper's Fig. 3 bottom panel. Zero-filled wherever a hypothesis was
        pruned away (§2.4) or is structurally impossible (row > col, since
        run length can never exceed bars elapsed). Scatters by each
        hypothesis's true label rather than its array position, since
        truncation can drop hypotheses out of the middle of the array.
        """
        if max_run is not None and max_run < 0:
            raise ValueError("max_run must be non-negative")
        t_cols = len(self.run_length_posteriors)
        observed_max = 0
        for labels, _probs in self.run_length_posteriors:
            if labels.size:
                observed_max = max(observed_max, int(labels.max()))
        rows = observed_max if max_run is None else max_run
        matrix = np.zeros((rows + 1, t_cols), dtype=float)
        for col, (labels, probs) in enumerate(self.run_length_posteriors):
            visible = labels <= rows
            matrix[labels[visible], col] = probs[visible]
        return matrix


# ---------------------------------------------------------------------------
# The recursion (paper Algorithm 1, steps 1-8)
# ---------------------------------------------------------------------------


def _validate_series(x: np.ndarray | pd.Series) -> np.ndarray:
    values = x.to_numpy(dtype=float) if isinstance(x, pd.Series) else np.asarray(x, dtype=float)
    if values.ndim != 1:
        raise ValueError("x must be one-dimensional")
    if values.size == 0:
        raise ValueError("x must contain at least one observation")
    if not np.isfinite(values).all():
        raise ValueError("x must not contain NaN or infinite values")
    return values


def bocpd(
    x: np.ndarray | pd.Series,
    model: ObservationModel,
    hazard: ConstantHazard,
    *,
    truncation_mass: float = 1e-4,
) -> BocpdResult:
    """Adams & MacKay (2007) Algorithm 1, arXiv:0710.3742 PDF p.3, steps 1-8.

    Runs in log space throughout for P(r_t, x_1:t): a several-hundred-bar
    series computed in linear space underflows the joint to exactly zero,
    which is the single most common way a BOCPD port silently returns
    garbage. `model` and `hazard` are the two pluggable pieces (paper §4);
    `model` must be freshly constructed (a single live run, matching
    P(r_0=0)=1) since this function mutates it in place while it runs.

    Causal by construction: bar t's posterior depends only on x_1..x_t and
    the state folded forward from bar t-1. No future data is ever read.
    """
    values = _validate_series(x)
    if not (0.0 <= truncation_mass < 1.0):
        raise ValueError("truncation_mass must be in [0, 1)")
    if model.n_runs != 1:
        raise ValueError(
            "model must be freshly constructed (exactly one live run, matching "
            "P(r_0=0)=1) before calling bocpd() -- it is mutated in place"
        )

    n = values.shape[0]
    cp_prob_raw = np.empty(n, dtype=float)
    break_prob = np.empty(n, dtype=float)
    break_prob_20 = np.empty(n, dtype=float)
    map_run_length = np.empty(n, dtype=np.int64)
    expected_run_length = np.empty(n, dtype=float)
    pred_mean_out = np.empty(n, dtype=float)
    pred_std_out = np.empty(n, dtype=float)
    pred_var_defined_mass_out = np.empty(n, dtype=float)
    posteriors: list[tuple[np.ndarray, np.ndarray]] = []

    log_r = np.zeros(1, dtype=float)  # step 1: P(r_0 = 0) = 1 -> log(1) = 0
    # True run length of each row in `log_r` / `model`, tracked explicitly
    # rather than assumed from array position -- §2.4 truncation can drop
    # hypotheses out of the middle of the array (see _truncation_mask), so
    # position and run length diverge as soon as pruning first fires.
    labels = np.zeros(1, dtype=np.int64)

    for t in range(n):
        xt = float(values[t])

        # Step 3: pi_t^(r) for every live r_{t-1}, using pre-update stats.
        log_pred = model.log_pred_prob(xt)
        # Hazard argument is r_{t-1}+1 (eq. 4): the run length the segment
        # would reach if it survives this bar. Uses the TRUE label, not
        # array position, so a non-constant future hazard stays correct
        # after truncation has reordered which position holds which run.
        hz = hazard(labels.astype(float) + 1.0)
        hz = np.clip(hz, np.finfo(float).tiny, 1.0 - np.finfo(float).tiny)
        log_hz = np.log(hz)
        log_1m_hz = np.log1p(-hz)

        log_joint_prior = log_r + log_pred
        log_growth = log_joint_prior + log_1m_hz  # step 4
        log_cp = _log_sum_exp(log_joint_prior + log_hz)  # step 5

        new_log_joint = np.concatenate(([log_cp], log_growth))
        new_labels = np.concatenate(([0], labels + 1))  # r=0 row, then each survivor +1
        log_evidence = _log_sum_exp(new_log_joint)  # step 6
        new_log_r = new_log_joint - log_evidence  # step 7

        model.update(xt)  # step 8: grow sufficient statistics

        # eq. 1 marginal predictive for x_{t+1}, mixed over the *full*
        # (pre-truncation) posterior so truncation never touches this
        # forecast, only the carried-forward run-length belief state.
        #
        # The freshly-prepended r=0 row has a genuinely undefined (infinite)
        # predictive variance under the paper's own a0=1 default (dof=2,
        # see GaussianVarianceModel.pred_var), so it is excluded from the
        # variance mixture and the remaining posterior mass is renormalized
        # -- flooring it into a finite number would silently fabricate a
        # plausible-looking but meaningless constant (verified: it produces
        # the SAME pred_std at every bar for every input, which is exactly
        # the "constant that looks fine until you check it" failure mode
        # this guards against).
        mu_r = model.pred_mean()
        var_r = model.pred_var()
        p = np.exp(new_log_r)

        pred_mean_out[t] = float(np.sum(p * mu_r))

        var_defined = np.isfinite(var_r)
        defined_mass = float(np.sum(p[var_defined]))
        pred_var_defined_mass_out[t] = defined_mass
        if defined_mass > 0.0:
            w = p[var_defined] / defined_mass
            cond_mean = float(np.sum(w * mu_r[var_defined]))
            e_var = float(np.sum(w * var_r[var_defined]))
            var_of_mean = float(np.sum(w * (mu_r[var_defined] - cond_mean) ** 2))
            pred_std_out[t] = math.sqrt(max(e_var + var_of_mean, 0.0))
        else:
            pred_std_out[t] = float("nan")

        if truncation_mass > 0.0:
            keep = _truncation_mask(new_log_r, truncation_mass)
            if not keep.all():
                new_log_r = new_log_r[keep]
                new_log_r = new_log_r - _log_sum_exp(new_log_r)
                new_labels = new_labels[keep]
                model.prune(keep)

        log_r = new_log_r
        labels = new_labels
        probs = np.exp(log_r)
        posteriors.append((labels, probs))

        # Row 0 is always label 0 (see _truncation_mask: it is never pruned),
        # so this is exactly P(r_t = 0 | x_1:t) -- kept only as a self-check;
        # see BocpdResult.cp_prob_raw for why it is not a detection signal.
        cp_prob_raw[t] = probs[0]
        break_prob[t] = float(np.sum(probs[labels <= 5]))
        break_prob_20[t] = float(np.sum(probs[labels <= 20]))
        map_run_length[t] = int(labels[np.argmax(probs)])
        expected_run_length[t] = float(np.sum(probs * labels))

    return BocpdResult(
        cp_prob_raw=cp_prob_raw,
        break_prob=break_prob,
        break_prob_20=break_prob_20,
        map_run_length=map_run_length,
        expected_run_length=expected_run_length,
        pred_mean=pred_mean_out,
        pred_std=pred_std_out,
        pred_var_defined_mass=pred_var_defined_mass_out,
        run_length_posteriors=posteriors,
    )


def changepoints_from_prices(
    close: pd.Series,
    *,
    lambda_gap: float = 250.0,
    a: float = 1.0,
    b: float = 1e-4,
    truncation_mass: float = 1e-4,
) -> BocpdResult:
    """Convenience wrapper for the paper's §3.2 configuration on a price series.

    Forms simple returns R_t = p_t/p_{t-1} - 1 (paper eq. 14) and runs the
    zero-mean-Gaussian / Gamma-precision-prior model with a constant hazard.
    The first bar has no return (nothing to divide by) and is dropped, not
    filled -- filling it would fabricate a zero-return observation that never
    happened.
    """
    if not isinstance(close, pd.Series):
        raise ValueError("close must be a pandas Series of prices")
    returns = close.pct_change(fill_method=None).dropna()
    if returns.empty:
        raise ValueError("close must contain at least two priced bars to form a return")
    model = GaussianVarianceModel(a=a, b=b)
    hazard = ConstantHazard(lambda_gap=lambda_gap)
    return bocpd(returns.to_numpy(dtype=float), model, hazard, truncation_mass=truncation_mass)
