import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
from openai import Client

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

# Initialize session state for map and facilities
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

# Ensure the current location marker is persistent
if "current_location_marker" not in st.session_state:
    st.session_state["current_location_marker"] = None

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


wheelchair_filter = st.checkbox("Show only wheelchair-accessible facilities")

def fetch_healthcare_data_google(latitude, longitude, radius, care_type, open_only=False):
    """
    Fetch healthcare data using Google Places API with debugging for wheelchair accessibility.

    Args:
        latitude (float): Latitude of the search center.
        longitude (float): Longitude of the search center.
        radius (int): Search radius in meters.
        care_type (str or list): Type of healthcare facility to search for (single or multiple).
        open_only (bool): Whether to include only currently open facilities.

    Returns:
        pd.DataFrame: A DataFrame containing healthcare facility details.
    """
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    facilities = []

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
            st.write("Raw API Response:", response.json())  # Debugging step
            if response.status_code == 200:
                data = response.json()
                for result in data.get("results", []):
                    if open_only and not result.get("opening_hours", {}).get("open_now", False):
                        continue

                    accessibility = result.get("accessibility", {})
                    wheelchair_accessible = all([
                        accessibility.get("wheelchairAccessibleEntrance", None) is True,
                        accessibility.get("wheelchairAccessibleParking", None) is True,
                        accessibility.get("wheelchairAccessibleRestroom", None) is True,
                        accessibility.get("wheelchairAccessibleSeating", None) is True,
                    ])

                    facilities.append({
                        "name": result.get("name", "Unknown"),
                        "address": result.get("vicinity", "N/A"),
                        "latitude": result["geometry"]["location"]["lat"],
                        "longitude": result["geometry"]["location"]["lng"],
                        "rating": result.get("rating", "No rating"),
                        "user_ratings_total": result.get("user_ratings_total", 0),
                        "open_now": result.get("opening_hours", {}).get("open_now", "Unknown"),
                        "wheelchair_accessible": wheelchair_accessible,
                    })

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

st.title("Global Healthcare Facility Locator")

# Add legend above the map
st.markdown(f"""### Legend
- **Red Marker**: Current Location
- **Rating Colors**:
  - **Green**: 4-5 Stars
  - **Blue**: 3-4 Stars
  - **Orange**: 2-3 Stars
  - **Yellow**: 1-2 Stars
  - **Gray**: Unrated or 0-1 Stars
""")

location_query = st.text_input("Search by Location:")
radius = st.slider("Search Radius (meters):", min_value=500, max_value=100000, step=1000, value=20000, help="Note: Only the 60 nearest facilities will be shown, as per API limitations.")
issue_description = st.text_area("Describe the issue (optional):")
care_type = st.selectbox("Type of Care (leave blank to auto-detect):", options=[""] + list(CARE_TYPES.keys()))
open_only = st.checkbox("Show only open facilities")
st.caption("Note: Search by location will take precedence over the 'Use Current Location' button.")

use_current_location = st.button("Use Current Location", key="current_location_button")
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

# Ensure facilities are stored in session state
# Ensure facilities are stored in session state
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    # Fetch facilities using Google API
    facilities = fetch_healthcare_data_google(
        latitude=latitude,
        longitude=longitude,
        radius=radius,
        care_type=CARE_TYPES.get(care_type, "hospital"),
        open_only=open_only
    )

    # Filter for wheelchair accessibility if the checkbox is checked
    if wheelchair_filter:
        facilities = facilities[facilities["wheelchair_accessible"] == True]
    
    # Store the facilities in session state
    st.session_state["facilities"] = facilities

# Display facilities if available
facilities = st.session_state.get("facilities", pd.DataFrame())
if not facilities.empty:
    st.write(f"{len(facilities)} facilities found.")
    st.dataframe(facilities)
else:
    st.warning("No facilities found.")

# Sidebar with sorted list of locations
st.sidebar.title("Nearby Locations")
if not facilities.empty:
    # Ensure 'rating' is numeric, replacing non-numeric or missing values with 0
    facilities['rating'] = pd.to_numeric(facilities['rating'], errors='coerce').fillna(0)

    # Sort facilities by rating (descending)
    sorted_facilities = facilities.sort_values(by="rating", ascending=False)

    # Populate sidebar with sorted facilities
    for _, row in sorted_facilities.iterrows():
        st.sidebar.markdown(f"""
        **{row['name']}**
        - Address: {row['address']}
        - Rating: {row['rating']} ⭐
        - Distance: {row.get('distance', 'N/A')} km
        [Get Directions](https://www.google.com/maps/dir/?api=1&destination={row['latitude']},{row['longitude']})
        """)
else:
    st.sidebar.warning("No facilities found nearby.")

# Check if facilities are empty to display map or error message
if facilities.empty:
    st.error("No facilities found. Check your API key, location, or radius.")
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
        Open Now: {row['open_now']}<br>
        Rating: {row['rating']} ({row['user_ratings_total']} reviews)<br>
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


