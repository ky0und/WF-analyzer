      
# api/index.py
from flask import Flask, request, jsonify
import os
import sys
import datetime

# Add project root to sys.path to import handlers
# Adjust based on your project structure if api/ is not directly in root
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now import your handlers
try:
    import api_handler # Your original handler for warframe.market calls
    import database_handler # Your NEW PostgreSQL handler
except ImportError as e:
     # Basic error response if imports fail
     print(f"CRITICAL IMPORT ERROR in API: {e}")
     # In production, you might want to handle this more gracefully
     # or ensure the deployment environment has the correct path setup.

app = Flask(__name__)

# Initialize database on first request (or ideally before) if needed
# This is simplified; proper setup might involve app context
try:
     print("API: Running database setup check...")
     # database_handler.setup_database() # Run setup check
     # Note: Running setup on every API cold start might be slow/inefficient.
     # It's often better to ensure the DB is set up separately.
     # We'll rely on tables existing for now.
     print("API: Database setup check skipped/assumed complete.")
except Exception as e:
     print(f"API: Error during initial DB setup check: {e}")


# --- API Routes ---

@app.route('/api/fetch_item', methods=['GET'])
def fetch_item():
    item_url_name = request.args.get('name')
    platform = request.args.get('platform', 'pc') # Default to PC

    if not item_url_name:
        return jsonify({"error": "Missing 'name' parameter"}), 400

    print(f"API Endpoint: /api/fetch_item called for {item_url_name}")

    try:
        # 1. Fetch data from warframe.market
        orders = api_handler.get_market_data(item_url_name, platform)

        if orders is None:
            # Distinguish between API error and no orders found
            # For simplicity, return empty list if API fails here
             print(f"API Endpoint: api_handler returned None for {item_url_name}")
             return jsonify({"orders": []}) # Return empty list, frontend can handle

        # 2. Calculate min/max and store in DB (asynchronously?)
        # For simplicity, do it synchronously here. Could be slow.
        timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sell_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'sell' and 'platinum' in o])
        buy_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'buy' and 'platinum' in o], reverse=True)
        min_sell = sell_prices[0] if sell_prices else None
        max_buy = buy_prices[0] if buy_prices else None

        database_handler.insert_market_data(item_url_name, platform, timestamp_utc, 'sell', min_sell)
        database_handler.insert_market_data(item_url_name, platform, timestamp_utc, 'buy', max_buy)

        # 3. Return the fetched orders to the frontend
        # Add item_url_name back to each order for frontend context
        for order in orders:
            order['item_url_name'] = item_url_name

        return jsonify({"orders": orders})

    except Exception as e:
        print(f"API Endpoint: Error in /api/fetch_item for {item_url_name}: {e}")
        # Log the full traceback in production for debugging
        import traceback
        traceback.print_exc()
        return jsonify({"error": "An internal server error occurred"}), 500


@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    print("API Endpoint: /api/watchlist GET called")
    try:
        # Assuming a single user for now
        watchlist_data = database_handler.load_watchlist_db('default_user')
        return jsonify(watchlist_data if watchlist_data else {}) # Return empty dict if None
    except Exception as e:
        print(f"API Endpoint: Error in GET /api/watchlist: {e}")
        return jsonify({"error": "Failed to load watchlist"}), 500

@app.route('/api/watchlist', methods=['POST'])
def save_watchlist():
    print("API Endpoint: /api/watchlist POST called")
    try:
        watchlist_data = request.json # Get watchlist dict from request body
        if not isinstance(watchlist_data, dict):
            return jsonify({"error": "Invalid data format, expected JSON object"}), 400

        # Assuming a single user for now
        database_handler.save_watchlist_db(watchlist_data, 'default_user')
        return jsonify({"message": "Watchlist saved successfully"}), 200
    except Exception as e:
        print(f"API Endpoint: Error in POST /api/watchlist: {e}")
        return jsonify({"error": "Failed to save watchlist"}), 500

# --- Placeholder for Watchlist Check ---
# This would need a trigger (e.g., Vercel Cron Job) or manual call from frontend
@app.route('/api/check_watchlist', methods=['POST']) # POST to indicate action
def check_watchlist():
     print("API Endpoint: /api/check_watchlist POST called")
     # TODO: Implement logic similar to check_watchlist_prices_thread
     # 1. Load watchlist from DB
     # 2. Loop through items
     # 3. For each item:
     #    - Call api_handler.get_current_min_max_prices
     #    - Call database_handler.get_historical_prices_for_item
     #    - Calculate deal status
     # 4. Update watchlist statuses (maybe store results temporarily or update DB?)
     # 5. Return the updated statuses
     # This needs careful thought about how statuses are stored/updated.
     # For now, return a simple message.
     return jsonify({"message": "Watchlist check initiated (not fully implemented yet)"}), 202 # Accepted

# Note: This structure might not be fully optimized for Vercel serverless cold starts.
# Consider database connection pooling if performance becomes an issue.

# Vercel automatically looks for the 'app' variable
if __name__ == "__main__":
    # This part is for local testing, Vercel runs the app directly
    app.run(debug=True, port=5001) # Run on a different port locally

    