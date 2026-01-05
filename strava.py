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

# 1. Joueur A (Principal) - Charge depuis .env (VOTRE_...)
if 'client_id' not in st.session_state:
    st.session_state.client_id = os.getenv('VOTRE_CLIENT_ID', '')
if 'client_secret' not in st.session_state:
    st.session_state.client_secret = os.getenv('VOTRE_CLIENT_SECRET', '')
if 'refresh_token' not in st.session_state:
    st.session_state.refresh_token = os.getenv('VOTRE_REFRESH_TOKEN', '')
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = all([st.session_state.client_id, st.session_state.client_secret, st.session_state.refresh_token])

# 2. Joueur B (Adversaire) - Charge depuis .env (ADV_...)
if 'client_id_b' not in st.session_state:
    st.session_state.client_id_b = os.getenv('ADV_CLIENT_ID', '')
if 'client_secret_b' not in st.session_state:
    st.session_state.client_secret_b = os.getenv('ADV_CLIENT_SECRET', '')
if 'refresh_token_b' not in st.session_state:
    st.session_state.refresh_token_b = os.getenv('ADV_REFRESH_TOKEN', '')

# Détection automatique de connexion pour B (si les infos sont dans le .env)
if 'logged_in_b' not in st.session_state:
    st.session_state.logged_in_b = all([st.session_state.client_id_b, st.session_state.client_secret_b, st.session_state.refresh_token_b])

if 'name_b' not in st.session_state: 
    st.session_state.name_b = "Adversaire"

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

def get_athlete_profile(access_token):
    """Récupère le prénom de l'athlète pour l'affichage"""
    url = f'{BASE_URL}/athlete'
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('firstname', 'Adversaire')
    except:
        pass
    return "Adversaire"

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

def format_duration(seconds):
    if pd.isna(seconds): return "-"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes:02d}m {secs:02d}s"

# --- INTERFACES ---

def show_login_page():
    st.title("🔐 Connexion Strava Analytics")
    st.markdown("Pour analyser vos données, veuillez vous connecter.")
    
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
                    st.error("Échec de l'authentification.")
            else:
                st.warning("Veuillez remplir tous les champs.")

def show_dashboard():
    # --- SIDEBAR & CHARGEMENT DONNÉES JOUEUR A ---
    with st.sidebar:
        st.header("Paramètres")
        if st.button("🚪 Déconnexion"):
            st.session_state.logged_in = False
            st.session_state.client_id = ''
            st.session_state.client_secret = ''
            st.session_state.refresh_token = ''
            # On déconnecte aussi le joueur B
            st.session_state.logged_in_b = False
            st.session_state.client_id_b = ''
            st.rerun()

        if st.button("🔄 Actualiser les données"):
            st.cache_data.clear()
            st.rerun()
            
        token = get_access_token(st.session_state.client_id, st.session_state.client_secret, st.session_state.refresh_token)
        
        if not token:
            st.error("Token expiré.")
            st.session_state.logged_in = False
            st.rerun()
            
        activities_raw = get_activities(token)
        df = process_data(activities_raw)
        st.success(f"👤 Vous: {len(df)} activités")
        
        # --- CHARGEMENT DONNÉES JOUEUR B (Automatique via .env ou Session) ---
        df_b = pd.DataFrame()
        
        if st.session_state.logged_in_b:
            token_b = get_access_token(st.session_state.client_id_b, st.session_state.client_secret_b, st.session_state.refresh_token_b)
            if token_b:
                # Récupérer le nom si pas encore fait
                if st.session_state.name_b == "Adversaire":
                    st.session_state.name_b = get_athlete_profile(token_b)
                
                activities_b_raw = get_activities(token_b)
                df_b = process_data(activities_b_raw)
                st.info(f"🆚 {st.session_state.name_b}: {len(df_b)} activités")
            else:
                # Si le token automatique échoue, on déconnecte B pour afficher le formulaire
                st.error("Erreur connexion Adversaire (Token invalide)")
                st.session_state.logged_in_b = False

        # --- FILTRES COMMUNS ---
        if not df.empty:
            all_types = df['type'].unique().tolist()
            if not df_b.empty:
                 all_types = list(set(all_types + df_b['type'].unique().tolist()))
            
            defaults = [t for t in all_types if t in ['Course', 'Trail']]
            if not defaults: defaults = all_types
            
            selected_types = st.multiselect("Type d'activité", all_types, default=defaults)
            if not selected_types: selected_types = all_types
            
            min_date = df['date'].min().date()
            if not df_b.empty:
                min_date = min(min_date, df_b['date'].min().date())
                
            max_date = pd.Timestamp.now().date()
            
            start_date, end_date = st.date_input("Période", [min_date, max_date])
            
            # Filtres Joueur A
            mask = (df['type'].isin(selected_types)) & (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
            df_filtered = df[mask].copy()
            
            # Filtres Joueur B (Identiques)
            df_b_filtered = pd.DataFrame()
            if not df_b.empty:
                mask_b = (df_b['type'].isin(selected_types)) & (df_b['date'].dt.date >= start_date) & (df_b['date'].dt.date <= end_date)
                df_b_filtered = df_b[mask_b].copy()
        else:
            df_filtered = pd.DataFrame()
            df_b_filtered = pd.DataFrame()

    # --- MAIN CONTENT ---
    st.title("📊 Strava Analytics Pro")

    if df_filtered.empty:
        st.warning("Aucune activité trouvée pour le profil principal.")
    else:
        # KPI PRINCIPAUX
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Distance Totale", f"{df_filtered['distance_km'].sum():,.1f} km")
        kpi2.metric("Dénivelé +", f"{df_filtered['elevation_m'].sum():,.0f} m")
        kpi3.metric("Temps", f"{df_filtered['moving_time_sec'].sum()/3600:,.1f} h")
        kpi4.metric("BPM Moyen", f"{df_filtered['avg_heartrate'].mean():.0f} bpm" if not pd.isna(df_filtered['avg_heartrate'].mean()) else "N/A")

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Tendances", "❤️ Cardio", "🗺️ Carte", "📋 Données", "⚔️ Comparaison"])

        # --- TAB 1, 2, 3, 4 : INCHANGÉS ---
        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                monthly = df_filtered.groupby('month_year')['distance_km'].sum().reset_index()
                st.plotly_chart(px.bar(monthly, x='month_year', y='distance_km', title="Distance par Mois", color='distance_km'), width='stretch')
            with col2:
                df_sorted = df_filtered.sort_values('date')
                df_sorted['cum_dist'] = df_sorted['distance_km'].cumsum()
                st.plotly_chart(px.line(df_sorted, x='date', y='cum_dist', title="Cumul Annuel"), width='stretch')
            
            st.plotly_chart(px.histogram(df_filtered, x="distance_km", color="type", title="Répartition des distances", nbins=20, text_auto=True).update_layout(bargap=0.1), width='stretch')

            col_elev1, col_elev2 = st.columns(2)
            with col_elev1: st.plotly_chart(px.scatter(df_filtered, x="distance_km", y="elevation_m", color="type", size="moving_time_sec", title="Dénivelé vs Distance"), width='stretch')
            with col_elev2: 
                monthly_elev = df_filtered.groupby('month_year')['elevation_m'].sum().reset_index().sort_values('month_year')
                st.plotly_chart(px.bar(monthly_elev, x='month_year', y='elevation_m', title="Dénivelé par mois"), width='stretch')

            df_habit = df_filtered.copy()
            df_habit['hour'] = df_habit['date'].dt.hour
            df_habit['day_name'] = df_habit['date'].dt.day_name()
            days_fr = {'Monday': 'Lundi', 'Tuesday': 'Mardi', 'Wednesday': 'Mercredi', 'Thursday': 'Jeudi', 'Friday': 'Vendredi', 'Saturday': 'Samedi', 'Sunday': 'Dimanche'}
            habit_grp = df_habit.groupby(['day_name', 'hour']).agg({'id': 'count', 'distance_km': 'sum'}).reset_index()
            habit_grp['day_fr'] = habit_grp['day_name'].map(days_fr)
            fig_bub = px.scatter(habit_grp, x='day_fr', y='hour', size='id', color='distance_km', category_orders={'day_fr': list(days_fr.values())}, title="Habitudes (Taille=Freq, Couleur=Dist)")
            fig_bub.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_bub, width='stretch')

        with tab2:
            df_hr = df_filtered.dropna(subset=['avg_heartrate'])
            if not df_hr.empty:
                c1, c2 = st.columns(2)
                with c1: st.plotly_chart(px.box(df_hr, x='type', y='avg_heartrate', color='type', title="Distribution FC", points="all"), width='stretch')
                with c2: st.plotly_chart(px.scatter(df_hr, x='avg_speed_kmh', y='avg_heartrate', color='type', trendline="ols", title="Efficacité"), width='stretch')
            else: st.info("Pas de données cardiaques.")

        with tab3:
            valid_map = df_filtered[df_filtered['map_polyline'].notna() & (df_filtered['map_polyline'] != "")]
            if not valid_map.empty:
                try:
                    m = folium.Map(location=decode(valid_map.iloc[0]['map_polyline'])[0], zoom_start=10, tiles='CartoDB dark_matter')
                    for poly in valid_map['map_polyline']:
                        try: folium.PolyLine(decode(poly), color='#ff4b4b', weight=2, opacity=0.5).add_to(m)
                        except: pass
                    folium_static(m, width=1000)
                except: st.error("Erreur carte.")
            else: st.info("Pas de GPS.")

        with tab4:
            st.dataframe(df_filtered[['date', 'name', 'type', 'distance_km', 'elevation_m', 'moving_time_sec', 'avg_heartrate']].sort_values('date', ascending=False))

        # --- TAB 5 : COMPARAISON / LOGIN B ---
        with tab5:
            st.header("⚔️ Mode Duel / Comparaison")
            
            if not st.session_state.logged_in_b:
                st.info("Aucun adversaire connecté automatiquement.")
                st.write("Vous pouvez en ajouter un manuellement ici :")
                
                with st.form("login_b_form"):
                    c_id_b = st.text_input("Client ID (Adversaire)", value=st.session_state.client_id_b)
                    c_secret_b = st.text_input("Client Secret (Adversaire)", type="password", value=st.session_state.client_secret_b)
                    r_token_b = st.text_input("Refresh Token (Adversaire)", type="password", value=st.session_state.refresh_token_b)
                    
                    if st.form_submit_button("🔥 Ajouter l'adversaire"):
                        if c_id_b and c_secret_b and r_token_b:
                            token_test = get_access_token(c_id_b, c_secret_b, r_token_b)
                            if token_test:
                                st.session_state.client_id_b = c_id_b
                                st.session_state.client_secret_b = c_secret_b
                                st.session_state.refresh_token_b = r_token_b
                                st.session_state.logged_in_b = True
                                st.session_state.name_b = get_athlete_profile(token_test)
                                st.rerun()
                            else: st.error("Identifiants incorrects.")
                        else: st.warning("Remplissez tout.")
            else:
                if df_b_filtered.empty:
                    st.warning(f"L'adversaire ({st.session_state.name_b}) n'a pas d'activités pour ces filtres.")
                else:
                    st.success(f"Comparaison : Vous vs {st.session_state.name_b}")
                    if st.button("❌ Retirer l'adversaire"):
                        st.session_state.logged_in_b = False
                        st.session_state.client_id_b = ''
                        st.rerun()

                    # 1. SCOREBOARD
                    st.markdown("#### 🏆 Scoreboard")
                    col_d1, col_d2, col_d3 = st.columns(3)
                    dist_a, dist_b = df_filtered['distance_km'].sum(), df_b_filtered['distance_km'].sum()
                    elev_a, elev_b = df_filtered['elevation_m'].sum(), df_b_filtered['elevation_m'].sum()
                    time_a, time_b = df_filtered['moving_time_sec'].sum() / 3600, df_b_filtered['moving_time_sec'].sum() / 3600
                    
                    col_d1.metric("Distance", f"{dist_a:.1f} km", delta=f"{dist_a - dist_b:.1f} km (vs {dist_b:.1f})")
                    col_d2.metric("Dénivelé", f"{elev_a:.0f} m", delta=f"{elev_a - elev_b:.0f} m (vs {elev_b:.0f})")
                    col_d3.metric("Heures", f"{time_a:.1f} h", delta=f"{time_a - time_b:.1f} h (vs {time_b:.1f})")

                    st.markdown("---")

                    # PRÉPARATION DATAS COMBINÉES
                    df_a_comp = df_filtered.copy()
                    df_a_comp['Joueur'] = "Vous"
                    df_b_comp = df_b_filtered.copy()
                    df_b_comp['Joueur'] = st.session_state.name_b
                    df_combined = pd.concat([df_a_comp, df_b_comp])
                    
                    colors_map = {"Vous": "#00CC96", st.session_state.name_b: "#EF553B"}

                    # 2. COURSES CUMULÉES
                    c_race1, c_race2 = st.columns(2)
                    
                    with c_race1:
                        st.markdown("#### 🏁 Course de Distance")
                        df_combined = df_combined.sort_values('date')
                        df_combined['cum_dist'] = df_combined.groupby('Joueur')['distance_km'].cumsum()
                        fig_race_dist = px.line(df_combined, x='date', y='cum_dist', color='Joueur', 
                                           title="Progression Distance Cumulée", color_discrete_map=colors_map)
                        st.plotly_chart(fig_race_dist, width='stretch')
                        
                    with c_race2:
                        st.markdown("#### 🧗 Course au Sommet")
                        df_combined['cum_elev'] = df_combined.groupby('Joueur')['elevation_m'].cumsum()
                        fig_race_elev = px.line(df_combined, x='date', y='cum_elev', color='Joueur', 
                                           title="Progression Dénivelé Cumulé", color_discrete_map=colors_map)
                        st.plotly_chart(fig_race_elev, width='stretch')

                    st.markdown("---")
                    
                    # 3. DUEL CARDIO
                    st.markdown("#### ❤️ Duel Cardio & Physiologie")
                    df_combined_hr = df_combined.dropna(subset=['avg_heartrate'])
                    
                    if not df_combined_hr.empty:
                        c_hr1, c_hr2 = st.columns(2)
                        with c_hr1:
                            fig_hr_box = px.box(df_combined_hr, x='Joueur', y='avg_heartrate', color='Joueur',
                                                title="Distribution Fréquence Cardiaque", color_discrete_map=colors_map, points=False)
                            st.plotly_chart(fig_hr_box, width='stretch')
                        with c_hr2:
                            fig_hr_eff = px.scatter(df_combined_hr, x='avg_speed_kmh', y='avg_heartrate', color='Joueur',
                                                    trendline="ols", title="Efficacité (Vitesse vs FC)",
                                                    color_discrete_map=colors_map, opacity=0.6)
                            st.plotly_chart(fig_hr_eff, width='stretch')
                    else: st.info("Pas assez de données cardiaques pour le duel.")
                        
                    st.markdown("---")

                    # 4. DUEL VITESSE
                    st.markdown("#### 🐆 Duel de Vitesse (Running & Trail)")
                    df_combined_run = df_combined[df_combined['type'].isin(['Course', 'Trail'])].copy()
                    
                    if not df_combined_run.empty:
                        c_pace1, c_pace2 = st.columns(2)
                        with c_pace1:
                            fig_pace_box = px.box(df_combined_run, x='Joueur', y='pace_decimal', color='Joueur',
                                                  title="Distribution des Allures (min/km)", color_discrete_map=colors_map)
                            fig_pace_box.update_yaxes(autorange="reversed") 
                            st.plotly_chart(fig_pace_box, width='stretch')
                        with c_pace2:
                             fig_profile = px.scatter(df_combined, x='distance_km', y='elevation_m', color='Joueur',
                                                      title="Profil des sorties (Qui fait le plus dur ?)", 
                                                      color_discrete_map=colors_map, opacity=0.7)
                             st.plotly_chart(fig_profile, width='stretch')

# --- POINT D'ENTRÉE PRINCIPAL ---

if st.session_state.logged_in:
    show_dashboard()
else:
    show_login_page()