# 📡 Consensus Intelligence: Automated Stock Screening Platform

Consensus Intelligence is an advanced stock market analytics dashboard built with Streamlit. it automates the process of scanning multiple Chartink screeners, identifying "Consensus" stocks (high-conviction picks appearing in multiple scans), and tracking strategy performance over time.

## 🚀 Key Features

- **Automated Daily Analysis**: Triggered automatically at 5:00 PM IST to capture final post-market settled prices.
- **Next-Day Prediction Audit**: Measures exactly how yesterday's picks performed in today's market (The "Daily Debrief").
- **Consensus Engine**: Identifies stocks with the highest conviction based on cross-strategy repetition.
- **Strategic Leaderboard**: Ranks strategies based on weighted historical success and realized alpha.
- **Vault Protection**: Safety mechanisms to prevent intraday data from corrupting historical closing records.
- **Admin Control Center**: Password-protected settings for manual analysis and data management.
- **Scalable Architecture**: Powered by SQLite for fast, reliable data persistence.

## 🛠️ Tech Stack

- **UI**: Streamlit
- **Data Engine**: Pandas, SQLite
- **Visualization**: Plotly
- **Scraping**: BeautifulSoup4, Requests
- **Timezone Management**: Pytz

## 📦 Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/screeneriq.git
   cd screeneriq
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Add your screener list to `StocksScreener.xlsx` (columns: `SCAN STOCKS`, `LINK`).

4. Run the application:
   ```bash
   streamlit run app.py
   ```

## 📂 Project Structure

- `app.py`: Main Streamlit application and dashboard UI.
- `database.py`: SQLite data layer.
- `migrate_data.py`: Utility to import historical JSON data.
- `history.db`: Local SQLite database (ignored by git).
- `StocksScreener.xlsx`: Your input Excel file with Chartink links.

---
*Disclaimer: This tool is for educational and research purposes only. Always perform your own due diligence before trading.*
