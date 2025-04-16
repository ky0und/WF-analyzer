# warframe_market_tracker/main.py
import flet as ft
import requests # <-- Import requests for API calls

# Remove direct imports of api_handler and database_handler from frontend
# import api_handler
# import database_handler

# --- Configuration ---
PLATFORM = "pc"
# Remove DB/File paths
# DB_FILE = "market_data.db"
# WATCHLIST_FILE = "watchlist.json"
# Remove check delays - API calls handle timing
# WATCHLIST_CHECK_DELAY_SECONDS = 1.5
# Remove auto-check config
# AUTO_CHECK_INTERVAL_MINUTES = 30

# API Base URL (adjust if needed, depends on Vercel deployment / local testing)
API_BASE_URL = "/api" # Use relative path for deployment

# --- Global Variables ---
# Remove db_connection
current_orders_data = []
watched_items = {} # Will be loaded via API
# data_lock likely still useful for UI updates if rendering is complex
# watchlist_lock useful for updating local copy before potentially saving via API
live_order_filter = 'all'
# Remove auto-check globals
# auto_check_thread = None
# stop_auto_check_flag = threading.Event()
# auto_check_active_state = False

# --- Helper Function (Item Name Formatting - Keep) ---
def format_item_name_for_api(user_input):
    if not user_input: return None
    formatted = user_input.lower().strip().replace(' ', '_')
    return formatted

# --- Flet Application ---
def main(page: ft.Page):
    global current_orders_data, watched_items, live_order_filter
    global app_page # Keep page reference for clipboard
    app_page = page

    page.title = "Warframe Market Tracker (Web)"
    page.vertical_alignment = ft.MainAxisAlignment.START
    # Adjust window properties if needed for desktop testing
    page.window_width = 1050
    page.window_height = 800
    page.window_resizable = True
    page.window_min_width = 700
    page.window_min_height = 500
    page.update()

    # --- Define GUI Elements (Keep definitions, remove auto-check checkbox) ---
    item_input = ft.TextField(label="Item Name", hint_text="Enter item name", autofocus=True, width=350, on_submit=lambda e: fetch_button_clicked(e))
    fetch_button = ft.ElevatedButton("Fetch Item Orders", icon=ft.icons.SEARCH, tooltip="Fetch live orders")
    add_watchlist_button = ft.ElevatedButton("Add to Watchlist", icon=ft.icons.ADD_CIRCLE_OUTLINE, tooltip="Add the searched item", disabled=True)
    search_status_text = ft.Text("Enter an item name and press 'Fetch' or Enter.", italic=True)
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
    watchlist_view = ft.ListView(expand=True, spacing=5)

    # --- Core Logic ---
    def update_status(target_text_widget, message, is_loading=False, is_error=False, controls_to_disable=None):
        # ... (Implementation remains the same - uses page.update()) ...
        target_text_widget.value = message
        target_text_widget.italic = not is_loading and not is_error
        target_text_widget.color = ft.colors.RED if is_error else ft.colors.with_opacity(0.7, ft.colors.ON_SURFACE) if is_loading else None
        if controls_to_disable:
            for control in controls_to_disable: control.disabled = is_loading
        page.update()

    # --- NEW: Function to Load Initial Data from API ---
    def load_initial_data():
        global watched_items
        print("Loading initial watchlist data from API...")
        update_status(watchlist_status_text, "Loading watchlist...", is_loading=True)
        try:
            response = requests.get(f"{API_BASE_URL}/watchlist", timeout=10)
            response.raise_for_status() # Raise exception for bad status codes
            loaded_data = response.json()
            watched_items = loaded_data if isinstance(loaded_data, dict) else {}
            print(f"Watchlist loaded via API. Items: {len(watched_items)}")
            update_watchlist_display() # Update UI
            update_status(watchlist_status_text, "Watchlist loaded.", is_loading=False)
        except requests.exceptions.RequestException as e:
            print(f"Error loading watchlist via API: {e}")
            update_status(watchlist_status_text, "Error loading watchlist.", is_error=True)
            watched_items = {} # Ensure empty on error
            update_watchlist_display() # Show empty list


    # --- Modified Action Handlers ---
    def fetch_button_clicked(e):
        global current_orders_data
        user_input = item_input.value
        if not user_input or not user_input.strip():
            update_status(search_status_text, "Please enter an item name.", is_error=True); item_input.error_text = "Cannot be empty"; page.update(); return
        item_input.error_text = None; add_watchlist_button.disabled = True; page.update()
        item_url_name = format_item_name_for_api(user_input)

        # Disable controls during API call
        controls = [fetch_button, item_input, add_watchlist_button, check_watchlist_button]
        update_status(search_status_text, f"Fetching: {user_input.strip()}...", is_loading=True, controls_to_disable=controls)
        live_data_table.rows = []; page.update() # Clear table

        try:
            api_url = f"{API_BASE_URL}/fetch_item"
            params = {'name': item_url_name, 'platform': PLATFORM}
            response = requests.get(api_url, params=params, timeout=25) # Longer timeout for backend processing
            response.raise_for_status()
            data = response.json()

            if "orders" in data and isinstance(data["orders"], list):
                current_orders_data = data["orders"]
                status_message = f"Displaying {len(current_orders_data)} orders for {user_input.strip()}."
                is_error = False
                add_watchlist_button.disabled = False
                add_watchlist_button.data = {'url_name': item_url_name, 'friendly_name': user_input.strip()}
            else:
                current_orders_data = []
                status_message = f"No orders found or API error for {user_input.strip()}."
                is_error = True # Treat as error for status color

            update_live_table_display()
            update_status(search_status_text, status_message, is_loading=False, is_error=is_error, controls_to_disable=controls)

        except requests.exceptions.RequestException as ex:
            print(f"Error calling /api/fetch_item: {ex}")
            update_status(search_status_text, f"Error fetching {user_input.strip()}.", is_error=True, controls_to_disable=controls)
            current_orders_data = []
            update_live_table_display()
        except Exception as ex_gen: # Catch potential JSON errors etc.
             print(f"Generic Error calling /api/fetch_item: {ex_gen}")
             update_status(search_status_text, f"Error processing data for {user_input.strip()}.", is_error=True, controls_to_disable=controls)
             current_orders_data = []
             update_live_table_display()


    def add_watchlist_clicked(e):
        global watched_items
        item_data = add_watchlist_button.data
        if not item_data: return
        url_name = item_data['url_name']
        friendly_name = item_data['friendly_name']
        new_watchlist = {}


        # Create a copy to modify
        new_watchlist = watched_items.copy()
        if url_name not in new_watchlist:
            new_watchlist[url_name] = {'status': 'Not Checked', 'last_checked': None, 'friendly_name': friendly_name}
            update_local_state = True
            status_msg = f"Added '{friendly_name}' to watchlist."
            is_err = False
        else:
            update_local_state = False # Don't update local if already exists
            status_msg = f"'{friendly_name}' is already on watchlist."
            is_err = True

        if update_local_state:
             # Attempt to save via API
             try:
                 print("Calling POST /api/watchlist to save...")
                 response = requests.post(f"{API_BASE_URL}/watchlist", json=new_watchlist, timeout=10)
                 response.raise_for_status()
                 # If API save succeeds, update the global state
                 watched_items = new_watchlist
                 update_watchlist_display()
                 update_status(search_status_text, status_msg, is_error=is_err)
                 print("Watchlist saved via API successfully.")
             except requests.exceptions.RequestException as ex:
                  print(f"Error saving watchlist via API: {ex}")
                  update_status(search_status_text, f"Error saving '{friendly_name}' to watchlist.", is_error=True)
        else:
              # Just show the status message if item already exists
              update_status(search_status_text, status_msg, is_error=is_err)


    def remove_watchlist_item(item_url_name):
         global watched_items
         new_watchlist = {}
         item_removed_locally = False
         if item_url_name in watched_items:
             new_watchlist = watched_items.copy()
             del new_watchlist[item_url_name]
             item_removed_locally = True
         else:
             print(f"Item {item_url_name} not found in local watchlist for removal.")

         if item_removed_locally:
             # Attempt to save the reduced list via API
              try:
                 print(f"Calling POST /api/watchlist to remove {item_url_name}...")
                 response = requests.post(f"{API_BASE_URL}/watchlist", json=new_watchlist, timeout=10)
                 response.raise_for_status()
                 # If API save succeeds, update the global state
                 watched_items = new_watchlist
                 update_watchlist_display()
                 print(f"Removed {item_url_name} via API successfully.")
                 # Optional: Update status bar
                 # update_status(watchlist_status_text, f"Removed '{item_url_name}'.")
              except requests.exceptions.RequestException as ex:
                  print(f"Error removing item {item_url_name} via API: {ex}")
                  update_status(watchlist_status_text, f"Error removing item.", is_error=True)


    def check_watchlist_button_clicked(e):
         # This now just triggers the backend check
         # The backend should ideally update statuses in the DB
         # The frontend then needs to re-fetch the watchlist to see updates
         controls = [fetch_button, item_input, add_watchlist_button, check_watchlist_button]
         update_status(watchlist_status_text, "Initiating watchlist check...", is_loading=True, controls_to_disable=controls)
         try:
              print("Calling POST /api/check_watchlist...")
              response = requests.post(f"{API_BASE_URL}/check_watchlist", timeout=10) # Short timeout, just triggers
              response.raise_for_status()
              # Suggest user re-fetches or implement polling/websockets later
              update_status(watchlist_status_text, "Check initiated. Reload watchlist soon for updates.", is_loading=False, controls_to_disable=controls)
              # Optionally, trigger a delayed reload:
              # threading.Timer(5.0, load_initial_data).start() # Reload after 5s
         except requests.exceptions.RequestException as ex:
              print(f"Error calling /api/check_watchlist: {ex}")
              update_status(watchlist_status_text, "Error initiating check.", is_error=True, controls_to_disable=controls)

    # --- Display Update Functions (Keep update_live_table_display, update_watchlist_display) ---
    # Ensure they don't rely on deleted threads or DB connection
    def update_live_table_display():
        # ... (Implementation mostly same, uses data_lock, current_orders_data) ...
        # ... (Must call page.update() at the end) ...
        global current_orders_data, live_order_filter
        new_rows = []
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
            row = ft.DataRow(cells=[ ft.DataCell(copy_button), ft.DataCell(ft.Text(item_name, tooltip=order.get('item_url_name'))), ft.DataCell(ft.Text(user_name, tooltip=f"Status: {user_status}")), ft.DataCell(ft.Text(order_type)), ft.DataCell(ft.Text(f"{quantity}")), ft.DataCell(ft.Text(f"{price:,}")), ft.DataCell(ft.Text(user_status.capitalize())), ])
            new_rows.append(row)
        live_data_table.rows = new_rows
        print(f"UI: Live table updated with {len(new_rows)} rows (Filter: {live_order_filter}).")
        page.update()


    def update_watchlist_display():
        # ... (Implementation mostly same, reads global watched_items, calls page.update()) ...
         global watched_items
         controls = []
         sorted_items = sorted(watched_items.items(), key=lambda item: item[1].get('friendly_name', item[0]))
         for url_name, item_info in sorted_items:
             friendly_name = item_info.get('friendly_name', url_name)
             status = item_info.get('status', 'Unknown') # Status now comes from DB via API
             last_checked = item_info.get('last_checked', 'Never')
             status_color = ft.colors.GREEN if "Good Buy" in status else ft.colors.ORANGE if "Error" in status or "Not Enough" in status else ft.colors.BLUE_GREY_300 if "Checking" in status else None
             controls.append( ft.ListTile( title=ft.Text(friendly_name, weight=ft.FontWeight.BOLD), subtitle=ft.Text(f"Status: {status} (Checked: {last_checked})", color=status_color), trailing=ft.IconButton( icon=ft.icons.DELETE_OUTLINE, tooltip=f"Remove {friendly_name}", on_click=lambda _, u=url_name: remove_watchlist_item(u), icon_color=ft.colors.RED_400), data=url_name ) )
         watchlist_view.controls = controls
         page.update()


    # --- Other Handlers (Keep live_filter_changed, copy_whisper_message, handle_sort) ---
    def live_filter_changed(new_filter_value: str):
        global live_order_filter
        print(f"Live filter changed to: {new_filter_value}")
        live_order_filter = new_filter_value
        update_live_table_display()

    def copy_whisper_message(order_data: dict):
         global app_page
         # ... (Implementation mostly same, uses app_page.set_clipboard) ...
         if not order_data: print("Error: No order data for copy."); return
         user_name = order_data.get('user', {}).get('ingame_name')
         item_url_name = order_data.get('item_url_name')
         price = order_data.get('platinum')
         order_type = order_data.get('order_type')
         if not all([user_name, item_url_name, price is not None, order_type]): update_status(search_status_text, "Error: Missing data for message.", is_error=True); print(f"Missing data: User={user_name}, Item={item_url_name}, Price={price}, Type={order_type}"); return
         friendly_item_name = item_url_name.replace("_", " ").title()
         if order_type == 'sell': message = f'/w {user_name} Hi! I want to buy: "{friendly_item_name}" for {price} platinum.'
         elif order_type == 'buy': message = f'/w {user_name} Hi! I want to sell: "{friendly_item_name}" for {price} platinum.'
         else: update_status(search_status_text, "Error: Unknown order type.", is_error=True); return
         try: app_page.set_clipboard(message); print(f"Copied: {message}"); update_status(search_status_text, f"Copied whisper for {friendly_item_name}!", is_loading=False)
         except Exception as e: print(f"Error copying: {e}"); update_status(search_status_text, "Error: Could not copy.", is_error=True)


    def handle_sort(e: ft.DataColumnSortEvent, table_type: str, column_index: int):
        print(f"Sort event: Table={table_type}, Index={column_index}, Asc={e.ascending}")
        if table_type == 'live':
            live_data_table.sort_column_index = column_index
            live_data_table.sort_ascending = e.ascending
            update_live_table_display()

    # --- Assign Event Handlers (Remove auto-check related) ---
    fetch_button.on_click = fetch_button_clicked
    add_watchlist_button.on_click = add_watchlist_clicked
    check_watchlist_button.on_click = check_watchlist_button_clicked

    # --- Layout (Remove auto-check checkbox) ---
    page.add(
        ft.Row([item_input, fetch_button, add_watchlist_button], alignment=ft.MainAxisAlignment.START),
        ft.Row([search_status_text]),
        ft.Divider(height=5),
        live_orders_header_row,
        ft.Column([live_data_table], scroll=ft.ScrollMode.ADAPTIVE, expand=2),
        ft.Divider(height=5),
        ft.Row([ ft.Text("Watchlist", style=ft.TextThemeStyle.HEADLINE_SMALL), ft.Column([ check_watchlist_button, ], spacing=0) ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN), # Removed checkbox
        ft.Row([watchlist_status_text]),
        ft.Column([watchlist_view], expand=1),
    )

    # --- Initial Data Load from API---
    load_initial_data() # Fetch watchlist on startup
    # Don't call update_watchlist_display here, load_initial_data does it
    # page.update() # load_initial_data calls update

# --- Run the App (No major changes needed here, cleanup is gone) ---
if __name__ == "__main__":
    app_page = None
    # NOTE: Running locally like this won't typically have the API running
    # unless you run `python api/index.py` separately.
    # Use `vercel dev` for proper local testing of frontend + API.
    ft.app(target=main) # Can add port=... view=ft.WEB_BROWSER here for local web testing
    print("Application closed.")