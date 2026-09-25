# Methods

Notation: state/UT $s$ (37 series), age band $b$ (16 five-year bands, 00–04 … 70–74, 75+), calendar year $t$ (mid-year).
$W_b(t)$ is WPP 2024 India female population in band $b$; $C_{s,b}(t_a)$ is the harmonised Census count at anchor year
$t_a \in \{1991, 2001, 2011\}$. Code: `src/popproj.py`, `src/popmodel.py`, `notebooks/`.

## 1. Inputs

| Input | File | Notes |
|---|---|---|
| WPP 2024 India female population | `data/raw/wpp/` | single ages 0–100+, 1950–2100 (thousands), summed to bands |
| Census of India age-sex tables | `data/raw/census/` | 1991 (excluding J&K), 2001, 2011 |
| SRS Statistical Report 2022 | `data/raw/srs/` | female % age distribution, India + 22 bigger states (validation only) |
| Life table | `data/raw/life_table/` | 22 age groups, average death probability $q$ 1950–2100 |
| ICMR-NCDIR state female projections | `data/raw/icmr_ncdir/` | 37 series × 2012–2036 × 16 bands |

## 2. Structure of the ICMR-NCDIR projections

Every series satisfies $P_{s,b}(t) = N_s(t)\,c_{s,b}$ exactly: the state total $N_s(t)$ follows a projection, while the age
shares $c_{s,b}$ are constant over 2012–2036 (maximum change 0.0000 percentage points). For 30 series $c_{s,b}$ is a table of
percentages printed to 0.1 % (share × $K$, $K \approx 100$, lands on a 0.1 grid); 22 of these tables are distinct and 8 smaller units
reuse a neighbouring state's table; 7 smaller states/UTs use their own Census 2011 split.

## 3. Track A — extending ICMR-NCDIR to 1950–2100

For a series $y(t)$ known on 2012–2036 and a WPP reference $W(t)$ (ratio method):
$$y(t) = y(2036)\frac{W(t)}{W(2036)}\ (t>2036), \qquad y(t) = y(2012)\frac{W(t)}{W(2012)}\ (t<2012).$$

**Blended variant.** In log-growth $g(t)=\ln\bigl(y(t)/y(t-1)\bigr)$, $k$ years from a join,
$$g(t) = w(k)\,g_{\text{join}} + (1-w(k))\,g_W(t),\qquad w(k) = \tfrac12\bigl(1+\cos(\pi k/T)\bigr)\ (k<T),\ 0\ \text{otherwise},$$
with $T = 10$ years.

- **A1**: extend $N_s(t)$ with WPP India's total; $P_{s,b}(t) = N_s(t)\,c_{s,b}$ (fixed split everywhere).
- **A2**: extend each band with WPP India's band $W_b(t)$ (split fixed inside 2012–2036, changing outside).
- **A1-blend, A2-blend**: as above with blending.

States have no WPP series, so each state uses India's WPP shape. India = sum of states.

## 4. Cohort diagnostics

A cohort in band $b$ at year $t$ is in band $b+2$ at $t+10$. Ten-year survival and implied mortality:
$$S_b(t) = \frac{P_{b+2}(t+10)}{P_b(t)}, \qquad \mu_b = -\frac{\ln S_b}{10}.$$
Without migration $S_b \le 1$. $S_b > 1$ (negative implied mortality) means a births → aging → deaths model can only reproduce
the series with negative death rates.

## 5. Track B — Census-anchored series

### 5.1 Census anchors (today's boundaries in all years)

| Issue | Treatment |
|---|---|
| Age not stated | Redistributed pro rata across bands, per state and year |
| J&K not enumerated in 1991 | J&K 2001 × (rest-of-India band growth 1991→2001) |
| Chhattisgarh, Jharkhand, Uttarakhand in 1991 | Parent (MP, Bihar, UP) split band by band with the child's 2001 share |
| Telangana, Ladakh | Parent (Andhra Pradesh, J&K) split by the ICMR-NCDIR 2012 total ratio |
| Census date (1 March) | Shifted to mid-year: $C\,e^{g_b \cdot 4/12}$ with $g_b$ the band's intercensal growth |

### 5.2 National series (band-wise ratio method)
$$P^B_b(t) = W_b(t)\,\rho_b(t),\qquad \rho_b(t_a) = \frac{C_b(t_a)}{W_b(t_a)},$$
$\log\rho_b$ interpolated by a monotone cubic (PCHIP) between anchors. Outside 1991–2011:
**B-hold** keeps $\rho_b$ at the nearest anchor; **B-taper** fades $\log\rho_b$ to 0 (WPP) with a cosine over 30 years;
**B-smooth** holds $\rho_b$ after smoothing $\log\rho_b$ across neighbouring bands (weights ¼, ½, ¼), which no longer passes
exactly through the anchors.

### 5.3 State series
Each state is a share of the national band, $d_{s,b}(t) = P_{s,b}(t)/P_b(t)$, exact at the anchors and interpolated (PCHIP on
$\log d$) between them. Outside 1991–2011: **hold** ($d$ fixed) or **drift-damped** (the last decade's trend in $\log d$ continued
with a 15-year half-life). Raking to the national band totals:
$$P^B_{s,b}(t) = P^B_b(t)\,\frac{d_{s,b}(t)}{\sum_{s'} d_{s',b}(t)}.$$
Out-of-sample tests (predict 2011 from 1991 + 2001, and 1991 from 2001 + 2011): hold predicts the age split best (median 3.1 % of
women misplaced), drift-damped the totals best (2.8 % vs 4.6 %).

### 5.4 Validation
Against SRS 2022 female age distributions (not used in construction): error = $\tfrac12\sum_b|\text{share}_b - \text{SRS}_b|$
(% of women in the wrong band).

## 6. Track C — ICMR-NCDIR totals, Census-anchored split
$$P^C_{s,b}(t) = N^A_s(t)\,\frac{P^B_{s,b}(t)}{\sum_{b'}P^B_{s,b'}(t)}.$$
Totals equal ICMR-NCDIR in 2012–2036 (and Track A outside it); the age split equals Track B's. Any all-ages ratio computed per
head of population is therefore identical to one computed on ICMR-NCDIR, while age-specific populations follow the Census.

## 7. Population model

$$\frac{dP_1}{dt} = \Lambda(t) - (k_1+\mu_1)P_1,\quad
\frac{dP_i}{dt} = k_{i-1}P_{i-1} - (k_i+\mu_i)P_i\ (i=2..15),\quad
\frac{dP_{16}}{dt} = k_{15}P_{15} - \mu_{16}P_{16}.$$

| Component | Options |
|---|---|
| Recruitment $\Lambda$ | constant; or $p\,\Lambda^*(t)$ with $\Lambda^*$ = women aged 20–29 ten years ahead (default) or women 15–49 in the same year, from the same track |
| Mortality $\mu$ | one fitted rate; 16 fitted rates; or fixed from the life table, $\mu = -\ln(1-q)/n$ combined into bands |
| Maturation $k$ | 15 fitted rates; or fixed at $1/\text{band width} = 0.2$ per year |

**Fitting.** Initial condition = data at the first fitted year. Weighted least squares over all bands and years with
residual $(\hat P_{b}(t) - P_{b}(t))/\sigma_b$, $\sigma_b$ = standard deviation of band $b$ over time. Bounds:
$\Lambda,p \ge 0$, $0 \le \mu \le 1$, $0.01 \le k \le 1.5$ per year. Trust-region reflective least squares with an ODE tolerance of
$10^{-8}$ (relative) and a finite-difference step of $10^{-3}$, restarted once from the solution. Metrics: mean absolute
percentage error by band (MAPE), MAPE of the total, maximum error, and the number of parameters at a bound.
