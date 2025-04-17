# api/index.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import sys
import datetime
import json
import traceback # Import traceback for detailed error logging
import requests

# --- Add project root to sys.path ---
# Ensure handlers can be imported when run by Render/Gunicorn
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- Import your handlers ---
try:
    import api_handler       # For calling warframe.market
    import database_handler  # For database interactions (using pg8000)
except ImportError as e:
     # Log critical error if imports fail during startup
     print(f"CRITICAL IMPORT ERROR in API startup: {e}")
     # Depending on deployment, you might want to exit or raise further
     # For now, Flask will likely fail later if these are needed.

# --- Create Flask App and Enable CORS ---
app = Flask(__name__)
# Allow requests from any origin. Restrict this in production for better security
# by replacing '*' with your frontend's actual URL (e.g., "https://wf-analyzer-app.onrender.com")
# cors = CORS(app, resources={r"/api/*": {"origins": "https://your-frontend-app.onrender.com"}})
CORS(app)
print("Flask app created and CORS enabled.")

# --- API Routes ---

@app.route('/api/fetch_item', methods=['GET'])
def fetch_item():
    item_url_name = request.args.get('name')
    platform = request.args.get('platform', 'pc')

    # Validate input parameter
    if not item_url_name:
        print("API Endpoint: /api/fetch_item - Error: Missing 'name' parameter")
        return jsonify({"error": "Missing 'name' parameter"}), 400 # Bad Request

    print(f"API Endpoint: /api/fetch_item called for {item_url_name} on {platform}")

    conn = None # Initialize connection variable for this request
    try:
        # 1. Fetch data from external warframe.market API
        # This step might raise requests.exceptions (Timeout, HTTPError, ConnectionError)
        # or potentially JSONDecodeError if api_handler does parsing badly (it shouldn't)
        print(f"API Endpoint: Calling api_handler.get_market_data for {item_url_name}...")
        orders = api_handler.get_market_data(item_url_name, platform)

        # Handle case where external API failed or returned no relevant orders
        if orders is None:
             print(f"API Endpoint: api_handler returned None for {item_url_name}. Returning empty list.")
             # It's debatable whether this should be an error or empty success.
             # Let's treat it as success with no data for the frontend.
             return jsonify({"orders": []}) , 200

        # 2. Get DB connection FOR THIS REQUEST
        # This might raise ValueError (DATABASE_URL missing) or pg8000.Error
        print(f"API Endpoint: Attempting DB connection for {item_url_name} storage...")
        conn = database_handler.get_db_connection()
        print(f"API Endpoint: DB connection obtained for {item_url_name}.")

        # 3. Calculate min/max (potential TypeError if data format is unexpected)
        timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sell_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'sell' and 'platinum' in o])
        buy_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'buy' and 'platinum' in o], reverse=True)
        min_sell = sell_prices[0] if sell_prices else None
        max_buy = buy_prices[0] if buy_prices else None
        print(f"API Endpoint: Calculated MinSell={min_sell}, MaxBuy={max_buy} for {item_url_name}.")

        # 4. Store historical price points in DB (passing connection)
        # These use manual commit/rollback inside now, but still raise exceptions on failure
        print(f"API Endpoint: Inserting sell price ({min_sell}) for {item_url_name}...")
        database_handler.insert_market_data(conn, item_url_name, platform, timestamp_utc, 'sell', min_sell)
        print(f"API Endpoint: Inserting buy price ({max_buy}) for {item_url_name}...")
        database_handler.insert_market_data(conn, item_url_name, platform, timestamp_utc, 'buy', max_buy)
        print(f"API Endpoint: DB price points inserted for {item_url_name}.")

        # 5. Prepare and return the full order list response
        for order in orders:
             order['item_url_name'] = item_url_name # Add context for frontend if needed
        response_data = {"orders": orders}
        print(f"API Endpoint: Sending {len(orders)} orders back to frontend for {item_url_name}.")
        return jsonify(response_data), 200 # OK success

    except requests.exceptions.RequestException as req_ex:
        # Handle errors connecting to or getting data from warframe.market
        print(f"API Endpoint: External API request error in /api/fetch_item for {item_url_name}: {req_ex}")
        traceback.print_exc()
        return jsonify({"error": "Failed to fetch data from external market API"}), 502 # Bad Gateway
    except json.JSONDecodeError as json_ex:
        # Handle errors parsing JSON from warframe.market (if applicable)
        print(f"API Endpoint: JSON decode error in /api/fetch_item for {item_url_name}: {json_ex}")
        traceback.print_exc()
        return jsonify({"error": "Invalid data received from external market API"}), 502 # Bad Gateway
    except database_handler.pg8000.Error as db_ex:
        # Handle database specific errors (connection, query execution)
        print(f"API Endpoint: Database error in /api/fetch_item for {item_url_name}: {db_ex}")
        traceback.print_exc()
        return jsonify({"error": "Database operation failed"}), 500 # Internal Server Error
    except Exception as e:
        # Catch any other unexpected errors
        print(f"API Endpoint: Unexpected error in /api/fetch_item for {item_url_name}: {e}")
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred"}), 500 # Internal Server Error
    finally:
        # Ensure connection is closed if it was successfully opened in the try block
        if conn:
            try:
                conn.close()
                print(f"API Endpoint: /api/fetch_item closed DB connection for {item_url_name}")
            except database_handler.pg8000.Error as close_err:
                 # Error closing the connection (might already be closed/invalid)
                 print(f"API Endpoint: pg8000 error trying to close connection in finally for fetch_item: {close_err}")
            except Exception as close_gen_err:
                 # Catch any other weird error during close
                 print(f"API Endpoint: Generic error trying to close connection in finally for fetch_item: {close_gen_err}")


@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    print("API Endpoint: /api/watchlist GET called")
    conn = None
    try:
        # Might raise ValueError or pg8000.Error
        print("API Endpoint: GET /watchlist - Attempting DB connection...")
        conn = database_handler.get_db_connection()
        print("API Endpoint: GET /watchlist - DB connection obtained.")
        # Might raise pg8000.Error or ValueError
        print("API Endpoint: GET /watchlist - Loading watchlist from DB...")
        watchlist_data = database_handler.load_watchlist_db(conn, 'default_user')
        response_data = watchlist_data if watchlist_data else {}
        print("API Endpoint: GET /watchlist - Sending watchlist data.")
        return jsonify(response_data), 200 # OK success
    except database_handler.pg8000.Error as db_ex:
        print(f"API Endpoint: Database error in GET /api/watchlist: {db_ex}")
        traceback.print_exc()
        return jsonify({"error": "Database error loading watchlist"}), 500
    except Exception as e:
        print(f"API Endpoint: Unexpected error in GET /api/watchlist: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to load watchlist"}), 500
    finally:
        if conn:
            try:
                conn.close()
                print("API Endpoint: /api/watchlist GET closed DB connection")
            except database_handler.pg8000.Error as close_err:
                 print(f"API Endpoint: pg8000 error trying to close connection in finally for GET watchlist: {close_err}")
            except Exception as close_gen_err:
                 print(f"API Endpoint: Generic error trying to close connection in finally for GET watchlist: {close_gen_err}")


@app.route('/api/watchlist', methods=['POST'])
def save_watchlist():
    print("API Endpoint: /api/watchlist POST called")
    conn = None
    try:
        # Might raise JSONDecodeError if body is not valid JSON
        watchlist_data = request.json
        if not isinstance(watchlist_data, dict):
            print("API Endpoint: POST /watchlist - Error: Invalid data format")
            return jsonify({"error": "Invalid data format, expected JSON object"}), 400 # Bad Request

        # Might raise ValueError or pg8000.Error
        print("API Endpoint: POST /watchlist - Attempting DB connection...")
        conn = database_handler.get_db_connection()
        print("API Endpoint: POST /watchlist - DB connection obtained.")
        # Might raise pg8000.Error, ValueError or json errors if conversion fails internally
        print(f"API Endpoint: POST /watchlist - Saving {len(watchlist_data)} items to DB...")
        database_handler.save_watchlist_db(conn, watchlist_data, 'default_user')
        print("API Endpoint: POST /watchlist - Save successful.")
        return jsonify({"message": "Watchlist saved successfully"}), 200 # OK success
    except json.JSONDecodeError as json_err:
         print(f"API Endpoint: Error decoding JSON request body in POST /api/watchlist: {json_err}")
         traceback.print_exc()
         return jsonify({"error": "Invalid JSON data sent"}), 400
    except database_handler.pg8000.Error as db_ex:
        print(f"API Endpoint: Database error in POST /api/watchlist: {db_ex}")
        traceback.print_exc()
        return jsonify({"error": "Database error saving watchlist"}), 500
    except Exception as e:
        print(f"API Endpoint: Unexpected error in POST /api/watchlist: {e}")
        traceback.print_exc()
        return jsonify({"error": "Failed to save watchlist"}), 500
    finally:
        if conn:
            try:
                conn.close()
                print("API Endpoint: /api/watchlist POST closed DB connection")
            except database_handler.pg8000.Error as close_err:
                 print(f"API Endpoint: pg8000 error trying to close connection in finally for POST watchlist: {close_err}")
            except Exception as close_gen_err:
                 print(f"API Endpoint: Generic error trying to close connection in finally for POST watchlist: {close_gen_err}")


# --- Placeholder for Watchlist Check ---
# Needs full implementation: get conn, loop, call handlers, close conn in finally
@app.route('/api/check_watchlist', methods=['POST'])
def check_watchlist():
     print("API Endpoint: /api/check_watchlist POST called (Placeholder)")
     # TODO: Full implementation needed here.
     # This requires getting a DB connection, loading the watchlist,
     # looping through items, calling api_handler.get_current_min_max_prices,
     # calling database_handler.get_historical_prices_for_item (passing conn),
     # calculating status, potentially updating status in DB (requires another call),
     # and handling errors throughout, finally closing the connection.
     # This can be slow if done synchronously in one request.
     # Consider background jobs or returning immediately and letting frontend poll/reload.
     return jsonify({"message": "Watchlist check initiated (not fully implemented yet)"}), 202 # Accepted


# Note: The if __name__ == "__main__": block for local testing is removed
# as Render/Gunicorn will directly import and run the 'app' object.
# Use `flask run` or `gunicorn api.index:app` locally for testing if needed,
# ensuring the DATABASE_URL is set in your local .env file.