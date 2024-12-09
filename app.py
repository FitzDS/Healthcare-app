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
GEOAPIFY_API_KEY = st.secrets["api_keys"]["geoapify"]
GOOGLE_API_KEY = st.secrets["api_keys"]["google"]

CARE_TYPES = {
    "All Healthcare": "healthcare",
    "Pharmacy": "healthcare.pharmacy",
    "Hospital": "healthcare.hospital",
    "Clinic": "healthcare.clinic",
    "Dentist": "healthcare.dentist",
    "Rehabilitation": "healthcare.rehabilitation",
    "Emergency": "healthcare.emergency",
    "Veterinary": "healthcare.veterinary",
}

LANGUAGES = {"English": "en", "Spanish": "es"}
selected_language = st.selectbox("Choose Language / Seleccione el idioma:", options=LANGUAGES.keys())
language_code = LANGUAGES[selected_language]

# Initialize session state for map and facilities
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

# Ensure the current location marker is persistent
if "current_location_marker" not in st.session_state:
    st.session_state["current_location_marker"] = None

def classify_issue_with_openai(issue_description):
    """
    Classifies a healthcare issue description using OpenAI's API.

    Args:
        issue_description (str): The description of the issue.

    Returns:
        str: Predicted healthcare category.
    """
    prompt = f"""
    You are an expert in healthcare classification. Classify the following issue description into one of these categories:
    {', '.join(CARE_TYPES.keys())}.

    Issue: {issue_description}
    Category:"""
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a healthcare classification assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=50,
            temperature=0
        )
        category = response.choices[0].message.content.strip()
        return category
    except Exception as e:
        st.error(f"Error during classification: {e}")
        return "Error"


def enhance_facility_data_with_google(facility):
    """
    Enhance facility details using Google Places API.
    """
    query = facility.get("name", "Unknown")
    params = {
        "input": query,
        "inputtype": "textquery",
        "fields": "name,formatted_address,rating,user_ratings_total,opening_hours",
        "key": GOOGLE_API_KEY,
    }
    response = requests.get("https://maps.googleapis.com/maps/api/place/findplacefromtext/json", params=params)

    # Check for successful API response
    if response.status_code == 200:
        data = response.json()

        # Handle cases where no candidates are found
        if not data.get("candidates"):
            st.warning(f"No matching data found for {query}")
            return facility  # Return the original facility data

        # Enhance facility with first matching candidate's data
        candidate = data["candidates"][0]
        facility["address"] = candidate.get("formatted_address", facility.get("address", "N/A"))
        facility["rating"] = candidate.get("rating", facility.get("rating", "No rating"))
        facility["user_ratings_total"] = candidate.get("user_ratings_total", facility.get("user_ratings_total", 0))
        facility["open_now"] = candidate.get("opening_hours", {}).get("open_now", facility.get("open_now", "Unknown"))
    else:
        st.error(f"Google API error: {response.status_code}")
    
    return facility




def fetch_healthcare_data(latitude, longitude, radius, care_type, open_only=False):
    """
    Fetch healthcare facilities using the Geoapify Places API.

    Args:
        latitude (float): Latitude of the location.
        longitude (float): Longitude of the location.
        radius (int): Search radius in meters.
        care_type (str): Category of healthcare (e.g., 'healthcare.hospital').
        open_only (bool): Whether to include only currently open facilities.

    Returns:
        pd.DataFrame: A DataFrame with facility information.
    """
    url = f"https://api.geoapify.com/v2/places"
    params = {
        "categories": care_type,
        "filter": f"circle:{longitude},{latitude},{radius}",
        "limit": 50,
        "apiKey": GEOAPIFY_API_KEY,
    }

    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        facilities = []
        for feature in data.get("features", []):
            properties = feature["properties"]

            # Ensure the facility matches the requested care type
            if care_type not in properties.get("categories", []):
                continue

            # Skip facilities that are not open if open_only is True
            if open_only and not properties.get("opening_hours", {}).get("open_now", False):
                continue

            facility = {
                "name": properties.get("name", "Unknown"),
                "address": properties.get("formatted", "N/A"),
                "latitude": feature["geometry"]["coordinates"][1],
                "longitude": feature["geometry"]["coordinates"][0],
                "rating": properties.get("rating", "No rating"),
                "user_ratings_total": properties.get("user_ratings_total", 0),
                "open_now": properties.get("opening_hours", {}).get("open_now", "Unknown"),
            }
            facilities.append(facility)

        return pd.DataFrame(facilities)
    else:
        st.error(f"Error fetching data from Geoapify Places API: {response.status_code}")
        return pd.DataFrame()






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

st.title("Healthcare Facility Locator")

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
radius = st.slider("Search Radius (meters):", min_value=500, max_value=200000, step=1000, value=20000)
issue_description = st.text_area("Describe the issue (optional):")
care_type = st.selectbox("Type of Care (leave blank to auto-detect):", options=[""] + list(CARE_TYPES.keys()))
open_only = st.checkbox("Show only open facilities")

if language_code == "es":
    st.caption("Nota: La búsqueda por ubicación tendrá prioridad sobre el botón 'Usar ubicación actual'.")
else:
    st.caption("Note: Search by location will take precedence over the 'Use Current Location' button.")

use_current_location = st.button("Use Current Location", key="current_location_button")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)

# Infer care type if issue description is provided
if issue_description and not care_type:
    inferred_care_type = classify_issue_with_openai(issue_description)
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

if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES.get(care_type, "hospital"))

    if facilities.empty:
        st.error("No facilities found. Check your API key, location, or radius.")
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
    else:
        st.write(f"Found {len(facilities)} facilities.")
        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities.iterrows():
            # Convert row to dictionary and enhance it
            facility = row.to_dict()
            for facility in facilities:
                if not facility.get("name"):
                    st.error(f"Facility missing name: {facility}")
                    continue
                if "latitude" not in facility or "longitude" not in facility:
                    st.error(f"Facility missing coordinates: {facility}")
                    continue
            enhanced_facility = enhance_facility_data_with_google(facility)
            
            # Determine marker color based on rating
            color = "gray"  # Default color for unrated
            if enhanced_facility["rating"] != "No rating" and enhanced_facility["rating"]:
                if float(enhanced_facility["rating"]) >= 4:
                    color = "green"
                elif float(enhanced_facility["rating"]) >= 3:
                    color = "blue"
                elif float(enhanced_facility["rating"]) >= 2:
                    color = "orange"
                elif float(enhanced_facility["rating"]) >= 1:
                    color = "yellow"
            
            # Add marker to the map
            folium.Marker(
                location=[enhanced_facility["latitude"], enhanced_facility["longitude"]],
                popup=f"""
                    <b>{enhanced_facility.get('name', 'Unknown')}</b><br>
                    Address: {enhanced_facility.get('address', 'N/A')}<br>
                    Open Now: {enhanced_facility.get('open_now', 'Unknown')}<br>
                    Rating: {enhanced_facility.get('rating', 'No rating')} ({enhanced_facility.get('user_ratings_total', '0')} reviews)<br>
                    <a href="https://www.google.com/maps/dir/?api=1&destination={enhanced_facility['latitude']},{enhanced_facility['longitude']}" target="_blank" style="color:blue; text-decoration:underline;">Get Directions</a>
                """,
                icon=folium.Icon(color=color)
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
