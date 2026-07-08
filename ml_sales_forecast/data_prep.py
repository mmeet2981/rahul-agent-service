"""
Parse raw Tally-exported Sales Register files (all companies) into a clean
monthly (company, product, month) -> quantity/value dataset for forecasting.

Each voucher in a Tally Sales Register is exported as a block of rows:
  - the first row of the block carries the Date + Buyer + voucher totals
  - the following rows (blank Date) are the actual product line items
Only the line-item rows are used for product-level quantity/value; the
voucher-total row is used only as a fallback when a voucher has no
separate line items (single-item vouchers).
"""
from pathlib import Path

import pandas as pd

RAW_DATA_DIR = Path("/home/gopi/Downloads/Final Sorted Data")
OUTPUT_PATH = Path(__file__).parent / "monthly_sales.csv"

KNOWN_COMPANIES = [
    "Rahul Traders Surat",
    "Rahul Traders",
    "Rahul Papers India Pvt Ltd",
    "Mahavir Paper Trading Company",
    "Bhavani Industries",
]


def normalize_company(raw_name: str) -> str:
    name = str(raw_name).strip().upper()
    if "SURAT" in name:
        return "Rahul Traders Surat"
    if "RAHUL TRADERS" in name:
        return "Rahul Traders"
    if "RAHUL PAPERS" in name:
        return "Rahul Papers India Pvt Ltd"
    if "MAHAVIR" in name:
        return "Mahavir Paper Trading Company"
    if "BHAVANI" in name:
        return "Bhavani Industries"
    return str(raw_name).strip()


def find_header_row(raw: pd.DataFrame) -> int:
    for i in range(min(15, len(raw))):
        row = raw.iloc[i]
        if str(row[0]).strip().lower() == "date" and str(row[1]).strip().lower() == "particulars":
            return i
    return -1


def extract_file(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        xls = pd.ExcelFile(path)
    except Exception as e:
        print(f"  SKIP (open error) {path.name}: {e}")
        return records

    for sheet_name in xls.sheet_names:
        sname = sheet_name.lower()
        if "sale" not in sname or "order" in sname:
            continue
        try:
            raw = xls.parse(sheet_name, header=None)
        except Exception as e:
            print(f"  SKIP sheet {sheet_name} in {path.name}: {e}")
            continue
        if raw.empty:
            continue

        company = normalize_company(raw.iloc[0, 0])

        header_idx = find_header_row(raw)
        if header_idx == -1:
            continue
        columns = [str(c).strip() for c in raw.iloc[header_idx]]
        data = raw.iloc[header_idx + 1:].copy()
        data.columns = columns
        if not {"Date", "Particulars", "Quantity", "Value"}.issubset(data.columns):
            continue
        buyer_col = "Buyer" if "Buyer" in data.columns else None

        n = len(data)
        i = 0
        while i < n:
            row = data.iloc[i]
            if pd.isna(row["Date"]):
                i += 1
                continue

            current_date = row["Date"]
            current_buyer = row[buyer_col] if buyer_col else None

            j = i + 1
            line_items = []
            while j < n and pd.isna(data.iloc[j]["Date"]):
                part = data.iloc[j]["Particulars"]
                qty = data.iloc[j]["Quantity"]
                if pd.notna(part) and str(part).strip().lower() != "grand total" and pd.notna(qty) and qty != 0:
                    line_items.append((part, qty, data.iloc[j]["Value"]))
                j += 1

            if not line_items:
                part, qty, val = row["Particulars"], row["Quantity"], row["Value"]
                if pd.notna(part) and str(part).strip().lower() != "grand total" and pd.notna(qty) and qty != 0:
                    line_items.append((part, qty, val))

            for part, qty, val in line_items:
                records.append({
                    "company": company,
                    "date": current_date,
                    "buyer": current_buyer,
                    "product": str(part).strip(),
                    "quantity": float(qty),
                    "value": float(val) if pd.notna(val) else 0.0,
                })
            i = j

    return records


def main():
    all_records: list[dict] = []
    for folder in sorted(RAW_DATA_DIR.iterdir()):
        if not folder.is_dir() or folder.name == "Inventory Data":
            continue
        print(f"Processing folder: {folder.name}")
        for file in sorted(folder.iterdir()):
            if file.name.startswith("~$") or file.suffix.lower() not in (".xls", ".xlsx"):
                continue
            recs = extract_file(file)
            print(f"  {file.name}: {len(recs)} line items")
            all_records.extend(recs)

    df = pd.DataFrame(all_records)
    print(f"\nTotal raw line items extracted: {len(df)}")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["month"] = df["date"].dt.to_period("M").astype(str)

    monthly = (
        df.groupby(["company", "product", "month"], as_index=False)
        .agg(quantity=("quantity", "sum"), value=("value", "sum"))
        .sort_values(["company", "product", "month"])
    )
    monthly.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved {len(monthly)} monthly (company, product, month) rows -> {OUTPUT_PATH}")
    print(f"Companies: {sorted(monthly['company'].unique())}")
    print(f"Distinct products: {monthly['product'].nunique()}")
    print(f"Month range: {monthly['month'].min()} to {monthly['month'].max()}")


if __name__ == "__main__":
    main()
