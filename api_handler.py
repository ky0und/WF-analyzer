# warframe_market_tracker/api_handler.py
import requests

# --- Configuration ---
API_BASE_URL = "https://api.warframe.market/v1"
REQUEST_DELAY_SECONDS = 0.5 # Be respectful of the API

# --- Main Data Fetching Function (Keep as is) ---
def get_market_data(item_url_name, platform="pc"):
    # ... (Keep the implementation that works for you, the one finding relevant orders) ...
    # Example structure:
    try:
        url = f"{API_BASE_URL}/items/{item_url_name}/orders"
        params = {'platform': platform, 'include': 'item'}
        headers = {'accept': 'application/json', 'Platform': platform, 'Language': 'en'}
        print(f"API: Fetching full orders for: {item_url_name} ({platform})")
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if 'payload' in data and 'orders' in data['payload']:
            all_orders = data['payload']['orders']
            online_ingame_orders = [
                order for order in all_orders
                if order.get('user', {}).get('platform') == platform and \
                   str(order.get('user', {}).get('status')).lower() in ['ingame', 'online'] and \
                   order.get('visible', False) is True
            ]
            print(f"API: Found {len(online_ingame_orders)} relevant orders for {item_url_name}")
            return online_ingame_orders
        else:
            # Handle unexpected structure
            return None
    except Exception as e:
        print(f"API Error in get_market_data for {item_url_name}: {e}")
        return None # Return None on any error

# --- Helper for Watchlist Check ---
def get_current_min_max_prices(item_url_name, platform="pc"):
    """
    Fetches current orders and returns only the min sell and max buy prices.

    Returns:
        tuple: (min_sell_price, max_buy_price). Values can be None.
               Returns (None, None) if fetching fails.
    """
    print(f"API: Getting min/max for watchlist check: {item_url_name}")
    orders = get_market_data(item_url_name, platform) # Reuse the main fetch function

    if orders is None: # Check if fetching failed in get_market_data
         print(f"API: Failed to get orders for min/max check of {item_url_name}")
         return None, None

    if not orders: # Check if the list is empty (no relevant orders found)
        return None, None

    # Calculate min sell / max buy from the fetched orders
    sell_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'sell' and 'platinum' in o])
    buy_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'buy' and 'platinum' in o], reverse=True)

    min_sell = sell_prices[0] if sell_prices else None
    max_buy = buy_prices[0] if buy_prices else None

    print(f"API: Current prices for {item_url_name} - Min Sell: {min_sell}, Max Buy: {max_buy}")
    return min_sell, max_buy