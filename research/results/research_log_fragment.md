## Pass 1 — coarse screen
Cost: 0.08% RT | Train 70% / Test 30% | max hold 30 bars
- **H7_pdh_rvol** `INFY.NS` params={"rvol_min": 1.5, "side": 1} | OOS n=21 E=1.249% PF=2.65 MDD=-9.2% score=14.36
- **H3_gap_fade** `NIFTYBEES.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=145 E=0.815% PF=2.69 MDD=-13.0% score=10.86
- **H3_gap_fade** `ICICIBANK.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=26 E=0.766% PF=3.24 MDD=-3.3% score=10.13
- **H3_gap_fade** `^NSEBANK` params={"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=25 E=0.319% PF=1.52 MDD=-10.9% score=4.27
- **H3_gap_fade** `TCS.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=22 E=0.170% PF=1.19 MDD=-11.5% score=2.36
- **H7_pdh_rvol** `NIFTYBEES.NS` params={"rvol_min": 1.5, "side": -1} | OOS n=21 E=0.083% PF=1.15 MDD=-5.8% score=1.48
- **H3_gap_fade** `BANKBEES.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=83 E=0.008% PF=1.01 MDD=-22.5% score=0.56
- **H7_pdh_rvol** `TCS.NS` params={"rvol_min": 1.5, "side": 1} | OOS n=22 E=-0.049% PF=0.96 MDD=-14.6% score=-8.21
- **H3_gap_fade** `HDFCBANK.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=44 E=-0.146% PF=0.82 MDD=-19.3% score=-9.42
- **H3_gap_fade** `HDFCBANK.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=39 E=-0.161% PF=0.78 MDD=-14.5% score=-9.55
- **H7_pdh_rvol** `^NSEBANK` params={"rvol_min": 1.5, "side": 1} | OOS n=26 E=-0.211% PF=0.77 MDD=-11.1% score=-10.01
- **H3_gap_fade** `TCS.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=39 E=-0.235% PF=0.73 MDD=-18.9% score=-10.44
- **H3_gap_fade** `ICICIBANK.NS` params={"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=39 E=-0.271% PF=0.63 MDD=-13.0% score=-10.98
- **H7_pdh_rvol** `TCS.NS` params={"rvol_min": 1.5, "side": -1} | OOS n=26 E=-0.324% PF=0.77 MDD=-15.5% score=-11.23
- **H7_pdh_rvol** `BANKBEES.NS` params={"rvol_min": 1.5, "side": 1} | OOS n=25 E=-0.315% PF=0.61 MDD=-11.9% score=-11.26

## Per-hypothesis verdict (best symbol OOS)
- **H1_donchian_rvol**: REJECT — best `ICICIBANK.NS` OOS E=-1.504% n=23 PF=0.38; index mean E=-0.434%
- **H2_nr7_breakout**: REJECT — best `^NSEI` OOS E=-2.188% n=7 PF=0.01; index mean E=-1.157%
- **H3_gap_fade**: PROMISING — best `NIFTYBEES.NS` OOS E=0.815% n=145 PF=2.69; index mean E=-0.589%
- **H4_bos_volume**: REJECT — best `TCS.NS` OOS E=-0.999% n=17 PF=0.69; index mean E=0.002%
- **H5_inside_bar**: REJECT — best `HDFCBANK.NS` OOS E=-4.933% n=5 PF=0.00; index mean E=0.690%
- **H6_atr_squeeze**: REJECT — best `BANKBEES.NS` OOS E=-3.047% n=4 PF=0.18; index mean E=0.029%
- **H7_pdh_rvol**: WEAK/PARTIAL — best `INFY.NS` OOS E=1.249% n=21 PF=2.65; index mean E=0.172%
- **H8_pullback_reclaim**: REJECT — best `^NSEBANK` OOS E=-0.921% n=1 PF=0.00; index mean E=0.077%
- **H9_climax_reversal**: REJECT — best `RELIANCE.NS` OOS E=-0.823% n=4 PF=0.15; index mean E=1.761%
- **H10_vwap_reclaim**: REJECT — best `BANKBEES.NS` OOS E=0.364% n=11 PF=1.64; index mean E=-0.230%
- **H12_contraction_thrust**: REJECT — best `^NSEBANK` OOS E=0.046% n=1 PF=999.00; index mean E=-0.730%

## Pass 2 — walk-forward + ±20% param perturbation
- **H3_gap_fade** `^NSEI` {"gap_min": 0.012, "rvol_max": 0.9, "side": 1} | OOS n=6 E=0.341% PF=2.90 | WF n=1 E=3.196% PF=999.00 | pert+=0% meanE=-0.302%
- **H3_gap_fade** `NIFTYBEES.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=23 E=-1.602% PF=0.10 | WF n=13 E=0.915% PF=6.62 | pert+=0% meanE=-1.645%
- **H3_gap_fade** `NIFTYBEES.NS` {"gap_min": 0.012, "rvol_max": 0.9, "side": 1} | OOS n=15 E=-2.020% PF=0.10 | WF n=9 E=0.742% PF=6.95 | pert+=0% meanE=-2.028%
- **H3_gap_fade** `^NSEBANK` {"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=25 E=0.319% PF=1.52 | WF n=20 E=0.132% PF=1.13 | pert+=100% meanE=0.387%
- **H3_gap_fade** `^NSEBANK` {"gap_min": 0.012, "rvol_max": 0.9, "side": 1} | OOS n=12 E=0.526% PF=1.93 | WF n=9 E=0.016% PF=1.01 | pert+=100% meanE=0.488%
- **H3_gap_fade** `RELIANCE.NS` {"gap_min": 0.012, "rvol_max": 0.9, "side": 1} | OOS n=6 E=-0.509% PF=0.62 | WF n=3 E=-0.222% PF=0.64 | pert+=0% meanE=-1.273%
- **H3_gap_fade** `^NSEI` {"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=17 E=-0.112% PF=0.81 | WF n=7 E=-0.254% PF=0.78 | pert+=0% meanE=-0.196%
- **H3_gap_fade** `NIFTYBEES.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=145 E=0.815% PF=2.69 | WF n=20 E=-0.309% PF=0.58 | pert+=100% meanE=0.861%
- **H3_gap_fade** `HDFCBANK.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=44 E=-0.146% PF=0.82 | WF n=29 E=-0.397% PF=0.55 | pert+=20% meanE=-0.170%
- **H3_gap_fade** `RELIANCE.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=21 E=-1.105% PF=0.35 | WF n=23 E=-0.402% PF=0.58 | pert+=0% meanE=-1.121%
- **H3_gap_fade** `ICICIBANK.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": 1} | OOS n=26 E=0.766% PF=3.24 | WF n=41 E=-0.455% PF=0.64 | pert+=100% meanE=0.644%
- **H3_gap_fade** `ICICIBANK.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=39 E=-0.271% PF=0.63 | WF n=60 E=-0.863% PF=0.52 | pert+=20% meanE=-0.375%
- **H3_gap_fade** `HDFCBANK.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=39 E=-0.161% PF=0.78 | WF n=36 E=-0.925% PF=0.44 | pert+=20% meanE=-0.121%
- **H3_gap_fade** `HDFCBANK.NS` {"gap_min": 0.012, "rvol_max": 0.9, "side": 1} | OOS n=17 E=-0.282% PF=0.74 | WF n=8 E=-0.984% PF=0.21 | pert+=25% meanE=-0.274%
- **H3_gap_fade** `RELIANCE.NS` {"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=30 E=-0.313% PF=0.75 | WF n=27 E=-1.081% PF=0.38 | pert+=40% meanE=-0.135%
- **H3_gap_fade** `ICICIBANK.NS` {"gap_min": 0.012, "rvol_max": 0.9, "side": 1} | OOS n=11 E=0.784% PF=4.14 | WF n=12 E=-1.221% PF=0.24 | pert+=100% meanE=0.610%
- **H3_gap_fade** `^NSEBANK` {"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=31 E=-0.622% PF=0.51 | WF n=24 E=-1.273% PF=0.19 | pert+=0% meanE=-0.726%
- **H3_gap_fade** `^NSEI` {"gap_min": 0.008, "rvol_max": 1.0, "side": -1} | OOS n=14 E=-0.424% PF=0.52 | WF n=6 E=-2.920% PF=0.01 | pert+=0% meanE=-0.581%

## Winner selection
Selected: **H3_gap_fade** on `^NSEBANK` params={"gap_min": 0.008, "rvol_max": 1.0, "side": 1}

Multi-symbol OOS positive fraction: 33% (mean E=-0.448%)
- `ICICIBANK.NS` n=26 E=0.766% PF=3.24 MDD=-3.3%
- `^NSEBANK` n=25 E=0.319% PF=1.52 MDD=-10.9%
- `TCS.NS` n=22 E=0.170% PF=1.19 MDD=-11.5%
- `^NSEI` n=17 E=-0.112% PF=0.81 MDD=-9.1%
- `HDFCBANK.NS` n=44 E=-0.146% PF=0.82 MDD=-19.3%
- `INFY.NS` n=32 E=-0.641% PF=0.47 MDD=-16.4%
- `RELIANCE.NS` n=21 E=-1.105% PF=0.35 MDD=-27.7%
- `NIFTYBEES.NS` n=23 E=-1.602% PF=0.10 MDD=-31.0%
- `BANKBEES.NS` n=9 E=-1.683% PF=0.12 MDD=-14.7%
