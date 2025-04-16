# warframe_market_tracker/database_handler.py
import psycopg2 # Use PostgreSQL adapter
import datetime
import os
import json
from dotenv import load_dotenv # Load .env file

# Load environment variables from .env file (especially for local dev)
load_dotenv()

# Get connection string from environment variable
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set.")
    try:
        # print("Attempting to connect to PostgreSQL...") # Debug print
        conn = psycopg2.connect(DATABASE_URL)
        # print("Connection successful.") # Debug print
        return conn
    except psycopg2.Error as e:
        print(f"Error connecting to PostgreSQL database: {e}")
        # In a real app, you might want more robust error handling or retries
        raise # Re-raise the exception after logging

def setup_database():
    """Ensures necessary tables exist in the PostgreSQL database."""
    conn = get_db_connection()
    if not conn: return

    try:
        with conn.cursor() as cur:
            # MarketData Table (adjust types if necessary)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS MarketData (
                    id SERIAL PRIMARY KEY, -- Use SERIAL for auto-incrementing PK
                    item_url_name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL, -- Use TIMESTAMPTZ for timezone-aware timestamp
                    order_type TEXT NOT NULL, -- 'buy' or 'sell'
                    price INTEGER NOT NULL
                );
            """)
            # UserSettings Table (to store watchlist JSON)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS UserSettings (
                    user_id TEXT PRIMARY KEY, -- For simplicity, use 'default_user' for now
                    watchlist JSONB -- Store watchlist as JSONB
                );
            """)
            # Create indexes (adjust syntax slightly)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_marketdata_item_time ON MarketData (item_url_name, timestamp DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_marketdata_item_type_time ON MarketData (item_url_name, order_type, timestamp DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_usersettings_userid ON UserSettings (user_id);")

        conn.commit() # Commit the changes
        print("DB: Tables 'MarketData' and 'UserSettings' ensured in PostgreSQL.")
    except psycopg2.Error as e:
        print(f"DB Error during setup: {e}")
        conn.rollback() # Rollback changes on error
    finally:
        if conn:
            conn.close() # Always close the connection

# --- Data Insertion ---
def insert_market_data(item_url_name, platform, timestamp_utc_iso, order_type, price):
    """Inserts a single price point into PostgreSQL MarketData."""
    if price is None: return

    sql = """
        INSERT INTO MarketData (item_url_name, platform, timestamp, order_type, price)
        VALUES (%s, %s, %s, %s, %s)
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Convert ISO string back to datetime obj for psycopg2 (or ensure it's compatible)
            # psycopg2 can often handle ISO strings directly for TIMESTAMPTZ
            cur.execute(sql, (item_url_name, platform, timestamp_utc_iso, order_type, price))
        conn.commit()
        # print(f"DB: Stored {item_url_name} ({platform}) - {order_type} @ {price}") # Debug
    except psycopg2.Error as e:
        print(f"DB Error inserting market data for {item_url_name}: {e}")
        if conn: conn.rollback()
    except Exception as e:
        print(f"Unexpected error inserting market data: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()

# --- Data Retrieval for Watchlist Check ---
def get_historical_prices_for_item(item_url_name, platform="pc", days=7, order_type='sell'):
    """Fetches historical prices from PostgreSQL."""
    prices = []
    conn = None
    try:
        conn = get_db_connection()
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        # cutoff_iso = cutoff_date.isoformat() # Use datetime object directly

        with conn.cursor() as cur:
            query = """
                SELECT price
                FROM MarketData
                WHERE item_url_name = %s
                  AND platform = %s
                  AND order_type = %s
                  AND timestamp >= %s
            """
            cur.execute(query, (item_url_name, platform, order_type, cutoff_date))
            results = cur.fetchall()
            prices = [row[0] for row in results]
            print(f"DB: Found {len(prices)} historical '{order_type}' prices for '{item_url_name}' in last {days} days.")
    except psycopg2.Error as e:
        print(f"DB Error fetching historical prices for {item_url_name}: {e}")
    except Exception as e:
        print(f"Unexpected error fetching historical prices: {e}")
    finally:
        if conn: conn.close()
    return prices

# --- Watchlist Persistence in DB ---
def load_watchlist_db(user_id='default_user'):
    """Loads the watchlist JSON for a user from PostgreSQL."""
    watchlist_data = {}
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT watchlist FROM UserSettings WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            if result and result[0]:
                 # The data should already be a dict if stored as JSONB correctly
                 watchlist_data = result[0]
                 print(f"DB: Loaded watchlist for user '{user_id}'. Items: {len(watchlist_data)}")
            else:
                 print(f"DB: No watchlist found for user '{user_id}'.")
    except psycopg2.Error as e:
        print(f"DB Error loading watchlist for {user_id}: {e}")
    except Exception as e:
        print(f"Unexpected error loading watchlist: {e}")
    finally:
        if conn: conn.close()
    return watchlist_data

def save_watchlist_db(watchlist_dict, user_id='default_user'):
    """Saves/updates the watchlist JSON for a user in PostgreSQL."""
    conn = None
    sql = """
        INSERT INTO UserSettings (user_id, watchlist)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            watchlist = EXCLUDED.watchlist;
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
             # Convert dict to JSON string for storage if not using JSONB directly with psycopg2 v3+ features
             # For standard JSONB, psycopg2 needs json.dumps
             watchlist_json = json.dumps(watchlist_dict)
             cur.execute(sql, (user_id, watchlist_json))
        conn.commit()
        print(f"DB: Saved watchlist for user '{user_id}'. Items: {len(watchlist_dict)}")
    except psycopg2.Error as e:
        print(f"DB Error saving watchlist for {user_id}: {e}")
        if conn: conn.rollback()
    except Exception as e:
        print(f"Unexpected error saving watchlist: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()