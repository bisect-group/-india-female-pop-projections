# India Female Population Projections 1991–2100

Annual female population time series for **India and all 37 States/UTs**, spanning 1991–2100,
broken into 16 age bands. Built from Census anchor years, NCDIR state-level projections,
and WPP-calibrated long-run projections.

---

## Quick Start

```bash
git clone https://github.com/bisect-group/-india-female-pop-projections.git
cd -india-female-pop-projections
pip install -r requirements.txt
jupyter notebook notebooks/India_Female_Population_1991_2100.ipynb
# Run All Cells — output Excel files appear in output/
```

---

## Repository Structure

```
india-female-pop-projections/
├── data/
│   ├── wpp/
│   │   └── India_Population_TimeSeries_Female.csv
│   │       # UN World Population Prospects 2024 — India female population
│   │       # for every single age (0,1,2,...,100+) and every year 1950–2100.
│   │       # Used for: (1) WPP-scaled long-run growth ratios post-2036,
│   │       # (2) within-band splitting for non-standard age boundaries.
│   ├── census/
│   │   └── Census_Master_AgeSex_1991_2001_2011.xlsx
│   │       # Census of India age-sex tables for all states — 1991, 2001, 2011.
│   └── ncdir/
│       └── State_Female_Projections_2012_2036.xlsx
│           # State-wise female population by 16 age bands, 5-year steps 2012–2036.
│           # Produced by NCDIR using the Census Cohort Component Method
│           # (Census 2011 base year, SRS fertility, Coale-Demeny West life tables).
├── notebooks/
│   ├── generate_notebook.py          # regenerates the .ipynb from source
│   └── India_Female_Population_1991_2100.ipynb
├── output/                           # created by notebook at runtime
│   ├── India_Female_AgeBands_1991_2100.xlsx
│   ├── Combined_All_States_1991_2100.xlsx
│   ├── Custom_AgeBands_India.xlsx
│   ├── Custom_AgeBands_All_States.xlsx
│   ├── Lambda_<band>.csv             # lambda function for epidemiological models
│   └── States/<State>.xlsx  (37 files)
├── requirements.txt
└── README.md
```

---

## Methodology — Three-Segment Pipeline

### Segment 1: Census Anchor Years + Linear Interpolation (1991–2011)

The census period uses **two sub-segments** to eliminate the discontinuity that
arises when switching from census to NCDIR data at 2011/2012:

**Sub-segment 1A — 1991 to 2001** (Census anchors at both ends):

$$P(\text{band},\, t) = C(\text{band},\, 1991) + \frac{t - 1991}{10}\bigl[C(\text{band},\, 2001) - C(\text{band},\, 1991)\bigr]$$

**Sub-segment 1B — 2001 to 2011** (Census 2001 → NCDIR 2012; Census 2011 not used):

$$P(\text{band},\, t) = C(\text{band},\, 2001) + \frac{t - 2001}{11}\bigl[N(\text{band},\, 2012) - C(\text{band},\, 2001)\bigr]$$

where $N(\text{band},\, 2012)$ is the NCDIR 2012 value. Because the 2012 endpoint of
this line equals $N(\text{band},\, 2012)$ exactly, the annual step from 2011 to 2012
is a uniform continuation of the same interpolation line — no source-change
discontinuity at the segment boundary.

Census bands map directly to the 16 NCDIR standard bands; only `75-79` and `80+`
are combined into the NCDIR `75+` band.

### Segment 2: NCDIR Projections (2012–2036)

State-level female population projections in 5-year steps from NCDIR, linearly
interpolated to annual resolution.

**Bifurcated states** — states created after 1991 have no earlier census records;
their populations are back-estimated using NCDIR 2012 split ratios applied to the
parent state's census values:

| New State | Parent State | Split Ratio Source |
|-----------|-------------|-------------------|
| Jharkhand | Bihar | NCDIR 2012 |
| Chhattisgarh | Madhya Pradesh | NCDIR 2012 |
| Uttarakhand | Uttar Pradesh | NCDIR 2012 |
| Telangana | Andhra Pradesh | NCDIR 2012 |
| Ladakh | Jammu & Kashmir | NCDIR 2012 (1991 back-extrapolated) |

### Segment 3: WPP-Scaled Long-Run Projections (2037–2100)

#### WPP Growth Ratio

For each age band $x$ and year $t$:

$$\rho(x,\, t) = \frac{P_{\text{WPP}}(x,\, t)}{P_{\text{WPP}}(x,\, 2036)}$$

Captures how WPP projects each band's *relative* trajectory from the 2036 base.

#### Gompertz TFR Curve

$$\text{TFR}(t) = L + (U - L)\cdot a^{\,b^{(t-2010)}}$$

Parameters ($L=1.667$, $U=2.5$, $a$, $b$) are fitted to Census 2019 projected TFR values.

#### WPP-Scaled Projection Formula

$$P_{\text{proj}}(\text{band},\, t) = P_{\text{NCDIR}}(\text{band},\, 2036)\;\times\;\rho(\text{band},\, t)\;\times\;\left(\frac{\text{TFR}(t)}{\text{TFR}(2036)}\right)^{0.3}$$

#### Blending Window (2037–2046)

A 10-year linear blend transitions from NCDIR momentum to the WPP-scaled trajectory:

$$\alpha(t) = \frac{t - 2036}{10}, \quad P(t) = (1-\alpha)\,P_{\text{mom}}(t) + \alpha\,P_{\text{proj}}(t)$$

After 2046, a continuity correction ensures a smooth join:

$$P(t) = P_{\text{proj}}(t)\;\times\;\frac{P(2046)}{P_{\text{proj}}(2046)}, \quad t > 2046$$

---

## Age Bands

The 16 standard five-year bands come directly from the NCDIR file:

`00-04` · `05-09` · `10-14` · `15-19` · `20-24` · `25-29` · `30-34` · `35-39` ·
`40-44` · `45-49` · `50-54` · `55-59` · `60-64` · `65-69` · `70-74` · `75+`

---

## Custom Age Bands

The notebook includes a tool (Section 10) that lets you derive any age range from the
16 native bands. You specify:

```python
USER_BANDS = [
    ("18-29", 18, 29),    # partial overlap: splits 15-19 at 18 using WPP proportions
    ("9-14",   9, 14),    # partial overlap: splits 05-09 at 9 using WPP proportions
    ("65+",   65, None),  # open-ended: 65-69 + 70-74 + 75+
]
```

- **Exact boundaries**: bands summed directly.
- **Non-standard boundaries** (e.g., age 9 within the `05-09` band): WPP single-age
  data provides the within-band proportion, applied year-by-year.

Output is saved to `output/Custom_AgeBands_India.xlsx` and
`output/Custom_AgeBands_All_States.xlsx`.

---

## Data Sources

| Dataset | Source | Coverage |
|---------|--------|----------|
| UN World Population Prospects 2024 | UNDESA | India female, single age 0–100+, 1950–2100 |
| Census of India (Age × Sex tables) | Office of the Registrar General, India | All states, 1991, 2001, 2011 |
| State-level Female Projections | National Cancer Registry of India (NCDIR) | All states, 2012–2036 |
| Population Projections Report 2019 | Census of India | TFR targets for Gompertz fitting |
| SRS Statistical Report 2022 | Office of the Registrar General, India | Fertility and mortality inputs |

---

## Output Format

Each Excel file has columns:

| State | Year | 00-04 | 05-09 | … | 75+ | Total | Source |
|-------|------|-------|-------|---|-----|-------|--------|
| India | 1991 | … | … | … | … | … | Census-Interpolated |
| … | … | | | | | | NCDIR-Actual / WPP-Projection |

All population values are in **absolute persons** (not thousands or millions).

---

## Lambda Function for Epidemiological Models (Section 11)

In compartmental disease models (S → I → C → Deaths), transmission depends on the
size of the age-specific susceptible pool. Section 11 generates $\lambda(t)$ — the
population time series for any user-chosen age band — in two forms:

**Option 1 — Direct:** $\lambda(t) = P_{\text{band}}(t)$
Uses the projected population at the actual calendar year $t$.

**Option 2 — Shifted by N years:** $\lambda(t) = P_{\text{band}}(t + N)$
For simulation year $t$, uses the population $N$ years ahead in calendar time.
This avoids dependence on back-extrapolated pre-2012 values: with $N = 10$,
simulation year 2002 maps to the reliable 2012 NCDIR population, and so on.

Configure in Section 11:
```python
LAMBDA_BAND  = "18-29"              # any label from USER_BANDS
N_SHIFT      = 10                   # shift for Option 2
LAMBDA_YEARS = list(range(2002, 2071))
```

Output: `output/Lambda_<band>.csv` with columns `Year`, `Lambda_Direct`,
`Lambda_Shifted_N<shift>` (population in thousands).

---

## License

MIT License. Data from government and UN sources retain their original terms of use.
