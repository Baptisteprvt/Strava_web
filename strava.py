import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import folium
from streamlit_folium import folium_static
from polyline import decode
import numpy as np
import os
from dotenv import load_dotenv

# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Strava Analytics Pro", layout="wide", page_icon="🏃")
load_dotenv()

# --- GESTION DE L'ÉTAT (SESSION STATE) ---
if 'client_id' not in st.session_state:
    st.session_state.client_id = os.getenv('VOTRE_CLIENT_ID', '')
if 'client_secret' not in st.session_state:
    st.session_state.client_secret = os.getenv('VOTRE_CLIENT_SECRET', '')
if 'refresh_token' not in st.session_state:
    st.session_state.refresh_token = os.getenv('VOTRE_REFRESH_TOKEN', '')
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = all([st.session_state.client_id, st.session_state.client_secret, st.session_state.refresh_token])

BASE_URL = 'https://www.strava.com/api/v3'

# --- FONCTIONS (CACHE & API) ---

@st.cache_data(ttl=3600) 
def get_access_token(client_id, client_secret, refresh_token):
    auth_url = 'https://www.strava.com/oauth/token'
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }
    try:
        response = requests.post(auth_url, data=payload)
        response.raise_for_status()
        return response.json().get('access_token')
    except Exception as e:
        return None

@st.cache_data(ttl=3600, show_spinner="Récupération des activités Strava...") 
def get_activities(access_token):
    url = f'{BASE_URL}/athlete/activities'
    headers = {'Authorization': f'Bearer {access_token}'}
    all_activities = []
    page = 1
    
    while True:
        params = {'per_page': 200, 'page': page}
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            break
        activities = response.json()
        if not activities:
            break
        all_activities.extend(activities)
        page += 1
    return all_activities

def process_data(activities):
    if not activities:
        return pd.DataFrame()
    data = []
    for act in activities:
        # --- LOGIQUE DE SÉPARATION COURSE / TRAIL ---
        raw_type = act.get("sport_type", act.get("type"))
        
        if raw_type == "TrailRun":
            final_type = "Trail"
        elif raw_type == "Run":
            final_type = "Course"
        elif raw_type in ["Ride", "VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"]:
            final_type = "Vélo"
        elif raw_type == "Hike":
            final_type = "Randonnée"
        else:
            final_type = raw_type 

        item = {
            "id": act["id"],
            "name": act["name"],
            "date": act["start_date_local"],
            "type": final_type,
            "distance_km": act["distance"] / 1000,
            "duration_sec": act["elapsed_time"],
            "moving_time_sec": act["moving_time"],
            "elevation_m": act.get("total_elevation_gain", 0),
            "avg_speed_kmh": (act["average_speed"] * 3.6),
            "max_speed_kmh": (act["max_speed"] * 3.6),
            "avg_heartrate": act.get("average_heartrate", np.nan),
            "max_heartrate": act.get("max_heartrate", np.nan),
            "suffer_score": act.get("suffer_score", 0),
            "map_polyline": act.get("map", {}).get("summary_polyline", None)
        }
        data.append(item)
        
    df = pd.DataFrame(data)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month_year'] = df['date'].dt.to_period('M').astype(str)
    
    # Calcul du Pace (min/km) pour Course et Trail
    df['pace_decimal'] = (1 / df['avg_speed_kmh'].replace(0, np.nan)) * 60
    
    return df

# --- INTERFACES ---

def show_login_page():
    st.title("🔐 Connexion Strava Analytics")
    st.markdown("""
    Bienvenue sur Strava Analytics Pro. Pour analyser vos données, vous devez fournir vos identifiants API Strava.
    
    **Comment obtenir ces informations ?**
    1. Allez sur [Strava API Settings](https://www.strava.com/settings/api).
    2. Créez une application (mettez "localhost" comme domaine si demandé).
    3. Copiez le **Client ID**, le **Client Secret** et votre **Refresh Token**.
    """)
    
    with st.form("login_form"):
        c_id = st.text_input("Client ID", value=st.session_state.client_id)
        c_secret = st.text_input("Client Secret", type="password", value=st.session_state.client_secret)
        r_token = st.text_input("Refresh Token", type="password", value=st.session_state.refresh_token)
        
        submitted = st.form_submit_button("🚀 Analyser mes données")
        
        if submitted:
            if c_id and c_secret and r_token:
                token = get_access_token(c_id, c_secret, r_token)
                if token:
                    st.session_state.client_id = c_id
                    st.session_state.client_secret = c_secret
                    st.session_state.refresh_token = r_token
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("Échec de l'authentification. Vérifiez vos tokens.")
            else:
                st.warning("Veuillez remplir tous les champs.")

def show_dashboard():
    # --- SIDEBAR ---
    with st.sidebar:
        st.header("Paramètres")
        if st.button("🚪 Déconnexion"):
            st.session_state.logged_in = False
            st.session_state.client_id = ''
            st.session_state.client_secret = ''
            st.session_state.refresh_token = ''
            st.rerun()

        if st.button("🔄 Actualiser les données"):
            st.cache_data.clear()
            st.rerun()
            
        token = get_access_token(st.session_state.client_id, st.session_state.client_secret, st.session_state.refresh_token)
        
        if not token:
            st.error("Token expiré ou invalide.")
            st.session_state.logged_in = False
            st.rerun()
            
        activities_raw = get_activities(token)
        df = process_data(activities_raw)
        st.success(f"{len(df)} activités chargées.")
        
        # Filtres
        if not df.empty:
            all_types = df['type'].unique().tolist()
            
            defaults = [t for t in all_types if t in ['Course', 'Trail']]
            if not defaults: 
                defaults = all_types
                
            selected_types = st.multiselect("Type d'activité", all_types, default=defaults)
            if not selected_types: selected_types = all_types
            
            min_date = df['date'].min().date()
            max_date = df['date'].max().date()
            start_date, end_date = st.date_input("Période", [min_date, max_date])
            
            mask = (df['type'].isin(selected_types)) & (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
            df_filtered = df[mask].copy()
        else:
            df_filtered = pd.DataFrame()

    # --- MAIN CONTENT ---
    st.title("📊 Strava Analytics Pro")

    if df_filtered.empty:
        st.warning("Aucune activité trouvée.")
    else:
        # KPI
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Distance Totale", f"{df_filtered['distance_km'].sum():,.1f} km")
        kpi2.metric("Dénivelé +", f"{df_filtered['elevation_m'].sum():,.0f} m")
        kpi3.metric("Temps", f"{df_filtered['moving_time_sec'].sum()/3600:,.1f} h")
        kpi4.metric("BPM Moyen", f"{df_filtered['avg_heartrate'].mean():.0f} bpm" if not pd.isna(df_filtered['avg_heartrate'].mean()) else "N/A")

        # TABS - On regroupe tout dans 4 onglets principaux
        tab1, tab2, tab3, tab4 = st.tabs(["📈 Tendances & Analyse", "❤️ Cardio", "🗺️ Carte", "📋 Données"])

        with tab1:
            st.markdown("### 🏃‍♂️ Volume et Progression")
            col1, col2 = st.columns(2)
            with col1:
                monthly = df_filtered.groupby('month_year')['distance_km'].sum().reset_index()
                st.plotly_chart(px.bar(monthly, x='month_year', y='distance_km', title="Distance par Mois", color='distance_km'), use_container_width=True)
            with col2:
                df_sorted = df_filtered.sort_values('date')
                df_sorted['cum_dist'] = df_sorted['distance_km'].cumsum()
                st.plotly_chart(px.line(df_sorted, x='date', y='cum_dist', title="Cumul Annuel"), use_container_width=True)
            
            # Histogramme Distances
            fig_hist = px.histogram(df_filtered, x="distance_km", color="type", title="Répartition des distances (Nombre de sorties)", nbins=20, text_auto=True)
            fig_hist.update_layout(bargap=0.1)
            st.plotly_chart(fig_hist, use_container_width=True)

            st.markdown("---")
            st.markdown("### ⛰️ Analyse du Dénivelé")
            
            col_elev1, col_elev2 = st.columns(2)
            
            with col_elev1:
                # 1. Relation Distance vs Dénivelé
                fig_elev_dist = px.scatter(
                    df_filtered, 
                    x="distance_km", 
                    y="elevation_m", 
                    color="type",
                    size="moving_time_sec", 
                    hover_data=["date", "name"],
                    title="Dénivelé vs Distance",
                    labels={"distance_km": "Distance (km)", "elevation_m": "Dénivelé (m)"}
                )
                st.plotly_chart(fig_elev_dist, use_container_width=True)

            with col_elev2:
                 # 2. Cumul du dénivelé par mois
                monthly_elev = df_filtered.groupby('month_year')['elevation_m'].sum().reset_index()
                monthly_elev = monthly_elev.sort_values('month_year')
                
                fig_monthly_elev = px.bar(
                    monthly_elev, 
                    x='month_year', 
                    y='elevation_m', 
                    title="Dénivelé total par mois",
                    labels={'month_year': 'Mois', 'elevation_m': 'Dénivelé (m)'},
                    text_auto=True,
                    color='elevation_m'
                )
                st.plotly_chart(fig_monthly_elev, use_container_width=True)

            st.markdown("---")
            st.markdown("### 🗓️ Habitudes & Comparaisons")

            # --- GRAPHIQUE HABITUDES MODIFIÉ ---
            df_habit = df_filtered.copy()
            df_habit['hour'] = df_habit['date'].dt.hour
            df_habit['day_name'] = df_habit['date'].dt.day_name()
            days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            days_fr = {'Monday': 'Lundi', 'Tuesday': 'Mardi', 'Wednesday': 'Mercredi', 'Thursday': 'Jeudi', 'Friday': 'Vendredi', 'Saturday': 'Samedi', 'Sunday': 'Dimanche'}
            
            # On groupe en comptant les ID (fréquence) et en sommant la distance (pour info)
            habit_grp = df_habit.groupby(['day_name', 'hour']).agg({
                'id': 'count',          # Compte le nombre de sorties
                'distance_km': 'sum'    # Somme les km
            }).reset_index()
            
            habit_grp.rename(columns={'id': 'frequency'}, inplace=True)
            habit_grp['day_fr'] = habit_grp['day_name'].map(days_fr)
            
            # Bubble chart: Taille=Fréquence, Couleur=Distance
            fig_bubble = px.scatter(habit_grp, 
                                    x='day_fr', 
                                    y='hour', 
                                    size='frequency',     # TAILLE = FRÉQUENCE
                                    color='distance_km',  # COULEUR = VOLUME KILOMETRIQUE
                                    color_continuous_scale='Turbo',
                                    category_orders={'day_fr': [days_fr[d] for d in days_order]}, 
                                    title="Habitudes : Fréquence (Taille) vs Volume (Couleur)",
                                    labels={'frequency': 'Nombre de sorties', 'hour': 'Heure', 'day_fr': 'Jour', 'distance_km': 'Distance Cumulée'},
                                    hover_data={'distance_km': True, 'day_fr': False, 'frequency': True}) 
            
            fig_bubble.update_yaxes(autorange="reversed", dtick=1)
            st.plotly_chart(fig_bubble, use_container_width=True)
            
            # Comparaison Annuelle
            current_year = df['date'].dt.year.max()
            prev_year = current_year - 1
            df_yoy = df[df['year'].isin([current_year, prev_year])].copy()
            if not df_yoy.empty:
                df_yoy['day_of_year'] = df_yoy['date'].dt.dayofyear
                df_cumul = df_yoy.groupby(['year', 'day_of_year'])['distance_km'].sum().groupby(level=0).cumsum().reset_index()
                st.plotly_chart(px.line(df_cumul, x='day_of_year', y='distance_km', color='year', title=f"Duel Annuel : {prev_year} vs {current_year}"), use_container_width=True)


        with tab2:
            st.subheader("Physiologie")
            # On ne garde que les activités avec de la fréquence cardiaque
            df_hr = df_filtered.dropna(subset=['avg_heartrate'])
            
            if not df_hr.empty:
                c1, c2 = st.columns(2)
                
                with c1:
                    # 1. Box Plot (Distribution)
                    fig_box = px.box(df_hr, x='type', y='avg_heartrate', color='type', 
                                     title="Distribution FC (avec points individuels)",
                                     hover_data=['name', 'date', 'distance_km'])
                    st.plotly_chart(fig_box, use_container_width=True)
                
                with c2:
                    # 2. Scatter Plot (Efficacité)
                    fig_eff = px.scatter(df_hr, x='avg_speed_kmh', y='avg_heartrate', 
                                         color='type', trendline="ols", 
                                         title="Efficacité (Vitesse vs FC)",
                                         hover_data=['name', 'date', 'distance_km'])
                    st.plotly_chart(fig_eff, use_container_width=True)
                
                # 3. Graphique Allure (Running/Trail uniquement)
                runs = df_filtered[df_filtered['type'].isin(['Course', 'Trail'])].copy()
                if not runs.empty:
                    st.markdown("---")
                    st.subheader("Allure Running & Trail")
                    
                    def decimal_to_pace(val):
                        if pd.isna(val) or val == float('inf'): return "N/A"
                        mins = int(val); secs = int((val - mins) * 60)
                        return f"{mins}:{secs:02d}"
                    
                    runs['pace_str'] = runs['pace_decimal'].apply(decimal_to_pace)
                    
                    fig_pace = px.scatter(runs, x='date', y='pace_decimal', 
                                          color='avg_heartrate', 
                                          title="Évolution Allure (min/km)",
                                          hover_data={
                                              'date': True, 
                                              'pace_decimal': False,
                                              'pace_str': True,
                                              'name': True,
                                              'distance_km': True,
                                              'type': True
                                          })
                    
                    fig_pace.update_yaxes(autorange="reversed") # Plus bas = Plus vite = Meilleur
                    st.plotly_chart(fig_pace, use_container_width=True)
            else:
                st.info("Pas de données cardiaques disponibles pour cette sélection.")

        with tab3:
            st.subheader("Carte Thermique")
            valid_map = df_filtered[df_filtered['map_polyline'].notna() & (df_filtered['map_polyline'] != "")]
            if not valid_map.empty:
                first_poly = valid_map.iloc[0]['map_polyline']
                try:
                    m = folium.Map(location=decode(first_poly)[0], zoom_start=10, tiles='CartoDB dark_matter')
                    for poly in valid_map['map_polyline']:
                        try:
                            folium.PolyLine(decode(poly), color='#ff4b4b', weight=2, opacity=0.5).add_to(m)
                        except: pass
                    folium_static(m, width=1000)
                except: st.error("Erreur carte.")
            else:
                st.info("Pas de GPS.")

        with tab4:
            st.dataframe(df_filtered[['date', 'name', 'type', 'distance_km', 'elevation_m', 'moving_time_sec', 'avg_heartrate']].sort_values('date', ascending=False))

# --- POINT D'ENTRÉE PRINCIPAL ---

if st.session_state.logged_in:
    show_dashboard()
else:
    show_login_page()