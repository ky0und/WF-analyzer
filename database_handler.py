# warframe_market_tracker/database_handler.py
import pg8000 # <--- Import pg8000
import datetime
import os
import json
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL") # pg8000 can often parse the standard URL

def get_db_connection():
    """Establishes a connection to the PostgreSQL database using pg8000."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set.")
    try:
        # pg8000 can parse the URL directly, or you might need to extract components
        # depending on your specific URL format and pg8000 version.
        # Basic URL parsing might be needed if direct connect fails:
        # from urllib.parse import urlparse
        # url = urlparse(DATABASE_URL)
        # conn = pg8000.connect(
        #    user=url.username,
        #    password=url.password,
        #    host=url.hostname,
        #    port=url.port,
        #    database=url.path[1:] # Remove leading '/'
        # )
        # --- Try direct connection first (often works) ---
        conn = pg8000.connect(DATABASE_URL)
        # --- End Direct ---
        return conn
    # Catch pg8000 specific errors
    except pg8000.Error as e: # <--- Change Error type
        print(f"Error connecting to PostgreSQL database using pg8000: {e}")
        raise
    except Exception as e: # Catch potential URL parsing errors etc.
        print(f"Generic error connecting with pg8000: {e}")
        raise


def setup_database():
    """Ensures necessary tables exist in the PostgreSQL database."""
    conn = None # Initialize conn
    try:
        conn = get_db_connection()
        if not conn: return

        # Use conn directly with 'with conn:' for transaction management in pg8000
        with conn:
            cur = conn.cursor() # Get cursor inside the transaction block
            # MarketData Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS MarketData (...);
            """) # Keep schema same
            # UserSettings Table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS UserSettings (...);
            """) # Keep schema same
             # Create indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_marketdata_item_time ON MarketData (item_url_name, timestamp DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_marketdata_item_type_time ON MarketData (item_url_name, order_type, timestamp DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_usersettings_userid ON UserSettings (user_id);")
            cur.close() # Explicitly close cursor (good practice)

        # conn.commit() # Commit happens automatically when 'with conn:' block exits without error
        print("DB: Tables 'MarketData' and 'UserSettings' ensured in PostgreSQL.")
    except pg8000.Error as e: # <--- Change Error type
        print(f"DB Error during setup: {e}")
        # Rollback happens automatically if 'with conn:' block exits with error
    except Exception as e:
        print(f"Unexpected error during setup: {e}")
    finally:
        if conn:
            conn.close() # Always close the connection

# --- Data Insertion ---
def insert_market_data(item_url_name, platform, timestamp_utc_iso, order_type, price):
    """Inserts a single price point into PostgreSQL MarketData using pg8000."""
    if price is None: return

    sql = """
        INSERT INTO MarketData (item_url_name, platform, timestamp, order_type, price)
        VALUES (%s, %s, %s, %s, %s)
    """ # %s placeholder works for pg8000 too
    conn = None
    try:
        conn = get_db_connection()
        with conn: # Use 'with' for transaction
            cur = conn.cursor()
            # TIMESTAMPTZ should accept ISO format string
            cur.execute(sql, (item_url_name, platform, timestamp_utc_iso, order_type, price))
            cur.close()
        # Commit automatic
    except pg8000.Error as e: # <--- Change Error type
        print(f"DB Error inserting market data for {item_url_name}: {e}")
    except Exception as e:
        print(f"Unexpected error inserting market data: {e}")
    finally:
        if conn: conn.close()

# --- Data Retrieval for Watchlist Check ---
def get_historical_prices_for_item(item_url_name, platform="pc", days=7, order_type='sell'):
    """Fetches historical prices from PostgreSQL using pg8000."""
    prices = []
    conn = None
    try:
        conn = get_db_connection()
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

        with conn: # Use 'with' for transaction (read-only is fine)
            cur = conn.cursor()
            query = """
                SELECT price FROM MarketData
                WHERE item_url_name = %s AND platform = %s AND order_type = %s AND timestamp >= %s
            """
            cur.execute(query, (item_url_name, platform, order_type, cutoff_date))
            results = cur.fetchall()
            cur.close()
            prices = [row[0] for row in results] # list comprehension remains same
            print(f"DB: Found {len(prices)} historical '{order_type}' prices for '{item_url_name}' in last {days} days.")
    except pg8000.Error as e: # <--- Change Error type
        print(f"DB Error fetching historical prices for {item_url_name}: {e}")
    except Exception as e:
        print(f"Unexpected error fetching historical prices: {e}")
    finally:
        if conn: conn.close()
    return prices

# --- Watchlist Persistence in DB ---
def load_watchlist_db(user_id='default_user'):
    """Loads the watchlist JSON for a user from PostgreSQL using pg8000."""
    watchlist_data = {}
    conn = None
    try:
        conn = get_db_connection()
        with conn: # Use 'with' for transaction
            cur = conn.cursor()
            cur.execute("SELECT watchlist FROM UserSettings WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
            cur.close()
            if result and result[0]:
                 # pg8000 usually returns JSONB as dict directly
                 watchlist_data = result[0]
                 print(f"DB: Loaded watchlist for user '{user_id}'. Items: {len(watchlist_data)}")
            else:
                 print(f"DB: No watchlist found for user '{user_id}'.")
    except pg8000.Error as e: # <--- Change Error type
        print(f"DB Error loading watchlist for {user_id}: {e}")
    except Exception as e:
        print(f"Unexpected error loading watchlist: {e}")
    finally:
        if conn: conn.close()
    return watchlist_data

def save_watchlist_db(watchlist_dict, user_id='default_user'):
    """Saves/updates the watchlist JSON for a user in PostgreSQL using pg8000."""
    conn = None
    sql = """
        INSERT INTO UserSettings (user_id, watchlist) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET watchlist = EXCLUDED.watchlist;
    """
    try:
        conn = get_db_connection()
        with conn: # Use 'with' for transaction
             cur = conn.cursor()
             # pg8000 needs json.dumps for JSONB usually
             watchlist_json = json.dumps(watchlist_dict)
             cur.execute(sql, (user_id, watchlist_json))
             cur.close()
        # Commit automatic
        print(f"DB: Saved watchlist for user '{user_id}'. Items: {len(watchlist_dict)}")
    except pg8000.Error as e: # <--- Change Error type
        print(f"DB Error saving watchlist for {user_id}: {e}")
    except Exception as e:
        print(f"Unexpected error saving watchlist: {e}")
    finally:
        if conn: conn.close()