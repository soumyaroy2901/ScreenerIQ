import sqlite3
import pandas as pd
from database import DatabaseManager
import os

# --- CONFIG ---
DB_FILE = "history.db"
SUPABASE_URL = "https://cqwtfwgkbzqsygcjdboa.supabase.co"
SUPABASE_KEY = "sb_publishable_66GxMGwdnrIpl7Fi-nxsWA_nIceE1Un"

def migrate():
    if not os.path.exists(DB_FILE):
        print(f"❌ {DB_FILE} not found. Nothing to migrate.")
        return

    print(f"🔄 Starting migration from {DB_FILE} to Supabase...")
    
    # 1. Connect to SQLite
    sqlite_conn = sqlite3.connect(DB_FILE)
    
    # 2. Initialize Supabase Manager
    db = DatabaseManager(SUPABASE_URL, SUPABASE_KEY)
    
    # 3. Migrate Consensus Data
    print("📋 Migrating Consensus Data...")
    consensus_df = pd.read_sql("SELECT * FROM daily_consensus", sqlite_conn)
    if not consensus_df.empty:
        # Get unique dates to upload one by one (to handle saving logic in DatabaseManager)
        dates = consensus_df['date'].unique()
        for d in dates:
            print(f"  -> Uploading date: {d}")
            day_con = consensus_df[consensus_df['date'] == d]
            
            # Fetch performance for the same day
            day_perf = pd.read_sql(f"SELECT * FROM daily_performance WHERE date = '{d}'", sqlite_conn)
            
            # Save using our existing logic (which handles cleaning and formatting)
            db.save_daily_report(d, day_con, day_perf)
            print(f"  ✅ Uploaded {len(day_con)} picks and {len(day_perf)} strategy results.")

    print("\n✨ Migration complete! Your data is now in the cloud.")
    sqlite_conn.close()

if __name__ == "__main__":
    migrate()
