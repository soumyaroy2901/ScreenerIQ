import json
import os
import pandas as pd
from database import DatabaseManager

def migrate():
    json_path = "history.json"
    db_path = "history.db"
    
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found. Nothing to migrate.")
        return

    print(f"Reading {json_path}...")
    with open(json_path, 'r') as f:
        try:
            history = json.load(f)
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            return

    db = DatabaseManager(db_path)
    
    dates = sorted(history.keys())
    print(f"Found {len(dates)} days of data. Starting migration...")

    for date_str in dates:
        print(f"Migrating {date_str}...")
        day_data = history[date_str]
        
        # Extract consensus
        con_df = pd.DataFrame(day_data.get('consensus', []))
        
        # Extract performance
        perf_data = day_data.get('performance', [])
        perf_df = pd.DataFrame(perf_data)
        
        if not con_df.empty:
            # If performance data is missing success_rate, backfill it from consensus
            if not perf_df.empty and 'success_rate' not in perf_df.columns:
                # We need to map stocks to screeners to find the success rate
                screener_stats = []
                # con_df has 'screeners' (comma separated string) and 'per_chg'
                for _, row in con_df.iterrows():
                    sc_list = str(row.get('screeners', '')).split(', ')
                    for sc in sc_list:
                        if sc.strip():
                            screener_stats.append({
                                "Screener": sc.strip(),
                                "is_success": 1 if row.get('per_chg', 0) > 0 else 0
                            })
                
                if screener_stats:
                    stats_df = pd.DataFrame(screener_stats)
                    backfilled_success = stats_df.groupby('Screener')['is_success'].mean().reset_index()
                    backfilled_success.columns = ['Screener', 'success_rate']
                    
                    # Merge into perf_df
                    if 'Screener' not in perf_df.columns and 'screener_name' in perf_df.columns:
                        perf_df = perf_df.rename(columns={'screener_name': 'Screener'})
                    
                    perf_df = pd.merge(perf_df, backfilled_success, on='Screener', how='left')
            
            db.save_daily_report(date_str, con_df, perf_df)
        else:
            print(f"  Warning: Skipping {date_str} due to missing consensus data.")


    print("\n✅ Migration complete!")
    print(f"Data is now in {db_path}. You can now safely delete {json_path} or rename it to history_backup.json.")

if __name__ == "__main__":
    migrate()
