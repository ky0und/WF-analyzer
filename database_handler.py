      
# database_handler.py
import os
from dotenv import load_dotenv
import pg8000
from urllib.parse import urlparse # <-- Make sure this is imported

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
print(f"--- DATABASE_URL FROM ENV: {DATABASE_URL} ---") # Keep this print

def get_db_connection():
    if not DATABASE_URL:
        print("--- ERROR: DATABASE_URL environment variable is NOT SET. ---")
        raise ValueError("DATABASE_URL environment variable not set.")

    # --- Force parsing and explicit parameters ---
    try:
        print(f"--- Parsing URL: {DATABASE_URL} ---")
        url = urlparse(DATABASE_URL)

        # Extract components - Add print statements for EACH component
        db_user = url.username
        db_password = url.password
        db_host = url.hostname
        db_port = url.port
        db_name = url.path[1:] # Remove leading '/'

        print(f"--- Parsed Components ---")
        print(f"User: {db_user}")
        print(f"Host: {db_host}")
        print(f"Port: {db_port}")
        print(f"Database: {db_name}")
        # Avoid printing password in production logs if possible, but okay for debugging now
        print(f"Password: {'*' * len(db_password) if db_password else 'None'}")


        if not all([db_user, db_password, db_host, db_port, db_name]):
             print("--- ERROR: Failed to parse one or more components from DATABASE_URL ---")
             raise ValueError("Failed to parse required components from DATABASE_URL")

        print(f"--- Attempting pg8000.connect with explicit args to Host: {db_host} ---")
        conn = pg8000.connect(
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            database=db_name
            # You might need ssl_context=True if Render forces SSL and pg8000 doesn't auto-detect
            # ssl_context=True
        )
        print("--- Explicit parameter connection successful ---")
        return conn
    except pg8000.Error as e:
        print(f"Error connecting to PostgreSQL database using pg8000 (explicit params): {e}")
        raise
    except Exception as e:
        # This will catch errors during parsing too
        print(f"Error parsing DATABASE_URL or connecting with explicit params: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for parsing errors
        raise
    # --- End force parsing ---

    


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