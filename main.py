# warframe_market_tracker/main.py
import flet as ft
import datetime
import time
import threading
import re
import statistics
import json # <-- Import JSON
import os   # <-- Import OS

# Import handlers
import api_handler
import database_handler

# --- Configuration ---
PLATFORM = "pc"
DB_FILE = "market_data.db"
WATCHLIST_FILE = "watchlist.json" # <-- Define watchlist filename
WATCHLIST_CHECK_DELAY_SECONDS = 1.5
AUTO_CHECK_INTERVAL_MINUTES = 30

# --- Global Variables ---
db_connection = None
current_orders_data = []
watched_items = {} # Will be loaded from file
data_lock = threading.Lock()
watchlist_lock = threading.Lock()
live_order_filter = 'all'
auto_check_thread = None
stop_auto_check_flag = threading.Event()
auto_check_active_state = False

# --- Helper Function (Item Name Formatting - Keep as is) ---
def format_item_name_for_api(user_input):
    # ... (implementation) ...
    if not user_input: return None
    formatted = user_input.lower().strip().replace(' ', '_')
    return formatted


# --- Watchlist Persistence Functions ---
def load_watchlist():
    """Loads the watchlist from WATCHLIST_FILE into the global watched_items dict."""
    global watched_items
    if os.path.exists(WATCHLIST_FILE):
        try:
            # Use lock to ensure thread safety even during load (good practice)
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f, watchlist_lock:
                loaded_data = json.load(f)
                # Basic validation: ensure it's a dictionary
                if isinstance(loaded_data, dict):
                    watched_items = loaded_data
                    print(f"Loaded {len(watched_items)} items from {WATCHLIST_FILE}")
                else:
                    print(f"Warning: Invalid format in {WATCHLIST_FILE}. Starting with empty watchlist.")
                    watched_items = {} # Reset if format is wrong
        except json.JSONDecodeError:
            print(f"Error decoding JSON from {WATCHLIST_FILE}. File might be corrupt. Starting with empty watchlist.")
            # Optionally backup the corrupted file here before resetting
            # os.rename(WATCHLIST_FILE, f"{WATCHLIST_FILE}.bak")
            with watchlist_lock: watched_items = {} # Ensure reset within lock
        except IOError as e:
            print(f"Error reading watchlist file {WATCHLIST_FILE}: {e}. Starting empty.")
            with watchlist_lock: watched_items = {}
        except Exception as e:
             print(f"Unexpected error loading watchlist: {e}. Starting empty.")
             with watchlist_lock: watched_items = {}
    else:
        print(f"{WATCHLIST_FILE} not found. Starting with empty watchlist.")
        # No need to lock here as it's the initial state
        watched_items = {}

def save_watchlist():
    """Saves the current watched_items dictionary to WATCHLIST_FILE."""
    global watched_items
    try:
        # Use lock to ensure thread safety during save
        with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f, watchlist_lock:
            json.dump(watched_items, f, indent=4, ensure_ascii=False) # Use indent for readability
            print(f"Saved {len(watched_items)} items to {WATCHLIST_FILE}")
    except IOError as e:
        print(f"Error writing watchlist file {WATCHLIST_FILE}: {e}")
    except Exception as e:
        print(f"Unexpected error saving watchlist: {e}")


# --- Flet Application ---
def main(page: ft.Page):
    global db_connection, current_orders_data, watched_items, live_order_filter, auto_check_active_state

    # --- Define page reference globally (needed for copy_whisper_message) ---
    # This is slightly hacky, better solutions exist with classes, but works for now
    global app_page
    app_page = page
    # --- End page reference ---


    page.title = "Warframe Market Tracker - Live & Watchlist"
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.window.width = 800
    page.window.height = 1000
    page.window.resizable = True # Explicitly enable resizing (usually default)
    page.window.min_width = 800  # Set MINIMUM reasonable width
    page.window.min_height = 1000 # Set MINIMUM reasonable height

    page.update()
    
    # --- Load Watchlist EARLY ---
    load_watchlist() # Load data before building UI that might depend on it

    # --- Database Setup ---
    try:
        db_connection = database_handler.setup_database(DB_FILE)
        if not db_connection:
             page.add(ft.Text("FATAL: Could not connect to the database.", color=ft.colors.RED))
             page.update()
             return
    except Exception as e:
        page.add(ft.Text(f"FATAL: Error setting up database: {e}", color=ft.colors.RED))
        page.update()
        return

    # --- GUI Elements (Define them BEFORE page.add) ---
    # Search Area
    item_input = ft.TextField(label="Item Name", hint_text="Enter item name", autofocus=True, width=350, on_submit=lambda e: fetch_button_clicked(e))
    fetch_button = ft.ElevatedButton("Fetch Item Orders", icon=ft.icons.SEARCH, tooltip="Fetch live orders")
    add_watchlist_button = ft.ElevatedButton("Add to Watchlist", icon=ft.icons.ADD_CIRCLE_OUTLINE, tooltip="Add the searched item", disabled=True)
    search_status_text = ft.Text("Enter an item name and press 'Fetch' or Enter.", italic=True)

    # Live Orders Area
    live_orders_header_row = ft.Row(
        [
            ft.Text("Live Market Orders", style=ft.TextThemeStyle.HEADLINE_SMALL),
            ft.RadioGroup( content=ft.Row([ ft.Radio(value="all", label="All"), ft.Radio(value="sell", label="Sell Only"), ft.Radio(value="buy", label="Buy Only"), ]), value=live_order_filter, on_change=lambda e: live_filter_changed(e.control.value) )
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN
    )
    live_data_table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Whisper")), # Action
            ft.DataColumn(ft.Text("Item"), on_sort=lambda e: handle_sort(e, 'live', 1)),
            ft.DataColumn(ft.Text("User"), on_sort=lambda e: handle_sort(e, 'live', 2)),
            ft.DataColumn(ft.Text("Type"), on_sort=lambda e: handle_sort(e, 'live', 3)),
            ft.DataColumn(ft.Text("Quantity"), numeric=True, on_sort=lambda e: handle_sort(e, 'live', 4)),
            ft.DataColumn(ft.Text("Price (Plat)"), numeric=True, on_sort=lambda e: handle_sort(e, 'live', 5)),
            ft.DataColumn(ft.Text("Status"), on_sort=lambda e: handle_sort(e, 'live', 6)),
        ], rows=[], width=950, column_spacing=10, sort_column_index=None, sort_ascending=True, heading_row_color=ft.colors.with_opacity(0.1, ft.colors.ON_SURFACE),
    )

    # Watchlist Area
    watchlist_status_text = ft.Text("Watchlist Status: Idle", italic=True)
    check_watchlist_button = ft.ElevatedButton("Check Watchlist Prices", icon=ft.icons.VISIBILITY, tooltip="Check all watched items")
    enable_auto_check_cb = ft.Checkbox( label="Auto-Check Watchlist", tooltip=f"Auto-check every {AUTO_CHECK_INTERVAL_MINUTES} mins", value=auto_check_active_state, on_change=lambda e: toggle_automatic_checks(e.control.value) )
    watchlist_view = ft.ListView(expand=True, spacing=5)

    # --- Core Logic ---
    # Status Update Helper
    def update_status(target_text_widget, message, is_loading=False, is_error=False, controls_to_disable=None):
        # ... (implementation - uses page.update()) ...
        target_text_widget.value = message
        target_text_widget.italic = not is_loading and not is_error
        target_text_widget.color = ft.colors.RED if is_error else ft.colors.with_opacity(0.7, ft.colors.ON_SURFACE) if is_loading else None
        if controls_to_disable:
            for control in controls_to_disable: control.disabled = is_loading
        page.update()


    # Fetching Single Item Thread
    def fetch_single_item_thread(item_url_name, user_friendly_name):
        # ... (implementation - calls update_status, update_live_table_display) ...
        # ... (includes call to database_handler.insert_market_data) ...
        global current_orders_data, db_connection
        controls_to_disable = [fetch_button, item_input, add_watchlist_button, check_watchlist_button, enable_auto_check_cb] # Include checkbox
        update_status(search_status_text, f"Fetching: {user_friendly_name}...", is_loading=True, controls_to_disable=controls_to_disable)
        orders = api_handler.get_market_data(item_url_name, PLATFORM)
        fetched_orders_batch = []
        min_sell_for_db, max_buy_for_db = None, None
        status_message = f"Error fetching data for {user_friendly_name}."
        is_error = True
        if orders is not None:
            timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
            sell_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'sell' and 'platinum' in o])
            buy_prices = sorted([o['platinum'] for o in orders if o.get('order_type') == 'buy' and 'platinum' in o], reverse=True)
            min_sell_for_db = sell_prices[0] if sell_prices else None
            max_buy_for_db = buy_prices[0] if buy_prices else None
            database_handler.insert_market_data(db_connection, item_url_name, PLATFORM, timestamp_utc, 'sell', min_sell_for_db)
            database_handler.insert_market_data(db_connection, item_url_name, PLATFORM, timestamp_utc, 'buy', max_buy_for_db)
            for order in orders: order['item_url_name'] = item_url_name
            fetched_orders_batch.extend(orders)
            status_message = f"Displaying {len(fetched_orders_batch)} orders for {user_friendly_name}. Stored price point."
            is_error = False
            add_watchlist_button.disabled = False
            add_watchlist_button.data = {'url_name': item_url_name, 'friendly_name': user_friendly_name}
            page.update() # Update button state
        with data_lock: current_orders_data = fetched_orders_batch
        print(f"Live fetch complete. Stored {len(current_orders_data)} orders in memory for {item_url_name}.")
        update_live_table_display()
        update_status(search_status_text, status_message, is_loading=False, is_error=is_error, controls_to_disable=controls_to_disable)


    # Fetch Button Click Handler
    def fetch_button_clicked(e):
        # ... (implementation - calls update_status, starts thread) ...
        user_input = item_input.value
        if not user_input or not user_input.strip():
            update_status(search_status_text, "Please enter an item name.", is_error=True)
            item_input.error_text = "Cannot be empty"; page.update(); return
        item_input.error_text = None; add_watchlist_button.disabled = True; page.update()
        item_url_name = format_item_name_for_api(user_input)
        live_data_table.rows = []; page.update()
        thread = threading.Thread(target=fetch_single_item_thread, args=(item_url_name, user_input.strip()), daemon=True)
        thread.start()

    # --- Watchlist Logic ---
    def add_watchlist_clicked(e):
        # ... (implementation - uses update_status, calls update_watchlist_display) ...
        item_data = add_watchlist_button.data
        if not item_data: return
        url_name = item_data['url_name']
        friendly_name = item_data['friendly_name']
        with watchlist_lock:
            if url_name not in watched_items:
                watched_items[url_name] = {'status': 'Not Checked', 'last_checked': None, 'friendly_name': friendly_name}
                print(f"Watchlist: Added {url_name}")
                update_status(search_status_text, f"Added '{friendly_name}' to watchlist.", is_loading=False)
            else:
                update_status(search_status_text, f"'{friendly_name}' is already on watchlist.", is_loading=False, is_error=True)
        update_watchlist_display()
        save_watchlist() # <-- SAVE HERE

    def check_watchlist_prices_thread(is_auto_run=False):
        # ... (implementation - calls update_status, check_watched_item_deal, update_watchlist_display) ...
        global watched_items, db_connection
        controls_to_disable = [fetch_button, item_input, add_watchlist_button, check_watchlist_button, enable_auto_check_cb]
        if not is_auto_run: update_status(watchlist_status_text, "Checking watchlist prices...", is_loading=True, controls_to_disable=controls_to_disable)
        items_to_check = []
        with watchlist_lock: items_to_check = list(watched_items.keys())
        if not items_to_check:
            if not is_auto_run: update_status(watchlist_status_text, "Watchlist is empty.", is_loading=False, controls_to_disable=controls_to_disable)
            else: print("Auto-check: Watchlist empty, skipping.")
            return
        total_items = len(items_to_check)
        for i, item_url_name in enumerate(items_to_check):
             if is_auto_run and stop_auto_check_flag.is_set(): print("Auto-check: Stop flag detected."); break
             with watchlist_lock:
                 friendly_name = watched_items.get(item_url_name, {}).get('friendly_name', item_url_name)
                 if item_url_name in watched_items: watched_items[item_url_name]['status'] = 'Checking...'; watched_items[item_url_name]['last_checked'] = datetime.datetime.now().strftime("%H:%M:%S")
             update_watchlist_display() # Calls page.update()
             if is_auto_run: print(f"Auto-check ({i+1}/{total_items}): Checking {friendly_name}...")
             status = check_watched_item_deal(item_url_name)
             with watchlist_lock:
                 if item_url_name in watched_items: watched_items[item_url_name]['status'] = status; watched_items[item_url_name]['last_checked'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
             update_watchlist_display() # Calls page.update()
             time.sleep(WATCHLIST_CHECK_DELAY_SECONDS)
        if not is_auto_run: update_status(watchlist_status_text, "Watchlist check complete.", is_loading=False, controls_to_disable=controls_to_disable)
        else: print("Auto-check: Finished checking all items in list.")


    def check_watched_item_deal(item_url_name):
        # ... (implementation - calls api_handler, database_handler) ...
        MIN_HISTORICAL_POINTS = 5; BUY_THRESHOLD_PERCENT = 0.85
        current_min_sell, _ = api_handler.get_current_min_max_prices(item_url_name, PLATFORM)
        if current_min_sell is None: return "Error: API Fetch Failed"
        historical_sell_prices = database_handler.get_historical_prices_for_item(db_connection, item_url_name, platform=PLATFORM, days=7, order_type='sell')
        if not historical_sell_prices or len(historical_sell_prices) < MIN_HISTORICAL_POINTS: return f"Not Enough Data (<{MIN_HISTORICAL_POINTS})"
        try: median_sell_price = statistics.median(historical_sell_prices)
        except statistics.StatisticsError: return "Error: Calculation Failed"
        threshold_price = median_sell_price * BUY_THRESHOLD_PERCENT
        print(f"Check '{item_url_name}': Current Sell={current_min_sell}, Median Sell (7d)={median_sell_price:.1f}, Threshold (<{threshold_price:.1f})")
        if current_min_sell < threshold_price: return f"Good Buy! ({current_min_sell}p < {threshold_price:.0f}p)"
        else: return f"Normal ({current_min_sell}p vs {median_sell_price:.0f}p)"


    def check_watchlist_button_clicked(e):
        # ... (implementation - starts thread) ...
        thread = threading.Thread(target=check_watchlist_prices_thread, args=(False,), daemon=True)
        thread.start()

    def remove_watchlist_item(item_url_name):
         # ... (implementation - calls update_watchlist_display) ...
         with watchlist_lock:
             if item_url_name in watched_items:
                 del watched_items[item_url_name]
                 print(f"Watchlist: Removed {item_url_name}")
         update_watchlist_display()
         save_watchlist() # <-- SAVE HERE

    # --- Auto Check Logic ---
    def run_automatic_checks():
        # ... (implementation - calls check_watchlist_prices_thread) ...
        global auto_check_active_state
        print("Auto-check thread started.")
        while not stop_auto_check_flag.is_set():
            print(f"Auto-check: Waiting for {AUTO_CHECK_INTERVAL_MINUTES} minutes...")
            stopped = stop_auto_check_flag.wait(timeout=AUTO_CHECK_INTERVAL_MINUTES * 60)
            if stopped: break
            if not stop_auto_check_flag.is_set() and auto_check_active_state:
                print("Auto-check: Starting check cycle...")
                check_watchlist_prices_thread(is_auto_run=True)
                print("Auto-check: Check cycle finished.")
            elif not auto_check_active_state:
                 print("Auto-check: Skipping cycle, auto-check disabled.")
        print("Auto-check thread stopped.")

    def toggle_automatic_checks(enabled: bool):
        # ... (implementation - manages thread) ...
        global auto_check_thread, auto_check_active_state
        auto_check_active_state = enabled
        print(f"Auto-check toggled: {'Enabled' if enabled else 'Disabled'}")
        if enabled and (auto_check_thread is None or not auto_check_thread.is_alive()):
            stop_auto_check_flag.clear()
            auto_check_thread = threading.Thread(target=run_automatic_checks, daemon=True)
            auto_check_thread.start()
        elif not enabled and auto_check_thread is not None and auto_check_thread.is_alive():
            stop_auto_check_flag.set()
            auto_check_thread = None
        # page.update() # Might need if other elements react to this state

    # --- Display Update Functions ---
    def update_live_table_display():
       # ... (implementation - uses live_order_filter, calls page.update()) ...
       # ... (includes sorting logic AFTER filtering) ...
       # ... (includes copy button creation) ...
       global current_orders_data, live_order_filter
       new_rows = []
       with data_lock:
            filtered_orders = []
            if live_order_filter == 'all': filtered_orders = current_orders_data
            elif live_order_filter == 'sell': filtered_orders = [o for o in current_orders_data if o.get('order_type') == 'sell']
            elif live_order_filter == 'buy': filtered_orders = [o for o in current_orders_data if o.get('order_type') == 'buy']
            else: filtered_orders = current_orders_data
            orders_to_display = filtered_orders
            sort_idx = live_data_table.sort_column_index
            sort_asc = live_data_table.sort_ascending
            if sort_idx is not None and sort_idx != 0:
                 def get_sort_key(order):
                     if sort_idx == 1: return order.get('item_url_name', '').lower()
                     elif sort_idx == 2: return order.get('user', {}).get('ingame_name', '').lower()
                     elif sort_idx == 3: return order.get('order_type', '').lower()
                     elif sort_idx == 4: return int(order.get('quantity', 0))
                     elif sort_idx == 5: return int(order.get('platinum', 0))
                     elif sort_idx == 6: return order.get('user', {}).get('status', '').lower()
                     else: return None
                 try: orders_to_display.sort(key=get_sort_key, reverse=not sort_asc)
                 except Exception as sort_err: print(f"Error during live table sort: {sort_err}")
            for order in orders_to_display:
                 item_name = order.get('item_url_name', '?').replace("_", " ").title()
                 user_info=order.get('user', {}); user_name=user_info.get('ingame_name','?'); user_status=user_info.get('status','?'); order_type=str(order.get('order_type','?')).capitalize(); quantity=order.get('quantity',0); price=order.get('platinum',0)
                 copy_button = ft.IconButton( icon=ft.icons.CONTENT_COPY_ROUNDED, tooltip="Copy whisper message", icon_size=16, on_click=lambda _, o=order: copy_whisper_message(o), style=ft.ButtonStyle(padding=ft.padding.only(left=0, right=0)),)
                 row = ft.DataRow(cells=[
                         ft.DataCell(copy_button),
                         ft.DataCell(ft.Text(item_name, tooltip=order.get('item_url_name'))), ft.DataCell(ft.Text(user_name, tooltip=f"Status: {user_status}")), ft.DataCell(ft.Text(order_type)),
                         ft.DataCell(ft.Text(f"{quantity}")), ft.DataCell(ft.Text(f"{price:,}")), ft.DataCell(ft.Text(user_status.capitalize())),
                     ])
                 new_rows.append(row)
       live_data_table.rows = new_rows
       print(f"UI: Live table updated with {len(new_rows)} rows (Filter: {live_order_filter}).")
       page.update()


    def update_watchlist_display():
        # ... (implementation - calls page.update()) ...
        global watched_items
        controls = []
        with watchlist_lock:
            sorted_items = sorted(watched_items.items(), key=lambda item: item[1].get('friendly_name', item[0]))
            for url_name, item_info in sorted_items:
                friendly_name = item_info.get('friendly_name', url_name)
                status = item_info.get('status', 'Unknown')
                last_checked = item_info.get('last_checked', 'Never')
                status_color = ft.colors.GREEN if "Good Buy" in status else ft.colors.ORANGE if "Error" in status or "Not Enough" in status else ft.colors.BLUE_GREY_300 if "Checking" in status else None
                controls.append(
                    ft.ListTile( title=ft.Text(friendly_name, weight=ft.FontWeight.BOLD), subtitle=ft.Text(f"Status: {status} (Checked: {last_checked})", color=status_color),
                        trailing=ft.IconButton( icon=ft.icons.DELETE_OUTLINE, tooltip=f"Remove {friendly_name}", on_click=lambda _, u=url_name: remove_watchlist_item(u), icon_color=ft.colors.RED_400),
                        data=url_name
                    )
                )
        watchlist_view.controls = controls
        page.update()

    # --- Action Handlers ---
    def live_filter_changed(new_filter_value: str):
        # ... (implementation - calls update_live_table_display) ...
        global live_order_filter
        print(f"Live filter changed to: {new_filter_value}")
        live_order_filter = new_filter_value
        update_live_table_display()

    def copy_whisper_message(order_data: dict):
        # ... (implementation - uses page.set_clipboard, update_status) ...
        # Need the global page reference here
        global app_page
        if not order_data: print("Error: No order data for copy."); return
        user_name = order_data.get('user', {}).get('ingame_name')
        item_url_name = order_data.get('item_url_name')
        price = order_data.get('platinum')
        order_type = order_data.get('order_type')
        if not all([user_name, item_url_name, price is not None, order_type]):
            update_status(search_status_text, "Error: Missing data for message.", is_error=True)
            print(f"Missing data: User={user_name}, Item={item_url_name}, Price={price}, Type={order_type}")
            return
        friendly_item_name = item_url_name.replace("_", " ").title()
        if order_type == 'sell': message = f'/w {user_name} Hi! I want to buy: "{friendly_item_name}" for {price} platinum.'
        elif order_type == 'buy': message = f'/w {user_name} Hi! I want to sell: "{friendly_item_name}" for {price} platinum.'
        else: update_status(search_status_text, "Error: Unknown order type.", is_error=True); return
        try:
            app_page.set_clipboard(message) # Use the stored page reference
            print(f"Copied: {message}")
            update_status(search_status_text, f"Copied whisper for {friendly_item_name}!", is_loading=False)
        except Exception as e:
            print(f"Error copying: {e}")
            update_status(search_status_text, "Error: Could not copy.", is_error=True)

    # Sorting Handler
    def handle_sort(e: ft.DataColumnSortEvent, table_type: str, column_index: int):
        # ... (implementation - calls update_live_table_display) ...
        print(f"Sort event: Table={table_type}, Index={column_index}, Asc={e.ascending}")
        if table_type == 'live':
            live_data_table.sort_column_index = column_index
            live_data_table.sort_ascending = e.ascending
            update_live_table_display() # Re-applies filter and sort

    # --- Assign Event Handlers ---
    fetch_button.on_click = fetch_button_clicked
    add_watchlist_button.on_click = add_watchlist_clicked
    check_watchlist_button.on_click = check_watchlist_button_clicked
    # Other handlers assigned inline (TextField submit, RadioGroup change, Checkbox change, Sort clicks, Delete clicks)

# --- Layout ---
    page.add(
        # Search Row ...
        ft.Row([item_input, fetch_button, add_watchlist_button], alignment=ft.MainAxisAlignment.START),
        ft.Row([search_status_text]),
        ft.Divider(height=5),

        # Live Data Section
        live_orders_header_row, # The Row with Title and Radio buttons
        ft.Column(               # <--- THIS is the scrolling container
            [live_data_table],     # <--- DataTable is directly inside
            scroll=ft.ScrollMode.ADAPTIVE,
            expand=2             # <--- Make sure expand has a value > 0
        ),
        ft.Divider(height=5),

        # Watchlist Section
        # ... (Watchlist header row) ...
        ft.Row([ ft.Text("Watchlist", style=ft.TextThemeStyle.HEADLINE_SMALL), ft.Column([ check_watchlist_button, enable_auto_check_cb, ], spacing=0) ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ft.Row([watchlist_status_text]),
        ft.Column(               # <--- Scrolling container for watchlist
            [watchlist_view],      # <--- ListView is directly inside
            expand=1             # <--- Make sure expand has a value > 0
        ),
    )

    # --- Initial UI Update ---
    update_watchlist_display() # Show loaded watchlist
    page.update()

# --- Run the App ---
if __name__ == "__main__":
    app_page = None # Initialize page reference
    try:
        ft.app(target=main)
    finally:
        # Signal auto-check thread to stop
        print("App closing: Signaling auto-check stop...")
        stop_auto_check_flag.set()
        if auto_check_thread and auto_check_thread.is_alive():
             # Give it a brief moment, but it's a daemon thread anyway
             auto_check_thread.join(timeout=0.5)

        # Final save of watchlist
        save_watchlist()

        # Close DB
        if db_connection:
            print("Closing database connection.")
            db_connection.close()
    print("Application closed.")