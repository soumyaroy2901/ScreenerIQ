import pandas as pd
from supabase import create_client, Client
from datetime import datetime

class DatabaseManager:
    def __init__(self, url, key):
        self.url = url
        self.key = key
        self.supabase: Client = create_client(self.url, self.key)

    def save_daily_report(self, date_str, consensus_df, performance_df):
        """Saves daily analysis results to Supabase."""
        timestamp = datetime.now().isoformat()
        
        # 1. Clear existing data for this date to avoid duplicates
        self.supabase.table("daily_consensus").delete().eq("date", date_str).execute()
        self.supabase.table("daily_performance").delete().eq("date", date_str).execute()
        
        # 2. Prepare Consensus Data
        if not consensus_df.empty:
            con_to_save = consensus_df.copy()
            con_to_save['date'] = date_str
            # Ensure only columns existing in Supabase are sent
            allowed_con = ['date', 'nsecode', 'name', 'repetition_count', 'close', 'per_chg', 'screeners']
            con_to_save = con_to_save[[c for c in allowed_con if c in con_to_save.columns]]
            
            # Convert to list of dicts and insert in chunks (Supabase limit)
            records = con_to_save.to_dict('records')
            # Chunking for safety (e.g., 500 records at a time)
            for i in range(0, len(records), 500):
                self.supabase.table("daily_consensus").insert(records[i:i+500]).execute()

        # 3. Prepare Performance Data
        if not performance_df.empty:
            perf_to_save = performance_df.copy()
            perf_to_save['date'] = date_str
            
            # Mapping names to match Supabase schema
            if 'mean' in perf_to_save.columns: perf_to_save = perf_to_save.rename(columns={'mean': 'mean_return'})
            if 'count' in perf_to_save.columns: perf_to_save = perf_to_save.rename(columns={'count': 'pick_count'})
            if 'Screener' in perf_to_save.columns: perf_to_save = perf_to_save.rename(columns={'Screener': 'screener'})
            
            allowed_perf = ['date', 'screener', 'mean_return', 'pick_count', 'success_rate']
            perf_to_save = perf_to_save[[c for c in allowed_perf if c in perf_to_save.columns]]
            
            self.supabase.table("daily_performance").insert(perf_to_save.to_dict('records')).execute()

    def get_all_dates(self):
        """Returns a list of all unique dates in Supabase."""
        # Query the performance table instead of consensus, as it has fewer rows per date
        response = self.supabase.table("daily_performance").select("date").execute()
        if not response.data:
            return []
        df = pd.DataFrame(response.data)
        return sorted(df['date'].unique().tolist(), reverse=True)

    def get_daily_data(self, date_str):
        """Fetches data from Supabase for a specific date."""
        # Increase limit to 5000 to ensure we get all stocks for the day (usually ~1500)
        con_resp = self.supabase.table("daily_consensus").select("*").eq("date", date_str).limit(5000).execute()
        perf_resp = self.supabase.table("daily_performance").select("*").eq("date", date_str).execute()
        
        con_df = pd.DataFrame(con_resp.data) if con_resp.data else pd.DataFrame()
        perf_df = pd.DataFrame(perf_resp.data) if perf_resp.data else pd.DataFrame()
        
        # Rename back for app compatibility
        if not perf_df.empty:
            perf_df = perf_df.rename(columns={'screener': 'Screener', 'mean_return': 'mean', 'pick_count': 'count'})
            
        return con_df, perf_df

    def get_historical_performance(self):
        """Returns aggregated performance data from Supabase."""
        # Supabase doesn't support complex aggregations like SUM(x*y)/SUM(y) easily in one select
        # So we fetch all data and aggregate in Pandas
        resp = self.supabase.table("daily_performance").select("*").execute()
        if not resp.data:
            return pd.DataFrame()
        
        df = pd.DataFrame(resp.data)
        # Weighting logic
        df['weighted_success'] = df['success_rate'] * df['pick_count']
        df['weighted_return'] = df['mean_return'] * df['pick_count']
        
        agg = df.groupby('screener').agg({
            'weighted_success': 'sum',
            'weighted_return': 'sum',
            'pick_count': 'sum'
        })
        
        agg['avg_success_rate'] = agg['weighted_success'] / agg['pick_count']
        agg['avg_realized_return'] = agg['weighted_return'] / agg['pick_count']
        
        return agg.reset_index().rename(columns={'screener': 'Screener', 'pick_count': 'total_picks'}).sort_values('avg_success_rate', ascending=False)

    def clear_all_history(self):
        """Wipes the Supabase tables (Use with caution)."""
        # Supabase requires a filter for deletes usually, or use a RPC
        self.supabase.table("daily_consensus").delete().neq("id", -1).execute()
        self.supabase.table("daily_performance").delete().neq("id", -1).execute()
