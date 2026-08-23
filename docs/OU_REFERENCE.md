# Canonical OU / mean-reversion reference
Source: cantaro86/Financial-Models-Numerical-Methods, notebook
"6.1 Ornstein-Uhlenbeck process and applications.ipynb" (verified by direct read of the
cloned repo, 2026-08-20). Use this as the ground truth when auditing edge/ estimators.

## Model
dX_t = kappa * (theta - X_t) dt + sigma dW_t

## Exact discretization (NOT Euler-Maruyama — Euler is biased for large dt)
X_{t+dt} = theta + exp(-kappa*dt) * (X_t - theta) + std_dt * Z,  Z ~ N(0,1)
std_dt = sqrt( sigma^2/(2*kappa) * (1 - exp(-2*kappa*dt)) )

## OLS estimator (reference implementation, verbatim structure)
XX = X[:-1]; YY = X[1:]
beta, alpha = linregress(XX, YY)          # YY = alpha + beta*XX
kappa_hat = -log(beta) / dt
theta_hat = alpha / (1 - beta)
resid     = YY - beta*XX - alpha
sigma_hat = std(resid, ddof=2) * sqrt( 2*kappa_hat / (1 - beta**2) )

half_life = log(2) / kappa_hat            # in the SAME time units as dt

## CRITICAL: the two regression forms are NOT interchangeable
  Form A (level-on-lag):  X_{t+1} = alpha + beta * X_t      -> kappa = -ln(beta)/dt
  Form B (delta-on-lag):  dX_t    = alpha + b    * X_t      -> beta = 1 + b,
                                                              kappa = -ln(1+b)/dt
Using -ln(2)/ln(b) on a Form-B coefficient is a real bug (b is near 0, not near 1).

## Required guards
- beta <= 0  -> no meaningful OU fit (oscillating / overshooting); return missing, not a number.
- beta >= 1  -> non-mean-reverting (unit root or explosive); kappa <= 0, half-life is
  undefined/infinite. Return an explicit missing/stale state — per repo convention,
  NEVER a fake zero or a clipped sentinel presented as a real estimate.
- Minimum sample: OU/AR(1) estimates are badly biased in small samples (Kendall bias
  ~ -(1+3*beta)/n). Require a documented n_min and report it.
- dt must match the bar frequency. If the series is daily bars and dt=1, kappa and
  half_life are in DAYS. If dt=1/252, they are in YEARS. Be explicit at every consumer.

## MLE (lower variance than OLS; reference also implements this)
theta_mle = (Sy*Sxx - Sx*Sxy) / (N*(Sxx - Sxy) - (Sx^2 - Sx*Sy))
kappa_mle = -(1/dt) * log( (Sxy - theta*Sx - theta*Sy + N*theta^2)
                           / (Sxx - 2*theta*Sx + N*theta^2) )
where Sx=sum(XX), Sy=sum(YY), Sxx=XX@XX, Sxy=XX@YY, Syy=YY@YY.

## First-passage (hitting) time X0 -> theta  — useful as a tradeable horizon estimate
C = (X0 - theta) * sqrt(2*kappa) / sigma
density in rescaled time t' = kappa*t:
  f(t') = sqrt(2/pi) * |C| * exp(-t') / (1-exp(-2t'))^{3/2}
          * exp( -C^2 * exp(-2t') / (2*(1-exp(-2t'))) )
Actual density in real time = kappa * f(kappa * t).
E[T] and sd(T) obtained by numerical integration of that density.

## Look-ahead rules (repo-specific, non-negotiable)
- Any fit used to generate a signal at time t must use data <= t only
  (expanding or rolling window, walk-forward). A full-sample fit reused across the
  whole sample is look-ahead bias and invalidates any backtest built on it.
- z-scores / spread normalization must use rolling or expanding mean & std, never
  full-sample.
- Overlapping windows produce autocorrelated residuals: t-stats and Sharpe computed
  from them are inflated unless Newey-West adjusted.
