import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import re
import html
import json
import os
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURATION ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(APP_DIR, "history.json")
DEFAULT_EXCEL = os.path.join(APP_DIR, "StocksScreener.xlsx")
IST = pytz.timezone('Asia/Kolkata')

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
def calculate_prediction_success(history, today_str):
    dates = sorted(history.keys())
    if len(dates) < 2:
        return None, None
    
    # Find the previous date
    try:
        current_idx = dates.index(today_str)
        if current_idx == 0: return None, None
        prev_date = dates[current_idx - 1]
    except ValueError:
        prev_date = dates[-1] if dates else None
        if not prev_date or prev_date == today_str: return None, None

    prev_con = pd.DataFrame(history[prev_date]['consensus'])
    today_con = pd.DataFrame(history[today_str]['consensus'])
    
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

def calculate_historical_success(history):
    dates = sorted(history.keys())
    if len(dates) < 2:
        return None
        
    all_pairs_results = []
    
    for i in range(len(dates) - 1):
        d1 = dates[i]
        d2 = dates[i+1]
        
        d1_con = pd.DataFrame(history[d1]['consensus'])
        d2_con = pd.DataFrame(history[d2]['consensus'])
        
        if d1_con.empty or d2_con.empty: continue
            
        # Match stocks by symbol
        sc_col = 'screeners' if 'screeners' in d1_con.columns else 'screener_name'
        if sc_col not in d1_con.columns: continue
            
        merged = pd.merge(
            d1_con[['nsecode', 'close', sc_col]], 
            d2_con[['nsecode', 'close']], 
            on='nsecode', 
            suffixes=('_prev', '_today')
        )
        
        if merged.empty: continue
            
        merged['realized_return'] = (merged['close_today'] / merged['close_prev'] - 1) * 100
        merged['is_success'] = merged['realized_return'] > 0
        
        for _, row in merged.iterrows():
            sc_list = str(row[sc_col]).split(', ')
            for sc in sc_list:
                all_pairs_results.append({
                    "Screener": sc,
                    "Return": row['realized_return'],
                    "Success": 1 if row['is_success'] else 0
                })
                
    if not all_pairs_results:
        return None
        
    df = pd.DataFrame(all_pairs_results)
    historical_leaderboard = df.groupby('Screener').agg(
        avg_success_rate=('Success', 'mean'),
        avg_realized_return=('Return', 'mean'),
        total_picks=('Success', 'count')
    ).sort_values(['avg_success_rate', 'avg_realized_return'], ascending=False)
    
    return historical_leaderboard

# --- UTILITIES ---
def get_current_ist_time():
    return datetime.now(IST)

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_to_history(date_str, consensus_df, screener_perf):
    history = load_history()
    history[date_str] = {
        "consensus": consensus_df.to_dict(orient='records'),
        "performance": screener_perf.to_dict(orient='records'),
        "timestamp": datetime.now().isoformat()
    }
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=4)

def extract_scan_clause(url, session):
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        pattern = r':scan-json="(.*?)"'
        match = re.search(pattern, response.text)
        if match:
            json_str = html.unescape(match.group(1))
            scan_data = json.loads(json_str)
            return scan_data.get('atlas_query', '').strip()
        return None
    except Exception:
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
            "Change %": row['per_chg']
        })
    perf_df = pd.DataFrame(screener_rows)
    screener_perf = perf_df.groupby('Screener')['Change %'].agg(['mean', 'count']).reset_index()
    screener_perf = screener_perf.sort_values(by='mean', ascending=False)

    return consensus_df, screener_perf, None

# --- STREAMLIT UI ---
def main():
    st.set_page_config(page_title="Commander Desk v5", page_icon="📡", layout="wide")
    apply_custom_styles()
    
    now = get_current_ist_time()
    today_str = now.strftime("%Y-%m-%d")
    history = load_history()
    
    # --- SIDEBAR ---
    st.sidebar.title("📡 CONTROL CENTER")
    st.sidebar.info(f"IST: {now.strftime('%H:%M:%S')}")
    
    analysis_status = "READY" if today_str in history else "PENDING"
    status_color = "status-ready" if analysis_status == "READY" else "status-pending"
    st.sidebar.markdown(f"Status: <span class='{status_color}'>{analysis_status}</span>", unsafe_allow_html=True)
    
    auto_trigger = st.sidebar.checkbox("Auto-Trigger Analysis at 5 PM", value=True)
    
    # Check for Auto-Trigger
    if auto_trigger and analysis_status == "PENDING" and now.hour >= 17:
        st.sidebar.warning("🕒 It's past 5 PM IST. Auto-triggering analysis...")
        if os.path.exists(DEFAULT_EXCEL):
            df_input = pd.read_excel(DEFAULT_EXCEL)
            con_df, perf_df, err = run_full_analysis(df_input)
            if not err:
                save_to_history(today_str, con_df, perf_df)
                st.rerun()
            else:
                st.sidebar.error(err)

    st.sidebar.divider()
    page = st.sidebar.radio("Navigate", ["Command Desk", "Performance Analytics", "Historical Trends", "Strategy Synergy", "Settings"])
    
    # --- PAGE: COMMAND DESK ---
    if page == "Command Desk":
        st.title("📡 Commander Desk - Daily Pulse")
        
        if today_str not in history:
            st.info("👋 No analysis found for today. Run it manually or wait for the 5 PM auto-trigger.")
            if st.button("🚀 Run Manual Analysis"):
                if os.path.exists(DEFAULT_EXCEL):
                    df_input = pd.read_excel(DEFAULT_EXCEL)
                    con_df, perf_df, err = run_full_analysis(df_input)
                    if not err:
                        save_to_history(today_str, con_df, perf_df)
                        st.success("Analysis complete and stored!")
                        st.rerun()
                    else:
                        st.error(err)
                else:
                    st.error("Missing StocksScreener.xlsx")
        else:
            data = history[today_str]
            con_df = pd.DataFrame(data['consensus'])
            perf_df = pd.DataFrame(data['performance'])
            
            # Prediction Success Calculation
            success_report, prev_date = calculate_prediction_success(history, today_str)
            overall_success_rate = success_report['success_rate'].mean() * 100 if success_report is not None else 0
            
            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Top Conviction", con_df.iloc[0]['nsecode'], f"{con_df.iloc[0]['repetition_count']} Hits")
            m2.metric("Best Strategy", perf_df.iloc[0]['Screener'], f"{perf_df.iloc[0]['mean']:.2f}% Today")
            m3.metric("Prediction Success", f"{overall_success_rate:.1f}%", f"vs {prev_date}" if prev_date else "No History")
            m4.metric("Market Sentiment", "Bullish" if con_df['per_chg'].mean() > 0 else "Bearish", f"{con_df['per_chg'].mean():.2f}% Avg")
            
            st.subheader("🔥 High Conviction Consensus (Today)")
            # Resilient column selection
            display_cols = ['nsecode', 'name', 'repetition_count', 'close', 'per_chg']
            if 'screeners' in con_df.columns: display_cols.append('screeners')
            elif 'screener_name' in con_df.columns:
                con_df = con_df.rename(columns={'screener_name': 'screeners'})
                display_cols.append('screeners')
            
            st.dataframe(con_df.head(30)[display_cols], use_container_width=True, height=600, hide_index=True)

    # --- PAGE: PERFORMANCE ANALYTICS ---
    elif page == "Performance Analytics":
        st.title("🎯 Strategy Performance Center")
        if today_str not in history:
            st.warning("Run today's analysis to see performance data.")
        else:
            success_report, prev_date = calculate_prediction_success(history, today_str)
            historical_report = calculate_historical_success(history)

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
                    # Format
                    disp_daily = success_report.copy()
                    disp_daily['success_rate'] = (disp_daily['success_rate'] * 100).map('{:.1f}%'.format)
                    disp_daily['avg_realized_return'] = disp_daily['avg_realized_return'].map('{:.2f}%'.format)
                    st.dataframe(disp_daily[['success_rate', 'avg_realized_return', 'pick_count']], use_container_width=True, height=500)
                else:
                    st.info("Daily success analysis requires at least 2 consecutive days of data.")
            
            with col_b:
                st.subheader("🏛️ All-Time Strategic Leaderboard")
                if historical_report is not None:
                    # Format
                    disp_hist = historical_report.copy()
                    disp_hist['avg_success_rate'] = (disp_hist['avg_success_rate'] * 100).map('{:.1f}%'.format)
                    disp_hist['avg_realized_return'] = disp_hist['avg_realized_return'].map('{:.2f}%'.format)
                    st.dataframe(disp_hist[['avg_success_rate', 'avg_realized_return', 'total_picks']], use_container_width=True, height=500)
                else:
                    st.info("Historical analysis builds up as you store more daily reports.")

    # --- PAGE: HISTORICAL TRENDS ---
    elif page == "Historical Trends":
        st.title("📈 Strategic Intelligence - History")
        if not history:
            st.warning("No historical data found.")
        else:
            dates = sorted(history.keys(), reverse=True)
            selected_date = st.selectbox("Select Date", dates)
            
            day_data = history[selected_date]
            perf_df = pd.DataFrame(day_data['performance'])
            
            st.write(f"Showing performance for: {selected_date}")
            fig = px.bar(perf_df.head(10), x='mean', y='Screener', orientation='h', 
                         title="Top 10 Screeners by Average Return",
                         color='mean', color_continuous_scale='Greens')
            st.plotly_chart(fig, use_container_width=True)
            
            # Cumulative performance of a strategy over time
            st.divider()
            st.subheader("Consistency Tracker")
            all_perf_data = []
            for d in history:
                d_perf = pd.DataFrame(history[d]['performance'])
                d_perf['Date'] = d
                all_perf_data.append(d_perf)
            
            big_perf = pd.concat(all_perf_data)
            all_strategies = sorted(big_perf['Screener'].unique())
            target_strategy = st.selectbox("Pick a Strategy to Track", all_strategies)
            
            strat_trend = big_perf[big_perf['Screener'] == target_strategy].sort_values('Date')
            fig2 = px.line(strat_trend, x='Date', y='mean', markers=True, title=f"Performance Trend: {target_strategy}")
            st.plotly_chart(fig2, use_container_width=True)

    # --- PAGE: STRATEGY SYNERGY ---
    elif page == "Strategy Synergy":
        st.title("🧬 Strategy Synergy Analysis")
        if not history:
            st.warning("No data found. Run an analysis to see synergy data.")
        else:
            dates = sorted(history.keys(), reverse=True)
            selected_date = st.selectbox("Select Date for Synergy Analysis", dates, key="synergy_date")
            
            data = history[selected_date]
            con_df = pd.DataFrame(data['consensus'])
            
            # Analyze combinations
            sc_col = 'screeners' if 'screeners' in con_df.columns else 'screener_name'
            
            if sc_col in con_df.columns:
                con_df['screener_list'] = con_df[sc_col].astype(str).str.split(', ')
                con_df['combo'] = con_df['screener_list'].apply(lambda x: " + ".join(sorted(x)) if len(x) > 1 else "Single Signal")
                
                synergy = con_df.groupby('combo')['per_chg'].agg(['mean', 'count']).sort_values('mean', ascending=False)
                synergy = synergy[synergy['count'] > 1]
                
                st.subheader(f"Top Multi-Signal Combinations ({selected_date})")
                st.dataframe(synergy, use_container_width=True)
                
                fig = px.scatter(con_df, x='repetition_count', y='per_chg', hover_name='nsecode', 
                                size='repetition_count', color='per_chg',
                                title=f"Signal Count vs. Price Performance ({selected_date})")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Screener data missing in history for this date.")

    # --- PAGE: SETTINGS ---
    elif page == "Settings":
        st.title("⚙️ System Settings")
        st.write(f"App Directory: `{APP_DIR}`")
        st.write(f"History File: `{HISTORY_FILE}`")
        
        if st.button("🗑️ Clear History"):
            if os.path.exists(HISTORY_FILE):
                os.remove(HISTORY_FILE)
                st.success("History cleared.")
                st.rerun()

if __name__ == "__main__":
    main()
