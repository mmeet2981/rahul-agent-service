# Sales Data Coverage — Company-wise Missing Months

This report is built from the sales Excel files in `Downloads/Final Sorted Data`.
Wherever "MISSING" is shown, it means **no sales Excel file was found for that month**
(the data isn't wrong — that file simply wasn't provided).

**Overall: no company has any data at all for 2025-04 to 2025-08 (5 months).**

---

## 1. Rahul Traders
- Data available: **2022-04 to 2026-07**
- Present: 40 / 52 months
- **Missing (12 months): 2025-04, 2025-05, 2025-06, 2025-07, 2025-08, 2025-09, 2025-10, 2025-11, 2025-12, 2026-01, 2026-02, 2026-03**

## 2. Rahul Papers India Pvt Ltd
- Data available: **2022-04 to 2026-07**
- Present: 28 / 52 months
- **Missing (24 months): the entire span from 2024-04 to 2026-03 (2024-04, 05, 06, 07, 08, 09, 10, 11, 12, 2025-01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 2026-01, 02, 03)**
- ⚠️ The largest gap — a full 2 years of data missing for this company.

## 3. Mahavir Paper Trading Company
- Data available: **2026-04 to 2026-07**
- Present: 4 / 4 months — no gap within this range
- Only the last 4 months of data exist; nothing older was ever provided.

## 4. Bhavani Industries
- Data available: **2025-09 to 2026-06**
- Present: 10 / 10 months — no gap within this range
- No data exists before 2025-09.

## 5. Rahul Traders Surat
- Data available: **2026-06 to 2026-07**
- Present: 2 / 2 months — no gap
- Only 2 months of data — the shortest history of any company.

---

## Quick Summary Table

| Company | From | To | Months Present | Months Missing |
|---|---|---|---|---|
| Rahul Traders | 2022-04 | 2026-07 | 40 | 12 (Apr'25–Mar'26) |
| Rahul Papers India Pvt Ltd | 2022-04 | 2026-07 | 28 | 24 (Apr'24–Mar'26) |
| Mahavir Paper Trading Company | 2026-04 | 2026-07 | 4 | 0 |
| Bhavani Industries | 2025-09 | 2026-06 | 10 | 0 |
| Rahul Traders Surat | 2026-06 | 2026-07 | 2 | 0 |

## Impact on Forecasting
- For the missing months, the model has **no ground truth** — those months can't be verified or treated as "actual."
- The forecast for the month right after a gap (e.g. Rahul Traders' 2026-04) is weaker, because the real data for the prior 3 months isn't available and gets treated as zero.
- If the missing months' Excel files become available later, adding them to the dataset and retraining would likely improve accuracy.
