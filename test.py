import requests
import json
import pandas as pd
import pytz
import zipfile
import io

# --- CONFIGURATION ---
# Replace with your actual OC Transpo API Key
OC_TRANSPO_API_KEY = 'YOUR_API_KEY_HERE'
OC_TRANSPO_BASE_URL = 'https://api.octranspo.com/' 

# OC Transpo API URLs
STATIC_FILES_URL = "https://oct-gtfs-emasagcnfmcgeham.z01.azurefd.net/public-access/GTFSExport.zip"
ENDPOINT = "gtfs-rt-tp/beta/v1/TripUpdates?format=json"

def time_string_to_seconds(time_str):
    """Converts HH:MM:SS to seconds from midnight."""
    if pd.isna(time_str):
        return pd.NA
    try:
        parts = str(time_str).split(':')
        h, m, s = map(int, parts) if len(parts) == 3 else (int(parts[0]), int(parts[1]), 0)
        return h * 3600 + m * 60 + s
    except:
        return pd.NA

def load_static_files(url):
    """Downloads and unzips static GTFS files into DataFrames."""
    print("Downloading static GTFS files...")
    gtfs_dfs = {}
    response = requests.get(url)
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        for file in z.namelist():
            if file.endswith('.txt'):
                name = file.replace('.txt', '')
                gtfs_dfs[name] = pd.read_csv(z.open(file))
    return gtfs_dfs

def fetch_realtime_updates(api_url, key, tz_obj):
    """Fetches real-time JSON updates from OC Transpo."""
    print("Fetching real-time trip updates...")
    header = {"Ocp-Apim-Subscription-Key": key}
    response = requests.get(api_url, headers=header)
    data = response.json()
    
    parsed = []
    for entity in data.get('Entity', []):
        if "TripUpdate" in entity:
            tu = entity["TripUpdate"]
            trip = tu.get("Trip", {})
            for stop_update in tu.get("StopTimeUpdate", []):
                parsed.append({
                    'trip_id': str(trip.get("TripId")),
                    'stop_id': str(stop_update.get("StopId")),
                    'stop_sequence': int(stop_update.get("StopSequence")),
                    'rt_arrival_utc': pd.to_datetime(stop_update.get("Arrival", {}).get("Time"), unit='s', utc=True)
                })
    
    df = pd.DataFrame(parsed)
    if not df.empty:
        df['rt_arrival_local'] = df['rt_arrival_utc'].dt.tz_convert(tz_obj)
    return df

def run_immediate_fetch():
    # 1. Get Static Data
    static_data = load_static_files(STATIC_FILES_URL)
    
    # Get Timezone
    try:
        agency_tz = pytz.timezone(static_data['agency']['agency_timezone'].iloc[0])
    except:
        agency_tz = pytz.timezone('America/Toronto')

    # 2. Get Real-Time Data
    rt_url = f"{OC_TRANSPO_BASE_URL}{ENDPOINT}"
    rt_df = fetch_realtime_updates(rt_url, OC_TRANSPO_API_KEY, agency_tz)

    if rt_df.empty:
        print("No real-time data available at this moment.")
        return

    # 3. Transform Static Data for Merging
    stop_times = static_data['stop_times'].copy()
    stop_times['trip_id'] = stop_times['trip_id'].astype(str)
    stop_times['stop_id'] = stop_times['stop_id'].astype(str)
    stop_times['sched_sec'] = stop_times['arrival_time'].apply(time_string_to_seconds)

    # 4. Merge Real-time and Scheduled data
    merged = pd.merge(
        rt_df, 
        stop_times[['trip_id', 'stop_id', 'stop_sequence', 'sched_sec']], 
        on=['trip_id', 'stop_id', 'stop_sequence'], 
        how='left'
    )

    # 5. Calculate Scheduled Local Datetime
    merged['service_date'] = merged['rt_arrival_local'].dt.normalize()
    merged['scheduled_arrival_local'] = merged['service_date'] + pd.to_timedelta(merged['sched_sec'], unit='s')

    # Show Results
    output_cols = ['trip_id', 'stop_id', 'rt_arrival_local', 'scheduled_arrival_local']
    print("\n--- RESULTS ---")
    print(merged[output_cols].head(20)) # Display first 20 results

if __name__ == "__main__":
    run_immediate_fetch()