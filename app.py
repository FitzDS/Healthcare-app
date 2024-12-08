import streamlit as st
import pandas as pd
import requests
import geocoder
from streamlit_folium import st_folium
import folium
from folium.features import CustomIcon

# Load API keys (replace with secure secrets management later)
GEOAPIFY_API_KEY = "f01884465c8743a9a1d805d1c778e7af"
GOOGLE_API_KEY = "AIzaSyBIghdeoXzo-XYY1mJkeIezTDPhr6WAHgM"

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

CATEGORY_ICONS = {
    "healthcare": "https://upload.wikimedia.org/wikipedia/commons/e/e7/Healthcare_icon.png",
    "healthcare.pharmacy": "https://upload.wikimedia.org/wikipedia/commons/4/4e/Pills_icon.png",
    "healthcare.hospital": "https://upload.wikimedia.org/wikipedia/commons/1/12/Hospital_icon.png",
    "healthcare.clinic": "https://upload.wikimedia.org/wikipedia/commons/4/45/Medical_Clinic_icon.png",
    "healthcare.dentist": "https://upload.wikimedia.org/wikipedia/commons/7/7f/Dental_Icon.png",
    "healthcare.rehabilitation": "https://upload.wikimedia.org/wikipedia/commons/2/21/Rehabilitation_icon.png",
    "healthcare.emergency": "https://upload.wikimedia.org/wikipedia/commons/4/45/Emergency_icon.png",
    "healthcare.veterinary": "https://upload.wikimedia.org/wikipedia/commons/5/5e/Veterinary_icon.png",
}




# Initialize session state for map and facilities
if "map" not in st.session_state:
    st.session_state["map"] = None
if "facilities" not in st.session_state:
    st.session_state["facilities"] = pd.DataFrame()

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

def fetch_ratings_for_existing_places(facilities_df):
    updated_facilities = []

    for _, facility in facilities_df.iterrows():
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            'input': facility['name'],
            'inputtype': 'textquery',
            'fields': 'rating,user_ratings_total',
            'locationbias': f"point:{facility['latitude']},{facility['longitude']}",
            'key': GOOGLE_API_KEY
        }

        response = requests.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            if data.get('candidates'):
                candidate = data['candidates'][0]
                facility['rating'] = candidate.get('rating', 'N/A')
                facility['user_ratings_total'] = candidate.get('user_ratings_total', 0)
            else:
                facility['rating'] = 'N/A'
                facility['user_ratings_total'] = 0
        else:
            st.error(f"Error fetching ratings for {facility['name']}: {response.status_code}")
            facility['rating'] = 'N/A'
            facility['user_ratings_total'] = 0

        updated_facilities.append(facility)

    return pd.DataFrame(updated_facilities)

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

location_query = st.text_input("Search by Location:")
use_current_location = st.button("Use Current Location", key="current_location_button")
latitude = st.number_input("Latitude", value=38.5449)
longitude = st.number_input("Longitude", value=-121.7405)
radius = st.slider("Search Radius (meters):", min_value=500, max_value=200000, step=1000, value=20000)
care_type = st.selectbox("Type of Care:", options=list(CARE_TYPES.keys()))

if location_query:
    lat, lon = get_lat_lon_from_query(location_query)
    if lat and lon:
        latitude = lat
        longitude = lon
        st.write(f"Using location: {location_query} (Latitude: {latitude}, Longitude: {longitude})")

if use_current_location:
    current_location = get_current_location()
    latitude = current_location[0]
    longitude = current_location[1]
    st.write(f"Using current location: Latitude {latitude}, Longitude {longitude}")

if st.button("Search", key="search_button"):
    st.write("Fetching data...")
    facilities = fetch_healthcare_data(latitude, longitude, radius, CARE_TYPES[care_type])

    if facilities.empty:
        st.error("No facilities found. Check your API key, location, or radius.")
        st.session_state["map"] = folium.Map(location=[latitude, longitude], zoom_start=12)
        st.session_state["facilities"] = pd.DataFrame()
    else:
        st.write(f"Found {len(facilities)} facilities.")
        facilities_with_ratings = fetch_ratings_for_existing_places(facilities)
        st.session_state["facilities"] = facilities_with_ratings

        m = folium.Map(location=[latitude, longitude], zoom_start=12)
        folium.Circle(
            location=[latitude, longitude],
            radius=radius,
            color="blue",
            fill=True,
            fill_opacity=0.4
        ).add_to(m)

        for _, row in facilities_with_ratings.iterrows():
            # Fetch facility information
            category = row.get('category', 'healthcare')  # Default to 'healthcare'
            icon_url = CATEGORY_ICONS.get(category, CATEGORY_ICONS["healthcare"])  # Fallback to 'healthcare' icon if category not found
            custom_icon = CustomIcon(icon_url, icon_size=(30, 30))  # Adjust size as needed
        
            # Prepare popup content
            popup_content = (
                f"<b>{row['name']}</b><br>"
                f"Address: {row['address']}<br>"
                f"Rating: {row['rating']} ({row['user_ratings_total']} reviews)<br>"
                f"<a href='https://www.google.com/maps/dir/?api=1&origin={latitude},{longitude}&destination={row['latitude']},{row['longitude']}' target='_blank'>Get Directions</a>"
            )
        
            # Add marker with the custom icon
            folium.Marker(
                location=[row["latitude"], row["longitude"]],
                popup=popup_content,
                icon=custom_icon
            ).add_to(m)




    st.session_state["map"] = m

if "map" in st.session_state and st.session_state["map"] is not None:
    st_folium(st.session_state["map"], width=700, height=500)
else:
    default_map = folium.Map(location=[latitude, longitude], zoom_start=12)
    folium.Marker(
        location=[latitude, longitude],
        popup="Current Location",
        icon=folium.Icon(color="red")
    ).add_to(default_map)
    folium.Circle(
        location=[latitude, longitude],
        radius=radius,
        color="blue",
        fill=True,
        fill_opacity=0.4
    ).add_to(default_map)
    st_folium(default_map, width=700, height=500)

# Add legend for marker colors and icons
st.markdown("""### Legend
- **Red Marker**: Current Location
- **Icons**:
  - 🏥 Hospital
  - 💊 Pharmacy
  - 🦷 Dentist
  - 🐾 Veterinary
  - 🩺 Clinic
  - 🚑 Emergency
  - 🚶 Rehabilitation
- **Rating Colors**:
  - **Green**: 4-5 Stars
  - **Blue**: 3-4 Stars
  - **Orange**: 2-3 Stars
  - **Yellow**: 1-2 Stars
  - **Gray**: Unrated or 0-1 Stars
""")

# Show data in a table if facilities exist
if "facilities" in st.session_state and not st.session_state["facilities"].empty:
    st.dataframe(st.session_state["facilities"])
