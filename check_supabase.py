from database import DatabaseManager
import pandas as pd

SUPABASE_URL = "https://cqwtfwgkbzqsygcjdboa.supabase.co"
SUPABASE_KEY = "sb_publishable_66GxMGwdnrIpl7Fi-nxsWA_nIceE1Un"

def check():
    db = DatabaseManager(SUPABASE_URL, SUPABASE_KEY)
    
    # Try with a larger limit
    resp = db.supabase.table("daily_consensus").select("date").limit(10000).execute()
    if resp.data:
        df = pd.DataFrame(resp.data)
        print("Dates found in Supabase (with 10000 limit):")
        print(df['date'].unique())
        print(f"Total rows fetched: {len(df)}")
    else:
        print("No data found.")

if __name__ == "__main__":
    check()
