import streamlit as st
from supabase import create_client, Client
import pandas as pd
import folium
from streamlit_folium import st_folium

# Configuration de la page
st.set_page_config(page_title="Dashboard Logistique DIX", page_icon="📊", layout="wide")

# Styles personnalisés
st.markdown("""
    <style>
    .main { font-family: 'Georgia', serif; }
    h1, h2, h3, h4 { font-family: 'Oswald', sans-serif; font-weight: 400 !important; text-transform: uppercase; color: #405F59; }
    [data-testid="stMetricValue"] { font-family: 'Oswald', sans-serif; font-weight: 400 !important; color: #549e39; }
    .stCaption { font-style: italic; color: #7f8c8d; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 1. CONNEXION À SUPABASE
# ==========================================
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

try:
    supabase: Client = init_connection()
except Exception as e:
    st.error("Erreur de connexion à Supabase. Vérifiez votre fichier .streamlit/secrets.toml")
    st.stop()

# ==========================================
# 2. RÉCUPÉRATION ET TRAITEMENT
# ==========================================
@st.cache_data(ttl=60)
def fetch_data():
    response = supabase.table("tournees_test").select("*").execute()
    return response.data

def process_full_data(raw_data):
    """ Transforme le JSON complexe en deux DataFrames : un pour les tournées, un pour les structures """
    processed_tours = []
    processed_structures = {}
    
    for row in raw_data:
        data_json = row.get("data_json", {})
        depot = data_json.get("depot", {})
        tours = data_json.get("tours", [])
        
        struct_name = depot.get("name", "Non renseigné")
        
        # On alimente le dictionnaire unique des structures
        if struct_name not in processed_structures:
            processed_structures[struct_name] = {
                "Structure": struct_name,
                "Véhicule Principal": depot.get("vehicule", "Non précisé"),
                "Énergie": depot.get("energie", ""),
                "Chauffeur": depot.get("driver", "Non précisé"),
                "Coût RH (€/h)": float(depot.get("cout_h", 0)),
                "Surf. Prépa (m²)": float(depot.get("stock_prep", 0)),
                "Surf. Sec (m²)": float(depot.get("stock_sec", 0)),
                "Surf. Frais (m²)": float(depot.get("stock_frais", 0)),
                "Surf. Négatif (m²)": float(depot.get("stock_neg", 0)),
            }
        
        # On alimente la liste des tournées (sans l'utilisateur)
        for tour in tours:
            stats = tour.get("stats", {})
            processed_tours.append({
                "ID_Dossier": row.get("id"),
                "Structure": struct_name,
                "Tournée": tour.get("name", "Sans nom"),
                "Jour": tour.get("day", ""),
                "Nb Arrêts": len(tour.get("stops", [])),
                "Distance (km)": round(stats.get("dist", 0), 1),
                "Temps (min)": round(stats.get("time", 0), 0),
                "Coût Total (€)": round(stats.get("cost", 0), 2),
                "Valeur (€)": round(stats.get("ca", 0), 2),
                "Ratio (%)": float(stats.get("ratio", 0)),
                "coords_depot": [depot.get("lat"), depot.get("lon")],
                "stops": tour.get("stops", [])
            })
            
    df_tours = pd.DataFrame(processed_tours)
    df_structs = pd.DataFrame(list(processed_structures.values()))
    return df_tours, df_structs

# ==========================================
# 3. INTERFACE UTILISATEUR
# ==========================================
st.title("📊 Synthèse des Tournées Logistiques")

with st.spinner("Synchronisation avec Supabase..."):
    raw_data = fetch_data()

if not raw_data:
    st.info("Aucune donnée disponible.")
else:
    df_tours, df_structs = process_full_data(raw_data)
    
    # -- Filtres avec Multiselect --
    st.sidebar.header("Filtres")
    
    all_structures = list(df_tours['Structure'].unique())
    selected_structures = st.sidebar.multiselect("Sélectionner les Structures", all_structures, default=all_structures)
    
    all_jours = list(df_tours['Jour'].unique())
    selected_jours = st.sidebar.multiselect("Jours de passage", all_jours, default=all_jours)
    
    # Filtrage des DataFrames
    filtered_df = df_tours[
        (df_tours['Structure'].isin(selected_structures)) & 
        (df_tours['Jour'].isin(selected_jours))
    ]
    filtered_structs = df_structs[df_structs['Structure'].isin(selected_structures)]

    # -- KPIs --
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tournées analysées", len(filtered_df))
    col2.metric("Distance totale", f"{filtered_df['Distance (km)'].sum():.1f} km")
    col3.metric("Coût logistique", f"{filtered_df['Coût Total (€)'].sum():.2f} €")
    
    total_val = filtered_df['Valeur (€)'].sum()
    avg_ratio = (filtered_df['Coût Total (€)'].sum() / total_val * 100) if total_val > 0 else 0
    col4.metric("Ratio moyen", f"{avg_ratio:.1f} %")

    st.divider()

    # -- CARTE DES TOURNÉES --
    st.subheader("📍 Carte géographique des flux")
    
    if not filtered_df.empty:
        # On essaie de trouver un centre valide
        valid_coords = filtered_df[filtered_df['coords_depot'].map(lambda x: x[0] is not None)]
        if not valid_coords.empty:
            center = valid_coords.iloc[0]['coords_depot']
        else:
            center = [46.603354, 1.888334] # Centre de la France par défaut
            
        m = folium.Map(location=center, zoom_start=9, tiles="cartodbvoyager")
        
        for idx, row in filtered_df.iterrows():
            depot_coords = row['coords_depot']
            stops = row['stops']
            
            if depot_coords[0]:
                # 1. Dessiner le tracé (PolyLine)
                path_coords = [depot_coords]
                for s in stops:
                    path_coords.append([s['lat'], s['lon']])
                path_coords.append(depot_coords) # Retour au dépôt
                
                folium.PolyLine(
                    locations=path_coords,
                    color="#549e39",
                    weight=2,
                    opacity=0.5,
                    dash_array='5, 10', 
                    tooltip=f"Tournée : {row['Tournée']}"
                ).add_to(m)

                # 2. Le Dépôt
                folium.Marker(
                    location=depot_coords,
                    popup=f"Dépôt: {row['Structure']}",
                    icon=folium.Icon(color="darkgreen", icon="home", prefix="fa")
                ).add_to(m)
            
            # 3. Les Arrêts
            for i, stop in enumerate(stops):
                folium.CircleMarker(
                    location=[stop['lat'], stop['lon']],
                    radius=5,
                    color="#549e39",
                    fill=True,
                    fill_color="#549e39",
                    fill_opacity=0.8,
                    popup=f"Arrêt {i+1}: {stop['client']} ({row['Tournée']})"
                ).add_to(m)
        
        st_folium(m, width="100%", height=500, returned_objects=[])
    else:
        st.warning("Sélectionnez au moins une structure et un jour pour afficher la carte.")

    st.divider()

    # -- NOUVEAU BLOC : DONNÉES DES STRUCTURES (Infrastructures) --
    st.subheader("📦 Paramètres et Espaces de Stockage")
    st.write("Synthèse des moyens logistiques engagés par les structures sélectionnées.")
    st.dataframe(filtered_structs, use_container_width=True, hide_index=True)

    st.divider()

    # -- TABLEAU DE DONNÉES (TOURNÉES) --
    st.subheader("📝 Détail des flux de transport")
    # On masque les colonnes techniques pour l'affichage du tableau
    display_df = filtered_df.drop(columns=['coords_depot', 'stops', 'ID_Dossier'])
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    st.download_button(
        "📥 Exporter les données de transport en CSV", 
        display_df.to_csv(index=False).encode('utf-8'), 
        'export_flux_logistique.csv', 
        'text/csv'
    )

    # ==========================================
    # NOTE SUR L'USAGE DES DONNÉES
    # ==========================================
    st.divider()
    st.caption("""
        🛡️ **Note sur la confidentialité et l'usage des données** : 
        Les informations présentées sur ce tableau de bord sont issues des simulations volontaires réalisées par les entrepreneurs via l'outil DIX. 
        Elles sont collectées dans le but unique de favoriser la mutualisation logistique territoriale et de réduire l'empreinte environnementale des transports. 
        Aucune donnée n'est cédée à des tiers à des fins commerciales.
    """)
