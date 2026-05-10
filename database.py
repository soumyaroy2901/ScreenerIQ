import sqlite3
import pandas as pd
import os
from datetime import datetime

class DatabaseManager:
    def __init__(self, db_path="history.db"):
        self.db_path = db_path
        self._initialize_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _initialize_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Table for consensus stock picks
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_consensus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    nsecode TEXT,
                    name TEXT,
                    repetition_count INTEGER,
                    close REAL,
                    per_chg REAL,
                    screeners TEXT,
                    timestamp TEXT
                )
            """)
            
            # Table for individual screener performance
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    screener TEXT,
                    mean_return REAL,
                    pick_count INTEGER,
                    success_rate REAL,
                    timestamp TEXT
                )
            """)

            
            # Indexing for faster lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_consensus_date ON daily_consensus(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_performance_date ON daily_performance(date)")
            conn.commit()

    def save_daily_report(self, date_str, consensus_df, performance_df):
        """Saves daily analysis results to the database."""
        timestamp = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            # Check if data already exists for this date and delete to avoid duplicates
            conn.execute("DELETE FROM daily_consensus WHERE date = ?", (date_str,))
            conn.execute("DELETE FROM daily_performance WHERE date = ?", (date_str,))
            
            # Define allowed columns for consensus
            con_cols = ['date', 'nsecode', 'name', 'repetition_count', 'close', 'per_chg', 'screeners', 'timestamp']
            # Define allowed columns for performance
            perf_cols = ['date', 'screener', 'mean_return', 'pick_count', 'success_rate', 'timestamp']


            # Prepare DataFrames for SQL
            con_to_save = consensus_df.copy()
            con_to_save['date'] = date_str
            con_to_save['timestamp'] = timestamp
            
            perf_to_save = performance_df.copy()
            perf_to_save['date'] = date_str
            perf_to_save['timestamp'] = timestamp
            
            # Handle column name mapping if necessary
            if 'mean' in perf_to_save.columns:
                perf_to_save = perf_to_save.rename(columns={'mean': 'mean_return'})
            if 'count' in perf_to_save.columns:
                perf_to_save = perf_to_save.rename(columns={'count': 'pick_count'})
            if 'Screener' in perf_to_save.columns:
                perf_to_save = perf_to_save.rename(columns={'Screener': 'screener'})

            # Filter only known columns to avoid sqlite3.OperationalError with 'Unnamed: 0' etc.
            con_to_save = con_to_save[[c for c in con_cols if c in con_to_save.columns]]
            perf_to_save = perf_to_save[[c for c in perf_cols if c in perf_to_save.columns]]

            # Save to SQL
            con_to_save.to_sql('daily_consensus', conn, if_exists='append', index=False)
            perf_to_save.to_sql('daily_performance', conn, if_exists='append', index=False)

            conn.commit()

    def get_all_dates(self):
        """Returns a list of all unique dates in the database."""
        with self._get_connection() as conn:
            query = "SELECT DISTINCT date FROM daily_consensus ORDER BY date DESC"
            return [row[0] for row in conn.execute(query).fetchall()]

    def get_daily_data(self, date_str):
        """Fetches both consensus and performance data for a specific date."""
        with self._get_connection() as conn:
            con_df = pd.read_sql("SELECT * FROM daily_consensus WHERE date = ?", conn, params=(date_str,))
            perf_df = pd.read_sql("SELECT * FROM daily_performance WHERE date = ?", conn, params=(date_str,))
            
            # Rename back for app compatibility
            if not perf_df.empty:
                perf_df = perf_df.rename(columns={'screener': 'Screener', 'mean_return': 'mean', 'pick_count': 'count'})
            
            return con_df, perf_df

    def get_historical_performance(self):
        """Returns aggregated performance data across all dates using weighted averages."""
        with self._get_connection() as conn:
            query = """
                SELECT 
                    screener as Screener, 
                    SUM(success_rate * pick_count) / SUM(pick_count) as avg_success_rate,
                    SUM(mean_return * pick_count) / SUM(pick_count) as avg_realized_return, 
                    SUM(pick_count) as total_picks
                FROM daily_performance
                GROUP BY screener
                HAVING total_picks > 0
                ORDER BY avg_success_rate DESC, avg_realized_return DESC
            """
            return pd.read_sql(query, conn)


    def get_synergy_data(self, date_str):
        """Fetches data specifically for synergy analysis."""
        with self._get_connection() as conn:
            return pd.read_sql("SELECT nsecode, per_chg, screeners, repetition_count FROM daily_consensus WHERE date = ?", conn, params=(date_str,))

    def clear_all_history(self):
        """Wipes the database tables."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM daily_consensus")
            conn.execute("DELETE FROM daily_performance")
            conn.commit()
