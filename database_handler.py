      
# database_handler.py
import os
from dotenv import load_dotenv
import pg8000
from urllib.parse import urlparse
import datetime
import json

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
print(f"--- DATABASE_URL FROM ENV: {DATABASE_URL} ---")

def get_db_connection():
    if not DATABASE_URL:
        print("--- ERROR: DATABASE_URL environment variable is NOT SET. ---")
        raise ValueError("DATABASE_URL environment variable not set.")

    try:
        print(f"--- Parsing URL: {DATABASE_URL} ---")
        url = urlparse(DATABASE_URL)

        db_user = url.username
        db_password = url.password
        db_host = url.hostname
        # --- Assign default port if None ---
        db_port = url.port if url.port else 5432 # <-- Use default 5432 if url.port is None/falsy
        # --- End default port assignment ---
        db_name = url.path[1:] if url.path else None # Handle potential empty path, remove leading '/'

        print(f"--- Parsed Components ---")
        print(f"User: {db_user}")
        print(f"Host: {db_host}")
        print(f"Port: {db_port}") # Should now show 5432
        print(f"Database: {db_name}")
        print(f"Password: {'*' * len(db_password) if db_password else 'None'}")

        # Check potentially missing components (e.g., database name if path was empty)
        if not all([db_user, db_password, db_host, db_port, db_name]):
             print("--- ERROR: Failed to parse one or more required components from DATABASE_URL ---")
             # Log which component might be missing if needed
             raise ValueError("Failed to parse required components from DATABASE_URL")

        print(f"--- Attempting pg8000.connect with explicit args to Host: {db_host} Port: {db_port} ---")
        conn = pg8000.connect(
            user=db_user,
            password=db_password,
            host=db_host,
            port=int(db_port), # <-- Ensure port is integer
            database=db_name,
            ssl_context=True # Consider adding if connection still fails (Render often uses SSL)
        )
        print("--- Explicit parameter connection successful ---")
        return conn
    except pg8000.Error as e:
        print(f"Error connecting to PostgreSQL database using pg8000 (explicit params): {e}")
        raise
    except Exception as e:
        print(f"Error parsing DATABASE_URL or connecting with explicit params: {e}")
        import traceback
        traceback.print_exc()
        raise

# --- Data Insertion (Manual Transaction) ---
def insert_market_data(conn, item_url_name, platform, timestamp_utc_iso, order_type, price):
    if price is None: return
    if not conn: raise ValueError("Database connection object is required.")

    sql = """
        INSERT INTO MarketData (item_url_name, platform, timestamp, order_type, price)
        VALUES (%s, %s, %s, %s, %s)
    """
    cur = None # Initialize cursor variable
    try:
        cur = conn.cursor()
        cur.execute(sql, (item_url_name, platform, timestamp_utc_iso, order_type, price))
        conn.commit() # <--- Commit manually on success
        # print(f"DB: Stored {item_url_name} ...")
    except pg8000.Error as e:
        print(f"DB Error inserting market data for {item_url_name}: {e}")
        if conn:
            try: conn.rollback() # <--- Rollback on error
            except pg8000.Error as rb_err: print(f"DB Error during rollback: {rb_err}")
        raise # Re-raise the original error
    except Exception as e:
        print(f"Unexpected error inserting market data: {e}")
        if conn:
            try: conn.rollback()
            except pg8000.Error as rb_err: print(f"DB Error during rollback: {rb_err}")
        raise
    finally:
        if cur: # Close cursor if it was created
            try: cur.close()
            except pg8000.Error as cur_err: print(f"DB: Error closing cursor: {cur_err}")


# --- Data Retrieval (Manual Transaction - less critical for reads but consistent) ---
def get_historical_prices_for_item(conn, item_url_name, platform="pc", days=7, order_type='sell'):
    prices = []
    if not conn: raise ValueError("Database connection object is required.")
    cur = None
    try:
        cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        cur = conn.cursor()
        query = """
            SELECT price FROM MarketData
            WHERE item_url_name = %s AND platform = %s AND order_type = %s AND timestamp >= %s
        """
        cur.execute(query, (item_url_name, platform, order_type, cutoff_date))
        results = cur.fetchall()
        prices = [row[0] for row in results]
        print(f"DB: Found {len(prices)} historical '{order_type}' prices...")
    except pg8000.Error as e:
        print(f"DB Error fetching historical prices for {item_url_name}: {e}")
        # No rollback needed for SELECT, but re-raise
        raise
    except Exception as e:
        print(f"Unexpected error fetching historical prices: {e}")
        raise
    finally:
         if cur:
            try: cur.close()
            except pg8000.Error as cur_err: print(f"DB: Error closing cursor: {cur_err}")
    return prices


# --- Watchlist Persistence (Manual Transaction) ---
def load_watchlist_db(conn, user_id='default_user'):
    watchlist_data = {}
    if not conn: raise ValueError("Database connection object is required.")
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("SELECT watchlist FROM UserSettings WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        if result and result[0]:
             watchlist_data = result[0]
             print(f"DB: Loaded watchlist for user '{user_id}'. Items: {len(watchlist_data)}")
        else:
             print(f"DB: No watchlist found for user '{user_id}'.")
    except pg8000.Error as e:
        print(f"DB Error loading watchlist for {user_id}: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error loading watchlist: {e}")
        raise
    finally:
         if cur:
            try: cur.close()
            except pg8000.Error as cur_err: print(f"DB: Error closing cursor: {cur_err}")
    return watchlist_data


def save_watchlist_db(conn, watchlist_dict, user_id='default_user'):
    if not conn: raise ValueError("Database connection object is required.")
    sql = """
        INSERT INTO UserSettings (user_id, watchlist) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET watchlist = EXCLUDED.watchlist;
    """
    cur = None
    try:
         cur = conn.cursor()
         watchlist_json = json.dumps(watchlist_dict)
         cur.execute(sql, (user_id, watchlist_json))
         conn.commit() # <--- Commit manually
         print(f"DB: Saved watchlist for user '{user_id}'. Items: {len(watchlist_dict)}")
    except pg8000.Error as e:
        print(f"DB Error saving watchlist for {user_id}: {e}")
        if conn:
            try: conn.rollback() # <--- Rollback
            except pg8000.Error as rb_err: print(f"DB Error during rollback: {rb_err}")
        raise
    except Exception as e:
        print(f"Unexpected error saving watchlist: {e}")
        if conn:
            try: conn.rollback()
            except pg8000.Error as rb_err: print(f"DB Error during rollback: {rb_err}")
        raise
    finally:
         if cur:
            try: cur.close()
            except pg8000.Error as cur_err: print(f"DB: Error closing cursor: {cur_err}")