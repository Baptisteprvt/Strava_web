import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import folium
from streamlit_folium import folium_static
from polyline import decode
import numpy as np
import os
from dotenv import load_dotenv
import plotly.graph_objects as go

# Configuration de la page (Doit être la première commande Streamlit)
st.set_page_config(page_title="Strava Analytics Pro", layout="wide", page_icon="🏃")

# --- CHARGEMENT DES VARIABLES D'ENVIRONNEMENT ---
load_dotenv() # Charge les variables du fichier .env

# Récupération des clés
CLIENT_ID = os.getenv('VOTRE_CLIENT_ID')
CLIENT_SECRET = os.getenv('VOTRE_CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('VOTRE_REFRESH_TOKEN')

# Vérification que les clés sont bien chargées
if not CLIENT_ID or not CLIENT_SECRET or not REFRESH_TOKEN:
    st.error("⚠️ Erreur de configuration : Les clés API Strava sont introuvables.")
    st.warning("Vérifiez que vous avez bien un fichier `.env` contenant VOTRE_CLIENT_ID, VOTRE_CLIENT_SECRET et VOTRE_REFRESH_TOKEN.")
    st.stop() # Arrête l'exécution du script ici si les clés manquent

BASE_URL = 'https://www.strava.com/api/v3'

# --- FONCTIONS D'AUTHENTIFICATION & DONNÉES ---

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
        st.error(f"Erreur d'authentification Strava: {e}")
        return None

@st.cache_data(ttl=3600, show_spinner="Récupération des activités Strava...") 
def get_activities(access_token):
    url = f'{BASE_URL}/athlete/activities'
    headers = {'Authorization': f'Bearer {access_token}'}
    all_activities = []
    page = 1
    
    while True:
        # On limite à 200 par page pour optimiser
        params = {'per_page': 200, 'page': page}
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code != 200:
            st.error(f"Erreur API lors de la récupération des activités: {response.status_code}")
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
    
    # Extraction des données brutes
    data = []
    for act in activities:
        # On prépare l'objet
        item = {
            "id": act["id"],
            "name": act["name"],
            "date": act["start_date_local"],
            "type": act["type"],
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
    
    # Conversions et enrichissement
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month_year'] = df['date'].dt.to_period('M').astype(str)
    
    # Calcul du Pace (min/km) pour la course à pied
    # Formule: (1 / vitesse_kmh) * 60
    # On remplace 0 par NaN pour éviter la division par zéro
    df['pace_decimal'] = (1 / df['avg_speed_kmh'].replace(0, np.nan)) * 60
    
    return df

# --- INTERFACE ---

st.title("📊 Strava Analytics Pro")

# Barre latérale pour les contrôles
with st.sidebar:
    st.header("Paramètres")
    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        
    # Authentification avec les variables chargées depuis .env
    token = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
    
    if token:
        activities_raw = get_activities(token)
        df = process_data(activities_raw)
        
        st.success(f"{len(df)} activités chargées.")
        
        # Filtres Dynamiques
        st.subheader("Filtres")
        
        if not df.empty:
            # Filtre Type d'activité
            all_types = df['type'].unique().tolist()
            # Par défaut, on sélectionne Run et Ride s'ils existent
            defaults = [t for t in all_types if t in ['Run', 'Ride']]
            if not defaults: defaults = all_types
            
            selected_types = st.multiselect("Type d'activité", all_types, default=defaults)
            if not selected_types:
                selected_types = all_types
                
            # Filtre Date
            min_date = df['date'].min().date()
            max_date = df['date'].max().date()
            start_date, end_date = st.date_input("Période", [min_date, max_date])

            # Application des filtres
            mask = (df['type'].isin(selected_types)) & (df['date'].dt.date >= start_date) & (df['date'].dt.date <= end_date)
            df_filtered = df[mask].copy()
        else:
            df_filtered = pd.DataFrame()
    else:
        st.stop()

# --- DASHBOARD PRINCIPAL ---

if df_filtered.empty:
    st.warning("Aucune activité trouvée (ou problème de récupération des données).")
else:
    # KPI Row
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    total_km = df_filtered['distance_km'].sum()
    total_elevation = df_filtered['elevation_m'].sum()
    total_hours = df_filtered['moving_time_sec'].sum() / 3600
    avg_hr = df_filtered['avg_heartrate'].mean()
    
    kpi1.metric("Distance Totale", f"{total_km:,.1f} km")
    kpi2.metric("Dénivelé +", f"{total_elevation:,.0f} m")
    kpi3.metric("Temps en mouvement", f"{total_hours:,.1f} h")
    kpi4.metric("BPM Moyen Global", f"{avg_hr:.0f} bpm" if not pd.isna(avg_hr) else "N/A", delta_color="off")

    # Onglets pour structurer l'analyse
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Tendances", "❤️ Cardio & Performance", "🗺️ Cartographie", "📋 Données", "🏆 Habits"])
    
    with tab1:
        st.subheader("Volume d'entraînement")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # Distance par mois
            monthly_dist = df_filtered.groupby('month_year')['distance_km'].sum().reset_index()
            fig_bar = px.bar(monthly_dist, x='month_year', y='distance_km', 
                             title="Distance par Mois", color='distance_km', color_continuous_scale='Viridis')
            st.plotly_chart(fig_bar, width='stretch')
            
        with col2:
            # Distance cumulée
            df_sorted = df_filtered.sort_values('date')
            df_sorted['cum_dist'] = df_sorted['distance_km'].cumsum()
            fig_cum = px.line(df_sorted, x='date', y='cum_dist', title="Distance Cumulée (Progression)", markers=False)
            fig_cum.update_layout(hovermode="x unified")
            st.plotly_chart(fig_cum, width='stretch')

        # Relation Distance vs Dénivelé
        fig_scatter = px.scatter(df_filtered, x='distance_km', y='elevation_m', 
                                 color='type', size='moving_time_sec', 
                                 title="Difficulté : Distance vs Dénivelé",
                                 hover_data=['name', 'date'])
        st.plotly_chart(fig_scatter, width='stretch')

        st.markdown("---")
        st.subheader("Répartition des Distances")
        
        # Création de l'histogramme
        # nbins=20 permet à Plotly de calculer automatiquement environ 20 tranches adaptées
        fig_hist = px.histogram(df_filtered, x="distance_km", 
                                color="type", 
                                title="Nombre de sorties par tranche de distance",
                                labels={'distance_km': 'Distance (km)', 'count': 'Nombre de sorties'},
                                text_auto=True, # Affiche le nombre exact sur les barres
                                nbins=20)
        
        # Amélioration visuelle : espace entre les barres
        fig_hist.update_layout(bargap=0.1, yaxis_title="Nombre d'activités")
        st.plotly_chart(fig_hist, width='stretch')
        
    with tab2:
        st.subheader("Analyse Physiologique")
        
        # Vérifier si on a des données cardiaques
        df_hr = df_filtered.dropna(subset=['avg_heartrate'])
        
        if not df_hr.empty:
            col_hr1, col_hr2 = st.columns(2)
            
            with col_hr1:
                # Distribution BPM
                fig_box = px.box(df_hr, x='type', y='avg_heartrate', color='type', 
                                 title="Distribution de la Fréquence Cardiaque Moyenne")
                st.plotly_chart(fig_box, width='stretch')
                
            with col_hr2:
                # Relation Vitesse vs BPM (Efficacité)
                fig_eff = px.scatter(df_hr, x='avg_speed_kmh', y='avg_heartrate', color='type', trendline="ols",
                                     title="Efficacité Cardiaque (Vitesse vs BPM)",
                                     hover_data=['name'])
                st.plotly_chart(fig_eff, width='stretch')
            
            st.info("💡 **Analyse :** Plus vous êtes en bas à droite du graphique 'Efficacité', plus vous êtes performant (Vitesse élevée pour un rythme cardiaque bas).")
            
            # Focus Course à Pied : Allure
            runs = df_filtered[df_filtered['type'] == 'Run'].copy()
            if not runs.empty:
                st.markdown("---")
                st.subheader("Focus Running : Allure (min/km)")
                
                # Conversion du pace decimal (ex: 5.5 min) en format texte (5:30) pour l'affichage
                def decimal_to_pace(val):
                    if pd.isna(val) or val == float('inf'): return "N/A"
                    mins = int(val)
                    secs = int((val - mins) * 60)
                    return f"{mins}:{secs:02d}"

                runs['pace_str'] = runs['pace_decimal'].apply(decimal_to_pace)
                
                fig_pace = px.scatter(runs, x='date', y='pace_decimal', 
                                      color='avg_heartrate', 
                                      title="Évolution de l'allure (min/km) au fil du temps",
                                      labels={'pace_decimal': 'Allure (min/km)'},
                                      hover_data=['pace_str', 'distance_km'])
                # Inverser l'axe Y car une allure plus basse est meilleure
                fig_pace.update_yaxes(autorange="reversed")
                st.plotly_chart(fig_pace, width='stretch')
        else:
            st.warning("Pas assez de données de fréquence cardiaque pour l'analyse physiologique.")

    with tab3:
        st.subheader("Carte Thermique des Activités")
        st.caption("Affichage basé sur les 'Summary Polylines' (Optimisé pour la vitesse)")
        
        # Centrer la carte sur la dernière activité ou une position par défaut
        # On cherche une activité qui a une polyline valide
        valid_map_activities = df_filtered[df_filtered['map_polyline'].notna() & (df_filtered['map_polyline'] != "")]
        
        if not valid_map_activities.empty:
            # On prend la première pour centrer la carte
            first_poly = valid_map_activities.iloc[0]['map_polyline']
            try:
                start_coords = decode(first_poly)[0]
                m = folium.Map(location=start_coords, zoom_start=11, tiles='CartoDB dark_matter')
                
                # Ajout des traces
                for poly in valid_map_activities['map_polyline']:
                    try:
                        coords = decode(poly)
                        if coords:
                            folium.PolyLine(coords, color='#ff4b4b', weight=2, opacity=0.5).add_to(m)
                    except Exception:
                        continue # On ignore les erreurs de décodage isolées
                
                folium_static(m, width=1000)
            except Exception as e:
                st.error(f"Erreur lors de la génération de la carte: {e}")
        else:
            st.info("Aucune donnée GPS disponible pour afficher la carte.")

    with tab4:
        st.subheader("Données Brutes")
        # On affiche uniquement les colonnes utiles
        display_cols = ['name', 'date', 'type', 'distance_km', 'duration_sec', 'elevation_m', 'avg_heartrate', 'avg_speed_kmh']
        st.dataframe(df_filtered[display_cols].sort_values('date', ascending=False))

    with tab5:
        st.subheader("🔬 Analyse Comportementale & Performance")

        # --- 1. MATRICE TEMPORELLE (Jour vs Heure) ---
        st.markdown("#### 📅 Quand t'entraînes-tu le plus ? (Habitudes)")
        st.caption("La taille des points correspond à la distance parcourue. Seuls les créneaux actifs sont affichés.")

        # Préparation des données
        df_habit = df_filtered.copy()
        df_habit['hour'] = df_habit['date'].dt.hour
        df_habit['day_name'] = df_habit['date'].dt.day_name()
        
        # Ordre des jours pour l'affichage (Lundi -> Dimanche)
        days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        days_fr_map = {'Monday': 'Lundi', 'Tuesday': 'Mardi', 'Wednesday': 'Mercredi', 'Thursday': 'Jeudi', 'Friday': 'Vendredi', 'Saturday': 'Samedi', 'Sunday': 'Dimanche'}
        
        # On groupe par Jour et Heure pour avoir la somme des distances
        habit_group = df_habit.groupby(['day_name', 'hour'])['distance_km'].sum().reset_index()
        habit_group['day_fr'] = habit_group['day_name'].map(days_fr_map)
        
        # Le Bubble Chart
        fig_bubble = px.scatter(habit_group, 
                                x='day_fr', 
                                y='hour', 
                                size='distance_km', 
                                color='distance_km',
                                color_continuous_scale='Teal',
                                labels={'day_fr': 'Jour', 'hour': 'Heure (24h)', 'distance_km': 'Volume (km)'},
                                category_orders={'day_fr': [days_fr_map[d] for d in days_order]})
        
        # Inverser l'axe Y pour avoir le matin en haut (optionnel, mais souvent plus lisible)
        # Et forcer l'affichage de toutes les heures présentes
        fig_bubble.update_yaxes(autorange="reversed", dtick=1)
        fig_bubble.update_layout(height=500)
        
        st.plotly_chart(fig_bubble, width='stretch')

        st.markdown("---")

        # --- 2. COMPARAISON ANNUELLE (N vs N-1) ---
        st.markdown("#### ⚔️ Duel : Cette année vs Année précédente")
        
        current_year = df['date'].dt.year.max()
        prev_year = current_year - 1
        
        # On filtre les données pour ces deux années
        df_yoy = df[df['year'].isin([current_year, prev_year])].copy()
        
        if not df_yoy.empty:
            # On calcule le jour de l'année (1 à 365) pour pouvoir comparer
            df_yoy['day_of_year'] = df_yoy['date'].dt.dayofyear
            
            # On groupe par année et jour, puis on fait la somme cumulative
            df_cumul = df_yoy.groupby(['year', 'day_of_year'])['distance_km'].sum().groupby(level=0).cumsum().reset_index()
            
            # Création du graphique de ligne
            fig_yoy = px.line(df_cumul, x='day_of_year', y='distance_km', color='year',
                              title=f"Progression Distance Cumulée : {prev_year} vs {current_year}",
                              labels={'day_of_year': 'Jour de l\'année (1-365)', 'distance_km': 'Distance Cumulée (km)', 'year': 'Année'},
                              color_discrete_map={current_year: '#00cc96', prev_year: '#636efa'}) # Vert pour l'année courante
            
            fig_yoy.update_traces(line=dict(width=3))
            fig_yoy.update_layout(hovermode="x unified")
            
            st.plotly_chart(fig_yoy, width='stretch')
            
            # Petit KPI textuel de comparaison
            max_day_current = df_cumul[df_cumul['year'] == current_year]['day_of_year'].max()
            
            # On cherche où on en était l'année dernière au même jour
            last_year_same_day = df_cumul[(df_cumul['year'] == prev_year) & (df_cumul['day_of_year'] == max_day_current)]
            
            if not last_year_same_day.empty:
                dist_n_1 = last_year_same_day['distance_km'].values[0]
                dist_n = df_cumul[df_cumul['year'] == current_year]['distance_km'].max()
                diff = dist_n - dist_n_1
                
                emoji = "🚀" if diff > 0 else "🐢"
                
                # CORRECTION ICI : On définit le texte avant pour éviter le backslash dans la f-string
                etat_avance = "d'avance" if diff > 0 else "de retard"
                
                st.info(f"{emoji} Au jour n°{max_day_current}, tu as **{abs(diff):.1f} km** {etat_avance} sur l'année {prev_year}.")
        else:
            st.warning("Pas assez de données historiques pour comparer deux années.")

        st.markdown("---")

        # --- 3. CHARGE D'ENTRAÎNEMENT (Weekly Load) ---
        st.markdown("#### ⚡ Charge d'entraînement Hebdomadaire (Suffer Score)")
        st.caption("Le 'Suffer Score' (ou intensité relative) x Durée. Permet de voir la charge réelle sur l'organisme.")
        
        # On groupe par Semaine
        # 'W-MON' signifie qu'on groupe par semaine commençant le Lundi
        df_load = df_filtered.set_index('date').resample('W-MON')[['suffer_score', 'distance_km']].sum().reset_index()
        
        # On filtre les semaines futures ou vides
        df_load = df_load[df_load['suffer_score'] > 0]
        
        if not df_load.empty:
            # Graphique combiné : Barres pour le Suffer Score, Ligne pour la distance
            fig_load = go.Figure()
            
            # Barres : Charge (Suffer Score)
            fig_load.add_trace(go.Bar(
                x=df_load['date'],
                y=df_load['suffer_score'],
                name='Charge (Suffer Score)',
                marker_color='#EF553B'
            ))
            
            # Ligne : Distance (sur un axe Y secondaire pour l'échelle)
            fig_load.add_trace(go.Scatter(
                x=df_load['date'],
                y=df_load['distance_km'],
                name='Distance (km)',
                yaxis='y2',
                line=dict(color='#FFA15A', width=2, dash='dot')
            ))
            
            fig_load.update_layout(
                title="Intensité (Barres) vs Volume (Ligne) par semaine",
                yaxis=dict(title="Suffer Score Cumulé"),
                yaxis2=dict(title="Distance (km)", overlaying='y', side='right'),
                hovermode="x unified",
                legend=dict(orientation="h", y=1.1)
            )
            
            st.plotly_chart(fig_load, width='stretch')
        else:
            st.write("Pas de données de Suffer Score disponibles.")