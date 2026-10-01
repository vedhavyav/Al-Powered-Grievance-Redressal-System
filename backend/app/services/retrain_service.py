import joblib
import os
from app.utils.aggregate_data import fetch_aggregated_data
from app.db.connection import get_db
from app.services.forecast_manager import update_forecast_cache

def retrain_forecast_models():
    """
    Retrains Prophet models using real grievance data if enough exists.
    Falls back to trained dataset otherwise.
    """
    from prophet import Prophet
    db = next(get_db())
    df = fetch_aggregated_data(db)

    if df is None or len(df["date"].unique()) < 60:
        print("Not enough real data for retraining. Using pretrained dataset.")
        return False  # This will trigger fallback to trained model

    categories = df["category"].unique()
    models = {}

    for category in categories:
        df_cat = df[df["category"] == category].groupby("date")["count"].sum().reset_index()
        df_cat.rename(columns={"date": "ds", "count": "y"}, inplace=True)

        model = Prophet(yearly_seasonality=True, weekly_seasonality=True)
        model.fit(df_cat)
        models[category] = model

    # Save retrained model
    os.makedirs("app/models/forecast", exist_ok=True)
    model_path = "app/models/forecast/up_forecast.pkl"
    joblib.dump(models, model_path)
    update_forecast_cache(models)

    print(f"Retrained Prophet models saved at {model_path}")
    return True
