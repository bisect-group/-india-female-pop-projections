# Input data

| Folder | File | Source | Notes |
|---|---|---|---|
| `raw/wpp/` | `WPP2024_India_Female_Population_SingleAge_1950_2100.csv` | United Nations, Department of Economic and Social Affairs, Population Division (2024). *World Population Prospects 2024* | India, female, single ages 0–99 and 100+, 1950–2100, in thousands. |
| `raw/census/` | `Census_Master_AgeSex_1991_2001_2011.xlsx` | Office of the Registrar General & Census Commissioner, India — Census of India 1991 (C-6), 2001 and 2011 (C-14) age-sex tables | Sheet `Master_Long`: state × year × age group, persons/males/females, total/rural/urban. 1991 excludes Jammu & Kashmir. |
| `raw/srs/` | `SRS_Statistical_Report_2022_extracted.xlsx` | Office of the Registrar General, India — *Sample Registration System Statistical Report 2022* | Tables extracted from the report. Used only to validate age distributions (Table 1). In sheet `Age_Sex_Dist_2022`, Telangana's rows follow Tamil Nadu's without a state label; `popproj.load_srs2022_female_shares()` relabels them. |
| `raw/life_table/` | `India_Female_LifeTable_MeanQ_1950_2100.xlsx` | Derived female life table | 22 age groups (0, 1–4, 5–9, …, 100+) with the average death probability `Mean_q_1950_2100`; converted to annual hazards by band in `popmodel.life_table_mu()`. |
| `raw/icmr_ncdir/` | `ICMR_NCDIR_State_Female_Projections_2012_2036.xlsx` | ICMR – National Centre for Disease Informatics and Research (ICMR-NCDIR), Bengaluru | Female population projections by state/UT and five-year age band, 2012–2036. Sheet `Female`; column `Population` holds the state name. |

Please cite the original providers when using these data or the data products derived from them.
