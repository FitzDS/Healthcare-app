import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
import openai

# Load API keys
GEOAPIFY_API_KEY = st.secrets["api_keys"]["geoapify"]
GOOGLE_API_KEY = st.secrets["api_keys"]["google"]
OPENAI_API_KEY = st.secrets["api_keys"]["openai"]

# Set OpenAI API key
openai.api_key = OPENAI_API_KEY

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
if "care_type" not in st.session_state:
    st.session_state["care_type"] = "All Healthcare"

def fetch_healthcare_data(latitude, longitude, radius, care_type):
    url = f"https://api.geoapify.com/v2/places"
    params = {
        "categories": care_type,
        "filter": f"circle:{longitude},{latitude},{radius}",
        "limit": 100,
        "apiKey": GEOAPIFY_API_KEY,
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        facilities = []
        for feature in data.get("features", []):
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            facility = {
                "name": properties.get("name", "Unknown"),
                "address": properties.get("formatted", "N/A"),
                "latitude": geometry.get("coordinates", [])[1],
                "longitude": geometry.get("coordinates", [])[0],
                "category": properties.get("categories", ["healthcare"])[0]
            }
            facilities.append(facility)
        return pd.DataFrame(facilities)
    else:
        st.error(f"Error fetching data from Geoapify: {response.status_code}")
        return pd.DataFrame()

def determine_care_type(issue_description):
    prompt = (
        f"Based on the following description, suggest a healthcare facility category: {issue_description}. "
        "Categories: Pharmacy, Hospital, Clinic, Dentist, Rehabilitation, Emergency, Veterinary, All Healthcare."
    )
    try:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=50
        )
        care_type = response.choices[0].text.strip()
        return CARE_TYPES.get(care_type, "healthcare")  # Default to "healthcare" if no match
    except Exception as e:
        st.error(f"Error determining care type: {e}")
        return "healthcare"

st.title("Healthcare Facility Locator")

# Add legend above the map
st.markdown("""### Legend
- **Red Marker**: Current Location
- **Rating Colors**:
  - **Green**: 4-5 Stars
  - **Blue**: 3-4 Stars
  - **Orange**: 2-3 Stars
  - **Yellow**: 1-2 Stars
  - **Gray**: Unrated or 0-1 Stars
""")

# User input for issue description
user_issue = st.text_area("Describe your issue:")
if st.button("Analyze Issue"):
    if user_issue:
        suggested_care_type = determine_care_type(user_issue)
        st.session_state["care_type"] = suggested_care_type
        st.write(f"Suggested care type based on your issue: {suggested_care_type}")
    else:
        st.error("Please describe your issue to analyze.")

location_query = st.text_input("Search by Location:")
use_current_location = st.button("Use Current Location", key="current_location_button")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)
radius = st.slider("Search Radius (meters):", min_value=500, max_value=200000, step=1000, value=20000)
care_type = st.session_state["care_type"]

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
    facilities = fetch_healthcare_data(latitude, longitude, radius, care_type)

    if facilities.empty:
        st.error("No facilities found. Check your API key, location, or radius.")
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
        st.session_state["facilities"] = pd.DataFrame()
    else:
        st.write(f"Found {len(facilities)} facilities.")
        st.session_state["facilities"] = facilities

        # Only regenerate the map when new data is fetched
        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities.iterrows():
            # Determine marker color based on rating
            marker_color = 'blue'  # Default marker color

            popup_content = (
                f"<b>{row['name']}</b><br>"
                f"Address: {row['address']}<br>"
                f"Category: {row['category']}<br>"
                f"<a href='https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={row['latitude']},{row['longitude']}' target='_blank'>Get Directions</a>"
            )

            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_content,
                icon=folium.Icon(color=marker_color)
            ).add_to(m)

        folium.Marker(
            location=[latitude, longitude],
            popup="Current Location",
            icon=folium.Icon(icon="info-sign", color="red")
        ).add_to(m)

        st.session_state["map"] = m

# Display the map only when it exists in session state
if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
