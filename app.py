import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import re
import html
from database import DatabaseManager
import os
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go
import json

# Fix pandas future warning



# --- CONFIGURATION ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(APP_DIR, "history.db")
DEFAULT_EXCEL = os.path.join(APP_DIR, "StocksScreener.xlsx")
IST = pytz.timezone('Asia/Kolkata')

# --- NSE HOLIDAYS 2026 ---
NSE_HOLIDAYS_2026 = [
    "2026-01-26", # Republic Day
    "2026-03-03", # Holi
    "2026-03-26", # Ram Navami
    "2026-03-31", # Mahavir Jayanti
    "2026-04-03", # Good Friday
    "2026-04-14", # Ambedkar Jayanti
    "2026-05-01", # Maharashtra Day
    "2026-05-28", # Bakri Id
    "2026-06-26", # Muharram
    "2026-09-14", # Ganesh Chaturthi
    "2026-10-02", # Gandhi Jayanti
    "2026-10-20", # Dasara
    "2026-11-10", # Diwali
    "2026-11-24", # Guru Nanak Jayanti
    "2026-12-25", # Christmas
]

def is_trading_day(dt):
    # Weekends (Saturday=5, Sunday=6)
    if dt.weekday() >= 5:
        return False
    # Holidays
    date_str = dt.strftime("%Y-%m-%d")
    if date_str in NSE_HOLIDAYS_2026:
        return False
    return True

def get_last_trading_day(dt):
    curr = dt - timedelta(days=1)
    while not is_trading_day(curr):
        curr -= timedelta(days=1)
    return curr

# Initialize Database
db = DatabaseManager(DB_FILE)


# --- CSS STYLING ---
def apply_custom_styles():
    st.markdown("""
        <style>
        /* Premium Light Mode Styling */
        .main { background-color: #f8fafc !important; color: #1e293b !important; }
        header[data-testid="stHeader"] { background: rgba(255,255,255,0) !important; }
        
        /* High Contrast Metric Cards (Light) */
        [data-testid="stMetricValue"] {
            color: #0f172a !important;
            font-size: 2rem !important;
            font-weight: 800 !important;
        }
        [data-testid="stMetricLabel"] p {
            color: #475569 !important;
            font-size: 0.9rem !important;
            font-weight: 700 !important;
            text-transform: uppercase !important;
            margin-bottom: 8px !important;
        }
        
        div[data-testid="metric-container"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            padding: 25px !important;
            border-radius: 15px !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06) !important;
            margin-bottom: 10px !important;
        }
        
        /* Delta Visibility (Light Mode) */
        [data-testid="stMetricDelta"] {
            background-color: rgba(16, 185, 129, 0.1) !important;
            padding: 4px 10px !important;
            border-radius: 6px !important;
            font-weight: 700 !important;
        }
        [data-testid="stMetricDelta"] div[data-direction="up"] {
            color: #059669 !important;
        }
        [data-testid="stMetricDelta"] div[data-direction="down"] {
            color: #dc2626 !important;
        }
        
        .stButton>button { background-color: #10b981; color: white; border-radius: 8px; border: none; padding: 10px 24px; font-weight: 600; }
        .stButton>button:hover { background-color: #059669; border: none; }
        
        /* Light Sidebar */
        section[data-testid="stSidebar"] {
            background-color: #ffffff !important;
            border-right: 1px solid #e2e8f0 !important;
        }
        
        /* Light Expanders */
        div[data-testid="stExpander"] {
            background-color: #ffffff !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 12px !important;
        }
        
        .status-ready { color: #059669; font-weight: bold; }
        .status-pending { color: #d97706; font-weight: bold; }
        
        /* Prediction Success Pill (Light) */
        .success-pill {
            background-color: #d1fae5 !important;
            color: #065f46 !important;
            padding: 2px 8px !important;
            border-radius: 4px !important;
            font-size: 0.75rem !important;
            font-weight: 600 !important;
        }
        </style>
    """, unsafe_allow_html=True)

# --- PREDICTION SUCCESS LOGIC ---
def calculate_prediction_success(today_str):
    all_dates = db.get_all_dates() # Returns sorted dates DESC
    if len(all_dates) < 2:
        return None, None
    
    # Find the previous date relative to today_str
    try:
        current_idx = all_dates.index(today_str)
        if current_idx == len(all_dates) - 1: return None, None # No earlier date
        prev_date = all_dates[current_idx + 1]
    except ValueError:
        # today_str not in DB yet (maybe running analysis right now)
        prev_date = all_dates[0] if all_dates else None
        if not prev_date or prev_date == today_str: return None, None

    prev_con, _ = db.get_daily_data(prev_date)
    today_con, _ = db.get_daily_data(today_str)

    
    if prev_con.empty or today_con.empty:
        return None, None
        
    # Match stocks by symbol
    cols_to_use = ['nsecode', 'close']
    if 'screeners' in prev_con.columns:
        cols_to_use.append('screeners')
    elif 'screener_name' in prev_con.columns:
        prev_con = prev_con.rename(columns={'screener_name': 'screeners'})
        cols_to_use.append('screeners')
    else:
        return None, None # Cannot analyze without screener mapping
        
    merged = pd.merge(
        prev_con[cols_to_use], 
        today_con[['nsecode', 'close']], 
        on='nsecode', 
        suffixes=('_prev', '_today')
    )
    
    if merged.empty:
        return None, None
        
    merged['realized_return'] = (merged['close_today'] / merged['close_prev'] - 1) * 100
    merged['is_success'] = merged['realized_return'] > 0
    
    # Aggregate by screener
    screener_results = []
    # We need to explode the screeners list from yesterday
    for _, row in merged.iterrows():
        sc_list = str(row['screeners']).split(', ')
        for sc in sc_list:
            screener_results.append({
                "Screener": sc,
                "Return": row['realized_return'],
                "Success": 1 if row['is_success'] else 0
            })
            
    perf_df = pd.DataFrame(screener_results)
    success_report = perf_df.groupby('Screener').agg(
        avg_realized_return=('Return', 'mean'),
        success_rate=('Success', 'mean'),
        pick_count=('Success', 'count')
    ).sort_values('avg_realized_return', ascending=False)
    
    return success_report, prev_date

def calculate_historical_success():
    return calculate_all_time_prediction_success()

def calculate_all_time_prediction_success():
    all_dates = db.get_all_dates() # Sorted DESC
    if len(all_dates) < 2:
        return None
    
    all_reports = []
    # all_dates is [D_now, D_prev, D_prev_prev, ...]
    for i in range(len(all_dates) - 1):
        target_date = all_dates[i]
        report, _ = calculate_prediction_success(target_date)
        if report is not None:
            all_reports.append(report.reset_index())
            
    if not all_reports:
        return None
        
    combined = pd.concat(all_reports)
    combined['weighted_return'] = combined['avg_realized_return'] * combined['pick_count']
    combined['weighted_success'] = combined['success_rate'] * combined['pick_count']
    
    final = combined.groupby('Screener').agg(
        total_return=('weighted_return', 'sum'),
        total_success=('weighted_success', 'sum'),
        total_picks=('pick_count', 'sum')
    )
    final['avg_realized_return'] = final['total_return'] / final['total_picks']
    final['avg_success_rate'] = final['total_success'] / final['total_picks']
    return final.sort_values('avg_success_rate', ascending=False).reset_index()


# --- UTILITIES ---
def get_current_ist_time():
    return datetime.now(IST)

def save_to_history(date_str, consensus_df, screener_perf):
    db.save_daily_report(date_str, consensus_df, screener_perf)


def extract_scan_clause(url, session):
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        pattern = r':scan-json="(.*?)"'
        match = re.search(pattern, response.text)
        if match:
            json_str = html.unescape(match.group(1))
            scan_data = json.loads(json_str)
            # Try multiple common keys for resilience
            for key in ['atlas_query', 'scan_clause', 'query']:
                val = scan_data.get(key)
                if val: return val.strip()
        return None
    except Exception as e:
        st.error(f"⚠️ Failed to parse screener logic for {url}: {e}")
        return None

# --- CORE ANALYSIS ENGINE ---
def run_full_analysis(df_input):
    CHARTINK_URL = "https://chartink.com/screener/process"
    session = requests.Session()
    
    # Handshake
    try:
        resp = session.get("https://chartink.com/screener/", timeout=10)
        csrf_token = BeautifulSoup(resp.text, "html.parser").find("meta", {"name": "csrf-token"})["content"]
        headers = {"x-csrf-token": csrf_token, "x-requested-with": "XMLHttpRequest"}
    except Exception as e:
        return None, None, f"Handshake failed: {e}"

    all_results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(df_input)
    for index, row in df_input.iterrows():
        name = str(row['SCAN STOCKS']).strip()
        url = str(row['LINK']).strip()
        clause = str(row.get('Scan Clause', '')).strip()
        
        status_text.text(f"Scanning [{index+1}/{total}]: {name}...")
        progress_bar.progress((index + 1) / total)
        
        if not clause or clause == 'nan' or len(clause) < 10:
            clause = extract_scan_clause(url, session)
            if not clause: continue
        else:
            if clause.startswith('"') and clause.endswith('"'): clause = clause[1:-1]

        try:
            response = session.post(CHARTINK_URL, data={"scan_clause": clause}, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json().get("data", [])
                if data:
                    res_df = pd.DataFrame(data)
                    res_df['screener_name'] = name
                    all_results.append(res_df)
            time.sleep(0.3)
        except Exception: continue
    
    if not all_results:
        return None, None, "No results found."

    master_df = pd.concat(all_results)
    
    # Consensus Logic
    counts = master_df['nsecode'].value_counts().reset_index()
    counts.columns = ['nsecode', 'repetition_count']
    screeners_grp = master_df.groupby('nsecode')['screener_name'].unique().apply(lambda x: ', '.join(x)).reset_index()
    screeners_grp.columns = ['nsecode', 'screeners']
    
    details = master_df.groupby('nsecode').agg({'name': 'first', 'close': 'last', 'per_chg': 'last'}).reset_index()
    consensus_df = pd.merge(details, counts, on='nsecode')
    consensus_df = pd.merge(consensus_df, screeners_grp, on='nsecode')
    consensus_df = consensus_df.sort_values(by='repetition_count', ascending=False)

    # Performance Logic (Per Screener)
    # We use the 'per_chg' column from Chartink (which is Day Change %)
    screener_rows = []
    for _, row in master_df.iterrows():
        screener_rows.append({
            "Screener": row['screener_name'],
            "Change %": row['per_chg'],
            "Is Positive": 1 if row['per_chg'] > 0 else 0
        })
    perf_df = pd.DataFrame(screener_rows)
    screener_perf = perf_df.groupby('Screener').agg(
        mean=('Change %', 'mean'),
        count=('Change %', 'count'),
        success_rate=('Is Positive', 'mean')
    ).reset_index()

    return consensus_df, screener_perf, None


# --- STREAMLIT UI ---
def main():
    st.set_page_config(page_title="Commander Desk v5", page_icon="📡", layout="wide")
    def get_last_trading_day():
        now = datetime.now(IST)
        today_str = now.strftime('%Y-%m-%d')
        today_weekday = now.weekday() # 0=Mon, 6=Sun
        
        is_trading_day = (today_weekday < 5) and (today_str not in NSE_HOLIDAYS_2026)
        
        # Time check (9:15 AM to 3:30 PM)
        market_open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        is_market_open = is_trading_day and (market_open_time <= now <= market_close_time)

        # Get last trading day by looking backwards
        search_date = now - timedelta(days=1)
        while True:
            sw = search_date.weekday()
            sd_str = search_date.strftime('%Y-%m-%d')
            if sw < 5 and sd_str not in NSE_HOLIDAYS_2026:
                last_day_str = sd_str
                break
            search_date -= timedelta(days=1)
            
        # If today is a trading day and it's after market close, today is the primary display date
        if is_trading_day and now.time() >= datetime.strptime("15:30", "%H:%M").time():
            return True, is_market_open, today_str, today_str, last_day_str
        
        return is_trading_day, is_market_open, last_day_str, today_str, last_day_str
    
    apply_custom_styles()
    
    now = get_current_ist_time()
    today_str = now.strftime("%Y-%m-%d")
    all_dates = db.get_all_dates()
    
    is_trading_day, is_market_open, last_trading_day_str, today_str, _ = get_last_trading_day()
    
    # --- SIDEBAR ---
    st.sidebar.title("📡 CONTROL CENTER")
    st.sidebar.info(f"IST: {now.strftime('%H:%M:%S')}")
    
    # Sidebar Market Status
    if is_market_open:
        st.sidebar.success("🟢 MARKET OPEN")
    else:
        st.sidebar.error("🔴 MARKET CLOSED")

    if today_str in all_dates:
        analysis_status = "READY"
        status_color = "status-ready"
    elif not is_trading_day:
        analysis_status = "NSE HOLIDAY / WEEKEND"
        status_color = "status-pending"
    else:
        analysis_status = "PENDING"
        status_color = "status-pending"

    st.sidebar.markdown(f"Analysis: <span class='{status_color}'>{analysis_status}</span>", unsafe_allow_html=True)
    auto_trigger = st.sidebar.checkbox("Auto-Trigger Analysis at 5 PM", value=True)

    
    # Check for Auto-Trigger (Double-lock to prevent race conditions across tabs)
    if auto_trigger and is_trading_day and analysis_status == "PENDING" and now.hour >= 17:
        # Re-verify status from DB to ensure another tab didn't just finish it
        if today_str not in db.get_all_dates():
            st.sidebar.warning("🕒 It's past 5 PM IST. Auto-triggering analysis...")
            try:
                if os.path.exists(DEFAULT_EXCEL):
                    df_input = pd.read_excel(DEFAULT_EXCEL)
                    # Deduplicate screeners if any
                    df_input = df_input.drop_duplicates(subset=['url'])
                    
                    con_df, perf_df, err = run_full_analysis(df_input)
                    if not err:
                        save_date = today_str if is_trading_day else last_trading_day_str
                        db.save_daily_report(save_date, con_df, perf_df)
                        st.rerun()
                    else:
                        st.sidebar.error(err)
                else:
                    st.sidebar.error("❌ StocksScreener.xlsx not found.")
            except Exception as e:
                st.sidebar.error(f"❌ Analysis failed: {e}")

    st.sidebar.divider()
    page = st.sidebar.radio("Navigate", ["Command Desk", "Performance Analytics", "Historical Trends", "Settings"])
    
    # --- PAGE: COMMAND DESK ---
    if page == "Command Desk":
        st.title("📡 Commander Desk - Daily Pulse")
        
        display_date = today_str
        is_fallback = False
        
        if today_str not in all_dates:
            if all_dates:
                display_date = all_dates[0]
                is_fallback = True
                if not is_trading_day:
                    if last_trading_day_str not in all_dates:
                        st.warning(f"⚠️ Missing data for the last trading day (**{last_trading_day_str}**). Run analysis now to capture results.")
                    st.info(f"🏖️ Market is closed today ({today_str}). Showing latest available data from **{display_date}**.")
                else:
                    st.info(f"📌 Today ({today_str}) is not yet analyzed. Showing latest available data from **{display_date}**.")
            else:
                st.info("👋 No analysis history found. Analysis is automated daily at 5 PM IST.")
                st.stop() # Stop here if no data at all
        
        # Fetch data for display_date
        con_df, perf_df = db.get_daily_data(display_date)
        
        # Sort performance for metrics
        if not perf_df.empty:
            perf_df = perf_df.sort_values('mean', ascending=False)
        
        if not con_df.empty:
            # Prediction Success Calculation (How yesterday's picks did on display_date)
            success_report, prev_date = calculate_prediction_success(display_date)


            overall_success_rate = success_report['success_rate'].mean() * 100 if success_report is not None else 0
            
            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Top Conviction", con_df.iloc[0]['nsecode'] if not con_df.empty else "N/A", f"{con_df.iloc[0]['repetition_count']} Hits" if not con_df.empty else "0 Hits")
            m2.metric("Best Strategy", perf_df.iloc[0]['Screener'] if not perf_df.empty else "N/A", f"{perf_df.iloc[0]['mean']:.2f}% Today" if not perf_df.empty else "0.00% Today")
            m3.metric("Prediction Success", f"{overall_success_rate:.1f}%", f"vs {prev_date}" if prev_date else "No History")
            m4.metric("Market Sentiment", "Bullish" if con_df['per_chg'].mean() > 0 else "Bearish", f"{con_df['per_chg'].mean():.2f}% Avg")

            
            st.subheader(f"🔥 High Conviction Consensus ({display_date})")
            # Resilient column selection
            display_cols = ['nsecode', 'name', 'repetition_count', 'close', 'per_chg']
            if 'screeners' in con_df.columns: display_cols.append('screeners')
            elif 'screener_name' in con_df.columns:
                con_df = con_df.rename(columns={'screener_name': 'screeners'})
                display_cols.append('screeners')
            
            filtered_con = con_df[con_df['repetition_count'] >= 3]
            st.dataframe(filtered_con[display_cols], width='stretch', height=600, hide_index=True)

    elif page == "Performance Analytics":
        st.title("🎯 Strategy Performance Center")
        
        display_date = today_str if today_str in all_dates else (all_dates[0] if all_dates else None)
        
        if not display_date:
            st.warning("No analysis history found. Run a scan to generate performance data.")
        else:
            success_report, prev_date = calculate_prediction_success(display_date)
            historical_report = calculate_historical_success()


            with st.expander("ℹ️ Understanding Performance Metrics", expanded=False):
                st.markdown("""
                - **Daily Prediction Success**: How yesterday's specific picks performed in today's session.
                - **All-Time Historical Leaderboard**: The aggregated performance of strategies across all days in your history vault.
                - **Hit Rate**: % of picks that ended higher than their entry price.
                """)

            col_a, col_b = st.columns(2)
            
            with col_a:
                st.subheader(f"📅 Daily Success Pulse (Vs {prev_date})")
                if success_report is not None:
                    # Keep numeric for sorting, use column_config for display
                    disp_daily = success_report.reset_index()
                    disp_daily['success_rate'] = disp_daily['success_rate'] * 100
                    
                    st.dataframe(
                        disp_daily, 
                        use_container_width=True,
                        column_config={
                            "success_rate": st.column_config.NumberColumn("Success Rate", format="%.1f%%"),
                            "avg_realized_return": st.column_config.NumberColumn("Avg Return", format="%.2f%%"),
                            "pick_count": st.column_config.NumberColumn("Picks")
                        },
                        hide_index=True
                    )

                else:
                    st.info("Daily success analysis requires at least 2 consecutive days of data.")
            
            with col_b:
                st.subheader("🏛️ Strategic Leaderboard (Next-Day)")
                if historical_report is not None and not historical_report.empty:
                    st.caption(f"Note: Picks from {today_str} are PENDING Monday's results.")
                    # Keep numeric for sorting
                    disp_hist = historical_report.copy()
                    disp_hist['avg_success_rate'] = disp_hist['avg_success_rate'] * 100
                    
                    st.dataframe(
                        disp_hist, 
                        use_container_width=True,
                        column_config={
                            "avg_success_rate": st.column_config.NumberColumn("Historical Success", format="%.1f%%"),
                            "avg_realized_return": st.column_config.NumberColumn("Avg Return", format="%.2f%%"),
                            "total_picks": st.column_config.NumberColumn("Total Picks")
                        },
                        hide_index=True
                    )

                else:
                    st.info("Historical analysis builds up as you store more daily reports.")


    # --- PAGE: HISTORICAL TRENDS ---
    elif page == "Historical Trends":
        st.title("📈 Strategic Intelligence - History")
        
        historical_report = calculate_historical_success()
        
        if historical_report is not None and not historical_report.empty:
            st.subheader("🏛️ Historical Prediction Leaderboard (Next-Day)")
            st.caption(f"Aggregated performance across {len(all_dates)-1} historical trading sessions.")
            # Format and show top 10 historical
            disp_hist = historical_report.head(10).copy()
            disp_hist['avg_realized_return_val'] = disp_hist['avg_realized_return'] # Keep numeric for chart
            
            fig = px.bar(disp_hist, x='avg_realized_return', y='Screener', orientation='h', 
                         title="Top 10 Screeners by Historical Avg Return",
                         color='avg_realized_return', color_continuous_scale='Greens')
            st.plotly_chart(fig, use_container_width=True)
        
        st.divider()
        if not all_dates:
            st.warning("No historical data found.")
        else:
            st.subheader("🔍 Daily Snapshot Lookup")
            selected_date = st.selectbox("Select Date to View Details", all_dates)
            con_df, perf_df = db.get_daily_data(selected_date)
            
            if not perf_df.empty:
                st.write(f"Showing performance for: {selected_date}")
                # Daily performance chart
                fig_daily = px.bar(perf_df.sort_values('mean', ascending=False).head(10), 
                                  x='mean', y='Screener', orientation='h',
                                  title=f"Daily Leaders ({selected_date})",
                                  color='mean', color_continuous_scale='Blues')
                st.plotly_chart(fig_daily, use_container_width=True)

            # Bug 1: Consistency Tracker (Multi-line)
            st.divider()
            st.subheader("🧬 Multi-Strategy Consistency Tracker")
            
            with db._get_connection() as conn:
                big_perf = pd.read_sql("SELECT * FROM daily_performance", conn)
                big_perf = big_perf.rename(columns={'screener': 'Screener', 'mean_return': 'mean', 'date': 'Date'})

            all_strategies = sorted(big_perf['Screener'].unique())
            # Default to top 5 historical strategies
            default_strats = historical_report.head(5)['Screener'].tolist() if historical_report is not None else []
            
            target_strategies = st.multiselect("Pick Strategies to Compare Trend", all_strategies, default=default_strats)
            
            if target_strategies:
                strat_trend = big_perf[big_perf['Screener'].isin(target_strategies)].sort_values('Date')
                fig2 = px.line(strat_trend, x='Date', y='mean', color='Screener', markers=True, 
                              title="Strategy Performance Consistency Over Time")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Select one or more strategies above to see the trend graph.")


    # --- PAGE: SETTINGS ---
    elif page == "Settings":
        st.title("⚙️ System Settings")
        
        st.subheader("🛠️ Administrative Actions")
        with st.expander("Run Manual Analysis"):
            admin_pwd = st.text_input("Admin Password", type="password", key="admin_pwd")
            if admin_pwd == "Trade@123":
                st.divider()
                if st.button("🚀 Trigger Full Analysis"):
                    # Vault Protection Check
                    if is_trading_day and now.time() < datetime.strptime("15:30", "%H:%M").time():
                        st.error("🛑 Vault Protection: You cannot save analysis to the database during live market hours (before 15:30 IST). This prevents intraday noise from corrupting your historical intelligence.")
                    elif os.path.exists(DEFAULT_EXCEL):
                        with st.spinner("Executing manual scan..."):
                            df_input = pd.read_excel(DEFAULT_EXCEL)
                            con_df, perf_df, err = run_full_analysis(df_input)
                            if not err:
                                t_day, is_mo, _, t_str, l_str = get_last_trading_day()
                                save_date = t_str if t_day else l_str
                                db.save_daily_report(save_date, con_df, perf_df)
                                st.success(f"Analysis complete and stored for {save_date}!")
                                st.rerun()
                            else:
                                st.error(err)
                    else:
                        st.error("Missing StocksScreener.xlsx")
                
                if st.button("🗑️ Clear History Database"):
                    db.clear_all_history()
                    st.success("History cleared.")
                    st.rerun()
            elif admin_pwd:
                st.error("Access Denied: Incorrect Password")

        st.divider()
        st.subheader("📂 Data Vault Information")
        st.write(f"App Directory: `{APP_DIR}`")
        st.write(f"Database File: `{DB_FILE}`")


if __name__ == "__main__":
    main()
