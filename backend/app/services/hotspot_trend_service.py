import pandas as pd
from app.db.connection import get_db
from app.db.models import Grievance
import joblib
import numpy as np


def get_hotspot_trends(limit=5):
    """Combine real hotspot volume with Prophet forecast trend (region + category adaptive)."""
    db = next(get_db())
    try:
        # Optimized query: Project only needed columns and filter nulls at the DB layer
        rows = (
            db.query(
                Grievance.region,
                Grievance.latitude,
                Grievance.longitude,
                Grievance.category
            )
            .filter(
                Grievance.latitude.isnot(None),
                Grievance.longitude.isnot(None),
                Grievance.region.isnot(None)
            )
            .all()
        )

        if not rows:
            return {"message": "No valid geolocation data yet."}

        data = [
            {
                "region": r.region,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "category": r.category
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        if df.empty:
            return {"message": "No valid geolocation data yet."}

        # Aggregate complaint counts per region ---
        hotspot_df = (
            df.groupby(["region", "latitude", "longitude"])
            .size()
            .reset_index(name="complaint_count")
            .sort_values(by="complaint_count", ascending=False)
            .head(limit)
        )

        # Load Prophet models ---
        try:
            models = joblib.load("app/models/forecast/up_forecast.pkl")
            print("Forecast models loaded successfully.")
        except Exception as e:
            print("Could not load Prophet models:", e)
            models = {}

        results = []

        # For each hotspot region ---
        for _, row in hotspot_df.iterrows():
            region = row["region"]

            # Determine the dominant grievance category for this region
            region_categories = df[df["region"] == region]["category"].value_counts()
            category = region_categories.index[0] if not region_categories.empty else "Infrastructure"

            # Using corresponding Prophet model
            if category in models:
                model = models[category]

                # Forecast for next 30 days
                future = model.make_future_dataframe(periods=30)
                forecast = model.predict(future).tail(30)

                # Calculate trend
                first, last = forecast["yhat"].iloc[0], forecast["yhat"].iloc[-1]
                change = ((last - first) / first) * 100 if first != 0 else 0
                trend = (
                    "increase" if change > 5 else
                    "decrease" if change < -5 else
                    "stable"
                )
            else:
                change, trend = 0, "unknown"

            results.append({
                "region": region,
                "dominant_category": category,
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "current_complaints": int(row["complaint_count"]),
                "forecast_trend": trend,
                "expected_change_percent": round(change, 2)
            })

        # Sort by most active regions first ---
        results = sorted(results, key=lambda x: x["current_complaints"], reverse=True)
        return results
    finally:
        db.close()
