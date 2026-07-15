import pandas as pd
import requests
import re
import os
from datetime import datetime
from rapidfuzz import process, fuzz
import io

# --- Configuration ---
JSON_URL = "https://static.startribune.com/news/projects/all/2025-cannabis-map/data/data.json"
EXCEL_URL = "https://mn.gov/ocm/assets/MN_OCM_licensed_businesses_071326_tcm1202-714418.xlsx"

TRACKED_JSON_FILE = "tracked_json.csv"
FINAL_OUTPUT_FILE = "combined_data.csv"
MATCH_THRESHOLD = 85  # Fuzzy match score threshold

def clean_text(text):
    """Normalizes strings to improve baseline matching."""
    if pd.isna(text):
        return ""
    text = str(text).lower().strip()
    text = re.sub(r'[^\w\s]', '', text) # Remove punctuation
    text = re.sub(r'\s+', ' ', text)     # Remove extra spaces
    return text

def main():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # ==========================================
    # 1. FETCH & UPDATE JSON WITH 'DATE ADDED'
    # ==========================================
    print("Fetching latest JSON data...")
    response_json = requests.get(JSON_URL, headers=headers)
    response_json.raise_for_status()
    
    # Load fresh JSON into a dataframe
    df_fresh_json = pd.DataFrame(response_json.json())
    
    # Check if we have historical tracked data
    if os.path.exists(TRACKED_JSON_FILE):
        print("Loading historical tracked JSON data...")
        df_tracked = pd.read_csv(TRACKED_JSON_FILE)
    else:
        print("No historical data found. Initializing new tracker...")
        df_tracked = pd.DataFrame(columns=df_fresh_json.columns.tolist() + ['date_added'])

    today_str = datetime.today().strftime('%Y-%m-%d')
    new_rows_count = 0

    # Identify new IDs that aren't in our tracked history
    tracked_ids = set(df_tracked['id'].dropna().astype(str))
    
    new_records = []
    for _, row in df_fresh_json.iterrows():
        row_id = str(row.get('id', ''))
        if row_id not in tracked_ids:
            row_dict = row.to_dict()
            row_dict['date_added'] = today_str
            new_records.append(row_dict)
            new_rows_count += 1

    # Append new records to our tracked dataframe
    if new_records:
        df_new = pd.DataFrame(new_records)
        df_tracked = pd.concat([df_tracked, df_new], ignore_index=True)
        print(f"Added {new_rows_count} new records to the tracker.")
    else:
        print("No new records found in the JSON.")

    # Save the updated tracking file
    df_tracked.to_csv(TRACKED_JSON_FILE, index=False)

    # ==========================================
    # 2. FETCH EXCEL DATA
    # ==========================================
    print("Fetching Excel data...")
    response_excel = requests.get(EXCEL_URL, headers=headers)
    response_excel.raise_for_status()
    df_excel = pd.read_excel(io.BytesIO(response_excel.content))

    # ==========================================
    # 3. FUZZY MERGE
    # ==========================================
    print("Standardizing text for fuzzy matching...")
    
    # Clean JSON text
    df_tracked['match_name'] = df_tracked.get('name', '').apply(clean_text)
    df_tracked['match_address'] = df_tracked.get('address', '').apply(clean_text)
    
    # Clean Excel text (Using actual headers from your MN_OCM file)
    df_excel['match_name'] = df_excel.get('Legal Business Name', '').apply(clean_text)
    df_excel['match_address'] = df_excel.get('Retail Site Address', '').apply(clean_text)
    
    # Create combined fuzzy keys
    df_tracked['fuzzy_key'] = df_tracked['match_name'] + " " + df_tracked['match_address']
    df_excel['fuzzy_key'] = df_excel['match_name'] + " " + df_excel['match_address']
    
    excel_keys = df_excel['fuzzy_key'].dropna().tolist()
    
    print("Performing fuzzy match...")
    combined_rows = []
    
    for _, json_row in df_tracked.iterrows():
        search_key = json_row['fuzzy_key']
        best_match = None
        
        if pd.notna(search_key) and str(search_key).strip() != "":
            best_match = process.extractOne(search_key, excel_keys, scorer=fuzz.token_set_ratio)
        
        if best_match and best_match[1] >= MATCH_THRESHOLD:
            excel_index = best_match[2]
            excel_row = df_excel.iloc[excel_index]
            
            merged_row = {**json_row.to_dict(), **excel_row.to_dict()}
            merged_row['Match_Score'] = best_match[1]
            combined_rows.append(merged_row)
        else:
            json_row_dict = json_row.to_dict()
            json_row_dict['Match_Score'] = 0
            combined_rows.append(json_row_dict)
            
    combined_df = pd.DataFrame(combined_rows)
    
    # Clean up temporary matching columns from output
    columns_to_drop = ['match_name', 'match_address', 'fuzzy_key']
    combined_df = combined_df.drop(columns=[col for col in columns_to_drop if col in combined_df.columns])
    
    combined_df.to_csv(FINAL_OUTPUT_FILE, index=False)
    print(f"Success! Final data saved to {FINAL_OUTPUT_FILE}")

    # ==========================================
    # 4. TWICE MONTHLY EXCEL EXPORT
    # ==========================================
    today_date = datetime.today()
    # Execute only on the 1st and 15th of the month
    if today_date.day in [1, 15]:
        excel_export_filename = f"tracked_json_export_{today_str}.xlsx"
        print(f"Today is the {today_date.day}. Exporting tracked JSON data to {excel_export_filename}...")
        
        # Drop the temporary fuzzy matching columns so the Excel file looks clean
        df_tracked_clean = df_tracked.drop(columns=[col for col in columns_to_drop if col in df_tracked.columns])
        df_tracked_clean.to_excel(excel_export_filename, index=False)
        
        print(f"Successfully exported {excel_export_filename}")

if __name__ == "__main__":
    main()
