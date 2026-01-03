# Strava Analytics

Un tableau de bord interactif créé avec Python et Streamlit pour analyser vos données sportives Strava (Course à pied, Vélo, etc.) avec des métriques avancées.

## Prérequis

* Python 3.8 ou supérieur
* Un compte Strava

## 🛠 Installation

1.  **Cloner le projet** (ou télécharger les fichiers) dans un dossier.

2.  **Créer un environnement virtuel** (recommandé) :
    ```bash
    python -m venv venv
    # Activation sous Windows :
    .\venv\Scripts\activate
    # Activation sous Mac/Linux :
    source venv/bin/activate
    ```

3.  **Installer les dépendances** :
    ```bash
    pip install -r requirements.txt
    ```

## Configuration (.env)

C'est l'étape la plus importante pour que l'application puisse accéder à vos données.

1.  Créez un fichier nommé `.env` à la racine du projet (au même endroit que `strava.py`).
2.  Ouvrez ce fichier avec un éditeur de texte.
3.  Ajoutez vos identifiants API Strava sous la forme suivante :

```env
VOTRE_CLIENT_ID='votre_id_ici'
VOTRE_CLIENT_SECRET='votre_secret_ici'
VOTRE_REFRESH_TOKEN='votre_refresh_token_ici'