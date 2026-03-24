---
name: pulse-data-scientist
description: PULSE analytics and metrics math context. Use when defining metric formulas, classification thresholds, or visualization types.
---
# PULSE Data Scientist Skill
## DORA: DF=count/days (Elite≥1/day, High 1/wk-1/day, Med 1/mo-1/wk, Low<1/mo). LT=median(deploy-commit) (E<24h, H<168h, M<720h). CFR=failed/total (E≤15%, H≤30%, M≤45%). MTTR=median(restore) (E<1h, H<24h, M<168h). Overall=lowest of 4.
## Lean: CFD (stacked area, 5 statuses), WIP (count in-progress, green/amber/red vs limit), Lead Time Dist (histogram + P50/P85/P95 lines), Scatterplot (dots per issue, percentile lines), Throughput (bars/week + 4wk moving avg).
## Cycle Time: Coding→Pickup→Review→Merge→Deploy. Stacked bar. Longest=bottleneck. Lower=green↓.
## Little's Law: WIP × Lead Time = Throughput. Validate.
## Anti-surveillance: NEVER individual rankings. Team level only.
## By Release: MVP=descriptive. R1=trends+anomaly (2σ). R2=Monte Carlo+forecasting. R3=DevEx correlation. R4=AI/LLM.
