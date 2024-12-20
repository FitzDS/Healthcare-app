
import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
from openai import Client

#sys.stderr = open(os.devnull, 'w')

# Initialize session state for map, facilities, and search flag
if "map" not in st.session_state:
    st.session_state["map"] = None

if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

# Initialize session state with default location (Davis, CA coordinates)
if "latitude" not in st.session_state:
    st.session_state["latitude"] = 38.5449  # Latitude for Davis, CA
if "longitude" not in st.session_state:
    st.session_state["longitude"] = -121.7405  # Longitude for Davis, CA

csv_url = "https://raw.githubusercontent.com/FitzDS/Healthcare-app/main/providers_data_with_coordinates_threading.csv"

# Read the CSV file from GitHub
medicaid_data = pd.read_csv(csv_url)

# Set up OpenAI client
client = Client(api_key=st.secrets["api_keys"]["openai"])

# Load API keys from Streamlit secrets
GOOGLE_API_KEY = st.secrets["api_keys"]["google"]

CARE_TYPES = {
    "All Healthcare": ["hospital", "pharmacy", "doctor", "dentist", "veterinary_care", "physiotherapist"],
    "Pharmacy": "pharmacy",
    "Hospital": "hospital",
    "Doctor": "doctor",
    "Dentist": "dentist",
    "Veterinary": "veterinary_care",
    "Physiotherapist": "physiotherapist",
}

# Ensure the current location marker is persistent
if "current_location_marker" in st.session_state:
    # Access or modify the session state variable
    current_location_marker = st.session_state["current_location_marker"]
else:
    # Initialize the session state variable if it doesn't exist
    st.session_state["current_location_marker"] = None
    current_location_marker = None

@st.cache_data
def classify_issue_with_openai_cached(issue_description):
    """
    Classifies a healthcare issue description using OpenAI's API and caches the result.

    Args:
        issue_description (str): The description of the issue.

    Returns:
        str: Predicted healthcare category.
    """
    prompt = f"""
    You are an expert in healthcare classification. Classify the following issue description into one of these categories:
    {', '.join(CARE_TYPES.keys())}.

    Examples:
    - "I need medication for my cold" -> Pharmacy
    - "I broke my arm and need treatment" -> Hospital
    - "My dog needs a checkup" -> Veterinary
    - "I need help recovering from a sports injury" -> Physiotherapist
    - "I need dental work" -> Dentist

    Issue: {issue_description}
    Category:"""

    primary_model = "gpt-4o-mini"
    fallback_model = "gpt-3.5-turbo"

    try:
        # Attempt classification with the primary model
        response = client.chat.completions.create(
            model=primary_model,
            messages=[
                {"role": "system", "content": "You are a healthcare classification assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0
        )
        category = response.choices[0].message.content.strip()
        return category
    except Exception as e:
        print(f"Error with {primary_model}: {e}. Trying fallback model {fallback_model}.")
        try:
            # Attempt classification with the fallback model
            response = client.chat.completions.create(
                model=fallback_model,
                messages=[
                    {"role": "system", "content": "You are a healthcare classification assistant."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,
                temperature=0
            )
            category = response.choices[0].message.content.strip()
            return category
        except Exception as fallback_error:
            print(f"Error with fallback model {fallback_model}: {fallback_error}.")
            return "Error"

def fetch_healthcare_data_google(latitude, longitude, radius, care_type, open_only=False, medicaid_data=None):
    """
    Fetch healthcare data using Google Places API with support for multiple healthcare categories.
    Now also checks for Medicaid support.
    """
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    facilities = []

    # Ensure Medicaid data is provided
    if medicaid_data is None:
        raise ValueError("Medicaid data must be provided")

    # Round Medicaid data coordinates for consistent comparison
    medicaid_data["latitude"] = medicaid_data["latitude"].astype(float).round(5)
    medicaid_data["longitude"] = medicaid_data["longitude"].astype(float).round(5)

    if isinstance(care_type, list):
        types_to_query = care_type
    else:
        types_to_query = [care_type]

    for care_type_query in types_to_query:
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius,
            "type": care_type_query,
            "key": GOOGLE_API_KEY,
        }

        while True:
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                for result in data.get("results", []):
                    if open_only and not result.get("opening_hours", {}).get("open_now", False):
                        continue

                    VALID_MEDICAID_CATEGORIES = ["hospital", "pharmacy", "doctor", "dentist", "physiotherapist"]
                    # Facility coordinates
                    lat = round(result["geometry"]["location"]["lat"], 5)
                    lon = round(result["geometry"]["location"]["lng"], 5)

                    facility_category = result.get("types", [])
                    is_medicaid_supported_category = any(
                    category in VALID_MEDICAID_CATEGORIES for category in facility_category
                    )

                    
                    if is_medicaid_supported_category:
                    # Filter Medicaid data for the bounding box (e.g., 0.0001 degrees margin for proximity)
                        medicaid_data_filtered = medicaid_data[
                            (medicaid_data["latitude"] > lat - 0.0001) &
                            (medicaid_data["latitude"] < lat + 0.0001) &
                            (medicaid_data["longitude"] > lon - 0.0001) &
                            (medicaid_data["longitude"] < lon + 0.0001)
                        ]
    
                    
                        # Determine if the facility is Medicaid-supported using filtered data
                        medicaid_supported = not medicaid_data_filtered.empty
                    else:
                        medicaid_supported = False  # Not a valid category, so it's not Medicaid-supported


                    facilities.append({
                        "name": result.get("name", "Unknown"),
                        "address": result.get("vicinity", "N/A"),
                        "latitude": lat,
                        "longitude": lon,
                        "rating": result.get("rating", "No rating"),
                        "user_ratings_total": result.get("user_ratings_total", 0),
                        "open_now": result.get("opening_hours", {}).get("open_now", "Unknown"),
                        "wheelchair_accessible_entrance": result.get("wheelchair_accessible_entrance", False),
                        "medicaid_supported": medicaid_supported,  # Correct value
                    })

                # Check for the next page token
                next_page_token = data.get("next_page_token")
                if next_page_token:
                    import time
                    time.sleep(2)
                    params = {"pagetoken": next_page_token, "key": GOOGLE_API_KEY}
                else:
                    break
            else:
                st.error(f"Error fetching data from Google Places API: {response.status_code}")
                break

    return pd.DataFrame(facilities)

def get_lat_lon_from_query(query):
    url = f"https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": query, "key": GOOGLE_API_KEY}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]
    st.error("Location not found. Please try again.")
    return None, None

def get_current_location():
    g = geocoder.ip('me')
    if g.ok:
        return g.latlng
    st.error("Unable to detect current location.")
    return [38.5449, -121.7405]

st.markdown("""
<style>
/* Header Container */
.header-container {
    background-color: #2b2e4a;
    padding: 50px;
    border-radius: 12px;
    box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.2);
    position: relative;
    overflow: hidden;
    color: white;
}

/* Geometric Shapes */
.header-container::before,
.header-container::after {
    content: '';
    position: absolute;
    border-radius: 50%;
    filter: blur(75px);
    z-index: 0;
}

.header-container::before {
    width: 300px;
    height: 300px;
    background: rgba(76, 175, 80, 0.1); /* Light green glow */
    top: -50px;
    left: -50px;
}

.header-container::after {
    width: 350px;
    height: 350px;
    background: rgba(3, 169, 244, 0.15); /* Blue glow */
    bottom: -60px;
    right: -60px;
}

/* Title Styling */
.header-container h1 {
    font-family: 'Roboto', sans-serif;
    font-weight: 900;
    font-size: 42px;
    margin: 0;
    z-index: 1;
    position: relative;
}

.header-container p {
    font-family: 'Roboto', sans-serif;
    font-weight: 300;
    font-size: 18px;
    margin-top: 10px;
    z-index: 1;
    position: relative;
}
</style>

<div class="header-container">
    <h1>Global Healthcare Facility Locator</h1>
    <p>Find the care you need, wherever you are.</p>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<style>
.legend-container {
    border: 1px solid #ddd;
    border-radius: 12px;
    padding: 20px;
    background-color: #ffffff;
    margin-top: 20px;
    box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.1);
    text-align: left; /* Align text to the left */
}

.legend-container h3 {
    color: #2b2e4a;
    font-family: 'Roboto', sans-serif;
    font-weight: 700;
    font-size: 20px; /* Slightly smaller for better balance */
    margin-bottom: 15px;
    border-bottom: 2px solid #ddd; /* Underline the title */
    padding-bottom: 5px;
    color: black;
}

.legend-container ul {
    list-style-type: none;
    padding: 0;
    margin: 0;
}

.legend-container li {
    margin: 10px 0;
    font-family: 'Roboto', sans-serif;
    font-size: 15px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid #eee; /* Subtle separator between items */
    padding-bottom: 8px;
    color: black;
}

.legend-container li:last-child {
    border-bottom: none; /* Remove the last item's separator */
}

.legend-container li span {
    display: inline-block;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    margin-right: 10px;
    border: 1px solid #ddd; /* Add a subtle border to the markers */
}

.color-red { background-color: #ff6b6b; } /* Soft Red */
.color-green { background-color: #81c784; } /* Soft Green */
.color-blue { background-color: #64b5f6; } /* Soft Blue */
.color-orange { background-color: #ffb74d; } /* Soft Orange */
.color-yellow { background-color: #fff176; } /* Soft Yellow */
.color-gray { background-color: #cfd8dc; } /* Soft Gray */
</style>

<div class="legend-container">
    <h3>Legend</h3>
    <ul>
        <li><span class="color-red"></span><strong>Current Location</strong></li>
        <li><span class="color-green"></span><strong>4-5 Stars</strong></li>
        <li><span class="color-blue"></span><strong>3-4 Stars</strong></li>
        <li><span class="color-orange"></span><strong>2-3 Stars</strong></li>
        <li><span class="color-yellow"></span><strong>1-2 Stars</strong></li>
        <li><span class="color-gray"></span><strong>Unrated or 0-1 Stars</strong></li>
    </ul>
</div>
""", unsafe_allow_html=True)

location_query = st.text_input("Search by Location:")
# Add a toggle for units
unit_option = st.radio("Select Unit for Radius:", options=["Meters", "Miles"], index=0)

# Set conversion factor
meters_to_miles = 0.000621371  # Conversion factor from meters to miles
miles_to_meters = 1609.34      # Conversion factor from miles to meters

# Adjust the radius input based on the selected unit
if unit_option == "Meters":
    radius = st.slider("Search Radius:", min_value=500, max_value=100000, step=1000, value=20000, help="Radius in meters. Note: Only the 60 nearest facilities will be shown, as per API limitations.")
else:
    radius_in_miles = st.slider("Search Radius:", min_value=0.3, max_value=62.1, step=0.5, value=12.4, help="Radius in miles. Note: Only the 60 nearest facilities will be shown, as per API limitations.")
    radius = radius_in_miles * miles_to_meters  # Convert miles to meters

# Display the selected radius
if unit_option == "Meters":
    st.write(f"Selected Radius: {radius} meters")
else:
    st.write(f"Selected Radius: {radius / miles_to_meters:.2f} miles")

# Use the `radius` variable (always in meters) in the rest of the app
issue_description = st.text_area("Describe the issue (optional):")
care_type = st.selectbox("Type of Care (leave blank to auto-detect):", options=[""] + list(CARE_TYPES.keys()))
open_only = st.checkbox("Show only open facilities")
show_medicaid_only = st.checkbox("Show Medicaid-Supported Providers Only")
st.caption("Note: Search by medicaid-supported providers will only take into account California currently.")

filter_wheelchair_accessible = st.checkbox("Show only locations with wheelchair accessible entrances", value=False)

use_current_location = st.button("Use Current Location", key="current_location_button")
st.caption("Note: Search by location will take precedence over the 'Use Current Location' button.")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)

# Infer care type if issue description is provided
if issue_description and not care_type:
    inferred_care_type = classify_issue_with_openai_cached(issue_description)
    if inferred_care_type in CARE_TYPES:
        care_type = inferred_care_type
        st.success(f"Inferred Type of Care: {care_type}")
    else:
        st.warning("Could not classify issue; defaulting to All Healthcare.")
        care_type = "All Healthcare"

if use_current_location:
    current_location = get_current_location()
    latitude = current_location[0]
    longitude = current_location[1]
    st.write(f"Using current location: Latitude {latitude}, Longitude {longitude}")
    location_query = ""  # Clear the location query to avoid conflicts

elif location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude = lat
        longitude = lon
        st.write(f"Using location: {location_query} (Latitude: {latitude}, Longitude: {longitude})")


# After the search has been performed, retrieve the facilities and display them
facilities = st.session_state.get("facilities", pd.DataFrame())

def update_sidebar(facilities):
    st.sidebar.title("Nearby Locations")
    if not facilities.empty:
        facilities['rating'] = pd.to_numeric(facilities['rating'], errors='coerce').fillna(0)
        sorted_facilities = facilities.sort_values(by="rating", ascending=False)
        for _, row in sorted_facilities.iterrows():
            st.sidebar.markdown(f"""
            **{row['name']}**
            - Address: {row['address']}
            - Rating: {row['rating']} ⭐
            - Wheelchair Accessible Entrance: {"Yes" if row['wheelchair_accessible_entrance'] else "No"}
            - Distance: {row.get('distance', 'N/A')} km
            [Get Directions](https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']})
            """)
    else:
        st.sidebar.warning("No facilities found nearby.")

# Ensure facilities are stored in session state only after the search button is clicked
if st.button("Search", key="search_button"):

    # Initialize session state for map and facilities only when Search button is clicked
    if "map" not in st.session_state:
        st.session_state["map"] = None
    if "facilities" not in st.session_state:
        st.session_state["facilities"] = pd.DataFrame()  # Empty DataFrame initially
    
    st.write("Fetching data...")

    # Fetch facilities using Google API
    facilities = fetch_healthcare_data_google(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        care_type=CARE_TYPES.get(care_type, "hospital"),
        open_only=open_only,
        medicaid_data=medicaid_data
    )
   

    # Only apply the "Show Medicaid-Supported Providers Only" filter if enabled
    if show_medicaid_only and "medicaid_supported" in facilities.columns:
        facilities = facilities[facilities["medicaid_supported"]]
    # Apply wheelchair filter if needed
    if filter_wheelchair_accessible:
        facilities = facilities[facilities['wheelchair_accessible_entrance'] == True]

    # Store the fetched facilities in session state
    st.session_state["facilities"] = facilities

# Retrieve facilities from session state
facilities = st.session_state.get("facilities", pd.DataFrame())  # Safely retrieve facilities from session state


    # Only apply the "Show Medicaid-Supported Providers Only" filter if facilities are populated
try:
    # Your code that may raise a KeyError
    facilities = facilities[facilities["medicaid_supported"]]
except KeyError as e:
    # Handle the exception gracefully, without showing it to the user
    print(f"KeyError: {e} - This column doesn't exist, but it's being ignored.")  # Log for debugging
    # You can choose not to do anything here to continue execution
    pass


update_sidebar(st.session_state.facilities)

# Ensure facilities are stored in session state
# Ensure facilities are stored in session state
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

# Retrieve facilities from session state
facilities = st.session_state["facilities"]


# Check if facilities are empty to display map or error message
if facilities.empty:
    st.error("No facilities found. Check your location or radius.")
    st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
else:
    st.write(f"Inferred Type of Care: {len(facilities)} facilities found.")
    m = folium.Map(location=[latitude, longitude], zoom_start=12)
    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=True,
        fill_opacity=0.4
    ).add_to(m)

    for _, row in facilities.iterrows():
        wheelchair_accessible = row.get('wheelchair_accessible_entrance', False)
        # Assign a color based on ratings
        color = "gray"  # Default color for unrated
        if row["rating"] != "No rating" and row["rating"]:
            if float(row["rating"]) >= 4:
                color = "green"
            elif float(row["rating"]) >= 3:
                color = "blue"
            elif float(row["rating"]) >= 2:
                color = "orange"
            elif float(row["rating"]) >= 1:
                color = "yellow"

        # Generate the directions link
        directions_link = f"https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']}"

        # Add marker with "Get Directions" link
        popup_content = f"""
        <b>{row['name']}</b><br>
        Address: {row['address']}<br>
        Open Now: {"Open" if row['open_now'] else "Closed"}<br>
        Medicaid Supported: {"Yes" if row["medicaid_supported"] else "No"}<br>
        Rating: {row['rating']} ({row['user_ratings_total']} reviews)<br>
        Wheelchair Accessible Entrance: {"Yes" if row['wheelchair_accessible_entrance'] else "No"}<br>
        <a href="{directions_link}" target="_blank">Get Directions</a>
        """
        folium.Marker(
            location=[row["latitude"], row["longitude"]],
            popup=folium.Popup(popup_content, max_width=300),
            icon=folium.Icon(color=color)
        ).add_to(m)

    # Add current location marker
    folium.Marker(
        location=[latitude, longitude],
        popup="Current Location",
        icon=folium.Icon(icon="info-sign", color="red")
    ).add_to(m)

    st.session_state["map"] = m

if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
else:
    default_map = folium.Map(location=[latitude, longitude], zoom_start=12)
    folium.Marker(
        location=[latitude, longitude],
        popup="Current Location",
        icon=folium.Icon(icon="info-sign", color="red")
    ).add_to(default_map)
    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=True,
        fill_opacity=0.4
    ).add_to(default_map)
    st_folium(default_map, width=700, height=500)

st.markdown("""
<div style="text-align: center;">
    <a href="https://docs.google.com/forms/d/e/1FAIpQLScgTWRrJggbHv6dXIXRIyG6vk02VIxPSlecwVfK0kg_7EESpw/viewform?usp=dialog" target="_blank" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-size: 16px;">
        📝 Fill Out Feedback Form
    </a>
</div>
""", unsafe_allow_html=True)
