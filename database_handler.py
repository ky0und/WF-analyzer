# warframe_market_tracker/database_handler.py
import sqlite3
import datetime
import os
import statistics # For median calculation

# --- Database Setup ---
def setup_database(db_file="market_data.db"):
    """Connects/creates the DB and ensures the MarketData table exists."""
    print(f"DB: Ensuring database exists at {os.path.abspath(db_file)}")
    # Allow access from different threads (needed for Flet background tasks)
    conn = sqlite3.connect(db_file, check_same_thread=False)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS MarketData (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_url_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                timestamp TEXT NOT NULL, -- Store as ISO 8601 Text (UTC)
                order_type TEXT NOT NULL, -- 'buy' or 'sell'
                price INTEGER NOT NULL
            );
        """)
        # Indexes for faster querying
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_item_time ON MarketData (item_url_name, timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_item_type_time ON MarketData (item_url_name, order_type, timestamp);")
        conn.commit()
        print("DB: Table 'MarketData' ensured.")
    except sqlite3.Error as e:
        print(f"DB Error during setup: {e}")
        conn.close() # Close connection if setup fails critically
        return None
    return conn

# --- Data Insertion ---
def insert_market_data(db_conn, item_url_name, platform, timestamp_utc, order_type, price):
    """Inserts a single min sell or max buy price point."""
    if price is None or db_conn is None:
        return # Don't insert if price wasn't found or DB connection is invalid

    sql = """
        INSERT INTO MarketData (item_url_name, platform, timestamp, order_type, price)
        VALUES (?, ?, ?, ?, ?)
    """
    cursor = db_conn.cursor()
    try:
        cursor.execute(sql, (item_url_name, platform, timestamp_utc, order_type, price))
        db_conn.commit()
        # Avoid excessive printing here unless debugging
        # print(f"DB: Stored {item_url_name} ({platform}) - {order_type} @ {price}")
    except sqlite3.Error as e:
        print(f"DB Error inserting data for {item_url_name}: {e}")

# --- Data Retrieval for Watchlist ---
def get_historical_prices_for_item(db_conn, item_url_name, platform="pc", days=7, order_type='sell'):
    """
    Fetches historical prices for a specific item and order type within a time window.

    Args:
        db_conn: Active database connection.
        item_url_name: The API-formatted item name.
        platform: The platform ('pc', etc.).
        days: How many days back to look for historical data.
        order_type: 'buy' or 'sell'.

    Returns:
        list: A list of integer prices, or an empty list if error/no data.
    """
    if not db_conn:
        return []
    try:
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        cutoff_iso = cutoff_date.isoformat()

        cursor = db_conn.cursor()
        query = """
            SELECT price
            FROM MarketData
            WHERE item_url_name = ?
              AND platform = ?
              AND order_type = ?
              AND timestamp >= ?
            ORDER BY timestamp DESC -- Order doesn't strictly matter for median but good practice
        """
        cursor.execute(query, (item_url_name, platform, order_type, cutoff_iso))
        results = cursor.fetchall()
        # fetchall returns tuples, extract the first element (the price)
        prices = [row[0] for row in results]
        print(f"DB: Found {len(prices)} historical '{order_type}' prices for '{item_url_name}' in last {days} days.")
        return prices
    except sqlite3.Error as e:
        print(f"DB Error fetching historical prices for {item_url_name}: {e}")
        return [] # Return empty list on error

# --- Optional: Get historical data for display (if needed later) ---
def get_historical_data_display(db_conn, item_url_name=None, platform="pc", limit=100):
    # ... (Keep the implementation from previous versions if you want a separate historical view) ...
    pass