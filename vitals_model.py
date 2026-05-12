"""
VitalSync ML Engine
- Random Forest vitals classifier (healthy/warning/critical/emergency)
- Isolation Forest anomaly detector
- Gradient Boosting disease risk predictor
- Rule-based emergency detection (instant, no model needed)
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, IsolationForest, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib
import os
from pathlib import Path

MODEL_DIR = Path(__file__).parent / "saved_models"
MODEL_DIR.mkdir(exist_ok=True)


# ── Synthetic Training Data ────────────────────────────────────────────────────

def generate_training_data(n_samples: int = 5000) -> tuple:
    """
    Generate realistic synthetic vital sign data with labeled health status.
    Based on clinical normal ranges.
    """
    np.random.seed(42)
    data = []
    labels = []

    for _ in range(n_samples):
        # Choose a health state with realistic distribution
        state = np.random.choice(
            ["healthy", "warning", "critical", "emergency"],
            p=[0.70, 0.20, 0.08, 0.02]
        )

        if state == "healthy":
            hr = np.random.normal(72, 8)        # 60-100 BPM normal
            spo2 = np.random.normal(98, 0.8)    # 95-100% normal
            temp = np.random.normal(36.8, 0.3)  # 36.1-37.5°C normal
            sys_bp = np.random.normal(120, 10)  # 90-130 mmHg normal
            dia_bp = np.random.normal(80, 8)
            ecg = np.random.normal(0.5, 0.1)
            fall = 0

        elif state == "warning":
            hr = np.random.choice([
                np.random.normal(50, 5),   # Bradycardia
                np.random.normal(110, 8),  # Tachycardia
            ])
            spo2 = np.random.normal(93, 1.5)   # Mild hypoxia
            temp = np.random.choice([
                np.random.normal(38.5, 0.3),   # Mild fever
                np.random.normal(35.5, 0.3),   # Mild hypothermia
            ])
            sys_bp = np.random.choice([
                np.random.normal(145, 8),
                np.random.normal(85, 5),
            ])
            dia_bp = np.random.normal(90, 8)
            ecg = np.random.normal(0.7, 0.15)
            fall = 0

        elif state == "critical":
            hr = np.random.choice([
                np.random.normal(140, 10),  # Severe tachycardia
                np.random.normal(40, 5),    # Severe bradycardia
            ])
            spo2 = np.random.normal(88, 2)     # Severe hypoxia
            temp = np.random.choice([
                np.random.normal(39.5, 0.3),   # High fever
                np.random.normal(34.5, 0.5),   # Hypothermia
            ])
            sys_bp = np.random.choice([
                np.random.normal(175, 10),
                np.random.normal(70, 8),       # Hypotensive shock
            ])
            dia_bp = np.random.normal(110, 10)
            ecg = np.random.normal(1.2, 0.2)
            fall = np.random.choice([0, 1], p=[0.8, 0.2])

        else:  # emergency
            hr = np.random.choice([
                np.random.normal(180, 15),  # VT/SVT
                np.random.normal(25, 5),    # Severe bradycardia
                np.random.normal(0, 3),     # Cardiac arrest
            ])
            spo2 = np.random.normal(82, 3)
            temp = np.random.choice([
                np.random.normal(40.5, 0.3),
                np.random.normal(33, 1),
            ])
            sys_bp = np.random.choice([
                np.random.normal(200, 10),
                np.random.normal(55, 10),
            ])
            dia_bp = np.random.normal(120, 15)
            ecg = np.random.normal(1.8, 0.3)
            fall = np.random.choice([0, 1], p=[0.5, 0.5])

        data.append([
            max(0, hr), min(100, max(80, spo2)), temp,
            sys_bp, dia_bp, ecg, fall
        ])
        labels.append(state)

    feature_names = ["heart_rate", "spo2", "temperature", "systolic_bp", "diastolic_bp", "ecg_value", "fall_detected"]
    return pd.DataFrame(data, columns=feature_names), np.array(labels)


# ── Disease Risk Data ──────────────────────────────────────────────────────────

def generate_disease_risk_data(n_samples: int = 3000) -> tuple:
    """Generate data for disease risk prediction."""
    np.random.seed(123)
    data = []
    labels = []

    diseases = ["none", "hypertension", "diabetes_risk", "respiratory", "cardiac_risk", "anemia"]

    for _ in range(n_samples):
        disease = np.random.choice(diseases, p=[0.50, 0.15, 0.12, 0.10, 0.08, 0.05])

        avg_hr = np.random.normal(72, 10)
        avg_spo2 = np.random.normal(97, 1.5)
        avg_temp = np.random.normal(36.8, 0.4)
        avg_sys = np.random.normal(120, 12)
        avg_dia = np.random.normal(80, 8)
        hr_variability = np.random.normal(5, 2)
        daily_score = np.random.normal(75, 10)

        if disease == "hypertension":
            avg_sys = np.random.normal(148, 12)
            avg_dia = np.random.normal(95, 8)
            hr_variability = np.random.normal(3, 1)
        elif disease == "diabetes_risk":
            avg_hr = np.random.normal(80, 8)
            daily_score = np.random.normal(60, 12)
        elif disease == "respiratory":
            avg_spo2 = np.random.normal(93, 2)
            avg_hr = np.random.normal(88, 10)
        elif disease == "cardiac_risk":
            avg_hr = np.random.normal(90, 15)
            avg_sys = np.random.normal(145, 15)
            hr_variability = np.random.normal(8, 3)
        elif disease == "anemia":
            avg_hr = np.random.normal(95, 10)
            avg_spo2 = np.random.normal(94, 2)

        data.append([avg_hr, avg_spo2, avg_temp, avg_sys, avg_dia, hr_variability, daily_score])
        labels.append(disease)

    feature_names = ["avg_hr", "avg_spo2", "avg_temp", "avg_sys", "avg_dia", "hr_variability", "daily_score"]
    return pd.DataFrame(data, columns=feature_names), np.array(labels)


# ── Training ───────────────────────────────────────────────────────────────────

def train_and_save_models():
    print("🔬 Training VitalSync ML models...")

    # 1. Vitals Classifier (Random Forest)
    X, y = generate_training_data(6000)
    vitals_pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1
        ))
    ])
    vitals_pipeline.fit(X, y)
    joblib.dump(vitals_pipeline, MODEL_DIR / "vitals_classifier.pkl")
    print(f"✅ Vitals classifier trained | Classes: {vitals_pipeline.classes_}")

    # 2. Anomaly Detector (Isolation Forest - trained on healthy data only)
    X_healthy = X[y == "healthy"]
    anomaly_detector = Pipeline([
        ("scaler", StandardScaler()),
        ("iso", IsolationForest(contamination=0.05, random_state=42, n_jobs=-1))
    ])
    anomaly_detector.fit(X_healthy)
    joblib.dump(anomaly_detector, MODEL_DIR / "anomaly_detector.pkl")
    print("✅ Anomaly detector trained")

    # 3. Disease Risk Predictor (Gradient Boosting)
    X_d, y_d = generate_disease_risk_data(4000)
    disease_pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.1,
            random_state=42
        ))
    ])
    disease_pipeline.fit(X_d, y_d)
    joblib.dump(disease_pipeline, MODEL_DIR / "disease_predictor.pkl")
    print(f"✅ Disease predictor trained | Classes: {disease_pipeline.classes_}")

    print("🎉 All models saved to", MODEL_DIR)
    return vitals_pipeline, anomaly_detector, disease_pipeline


# ── Inference ──────────────────────────────────────────────────────────────────

class VitalSignsAnalyzer:
    """Main ML inference class loaded once at startup."""

    def __init__(self):
        self.vitals_clf = None
        self.anomaly_det = None
        self.disease_pred = None
        self._load_models()

    def _load_models(self):
        try:
            self.vitals_clf = joblib.load(MODEL_DIR / "vitals_classifier.pkl")
            self.anomaly_det = joblib.load(MODEL_DIR / "anomaly_detector.pkl")
            self.disease_pred = joblib.load(MODEL_DIR / "disease_predictor.pkl")
            print("✅ ML models loaded successfully")
        except FileNotFoundError:
            print("⚠️  Models not found. Running train_and_save_models()...")
            train_and_save_models()
            self._load_models()

    def analyze_vitals(self, vitals: dict) -> dict:
        """
        Full analysis of a single vital reading.
        Returns status, confidence, anomaly flag, emergency flags.
        """
        features = np.array([[
            vitals.get("heart_rate", 72),
            vitals.get("spo2", 98),
            vitals.get("temperature", 36.8),
            vitals.get("systolic_bp", 120),
            vitals.get("diastolic_bp", 80),
            vitals.get("ecg_value", 0.5),
            1.0 if vitals.get("fall_detected") else 0.0,
        ]])

        # 1. Rule-based emergency detection (no ML needed — instant)
        emergency_flags = self._check_emergency_rules(vitals)

        # 2. ML classification
        status = self.vitals_clf.predict(features)[0]
        probas = self.vitals_clf.predict_proba(features)[0]
        confidence = float(max(probas))
        classes = self.vitals_clf.classes_

        # 3. Anomaly score
        anomaly_score = float(self.anomaly_det.decision_function(features)[0])
        is_anomaly = self.anomaly_det.predict(features)[0] == -1

        # Override with emergency rules if needed
        if emergency_flags:
            status = "emergency"
            confidence = 1.0

        # Build probability dict
        prob_dict = {cls: float(p) for cls, p in zip(classes, probas)}

        return {
            "status": status,
            "confidence": round(confidence, 3),
            "probabilities": prob_dict,
            "is_anomaly": is_anomaly,
            "anomaly_score": round(anomaly_score, 3),
            "emergency_flags": emergency_flags,
            "notes": self._generate_notes(vitals, status, emergency_flags),
        }

    def predict_disease_risk(self, daily_stats: dict) -> dict:
        """Predict disease risk from aggregated daily data."""
        features = np.array([[
            daily_stats.get("avg_heart_rate", 72),
            daily_stats.get("avg_spo2", 98),
            daily_stats.get("avg_temperature", 36.8),
            daily_stats.get("avg_systolic_bp", 120),
            daily_stats.get("avg_diastolic_bp", 80),
            daily_stats.get("hr_variability", 5),
            daily_stats.get("daily_health_score", 80),
        ]])

        disease = self.disease_pred.predict(features)[0]
        probas = self.disease_pred.predict_proba(features)[0]
        classes = self.disease_pred.classes_
        prob_dict = {cls: round(float(p) * 100, 1) for cls, p in zip(classes, probas)}

        # Sort by probability
        sorted_risks = sorted(prob_dict.items(), key=lambda x: x[1], reverse=True)

        return {
            "primary_prediction": disease,
            "risk_percentages": dict(sorted_risks),
            "top_risks": sorted_risks[:3],
        }

    def calculate_health_score(self, vitals_list: list) -> float:
        """Calculate health score 0-100 from a list of vital readings."""
        if not vitals_list:
            return 75.0

        scores = []
        for v in vitals_list:
            result = self.analyze_vitals(v)
            status_score = {"healthy": 95, "warning": 65, "critical": 35, "emergency": 10}
            base = status_score.get(result["status"], 75)
            # Adjust by anomaly
            if result["is_anomaly"]:
                base = max(base - 15, 5)
            scores.append(base)

        return round(float(np.mean(scores)), 1)

    def _check_emergency_rules(self, v: dict) -> list:
        """Deterministic rule-based emergency detection."""
        flags = []
        hr = v.get("heart_rate", 72)
        spo2 = v.get("spo2", 98)
        temp = v.get("temperature", 36.8)
        sys_bp = v.get("systolic_bp", 120)

        if hr > 150 or hr < 35:
            flags.append("CRITICAL_HEART_RATE")
        if hr > 170:
            flags.append("POSSIBLE_CARDIAC_ARREST")
        if spo2 < 85:
            flags.append("SEVERE_HYPOXIA")
        if spo2 < 90:
            flags.append("HYPOXIA_WARNING")
        if temp > 40.0:
            flags.append("HYPERTHERMIA")
        if temp < 34.0:
            flags.append("HYPOTHERMIA")
        if sys_bp > 180:
            flags.append("HYPERTENSIVE_CRISIS")
        if sys_bp < 60:
            flags.append("SHOCK_HYPOTENSION")
        if v.get("fall_detected"):
            flags.append("FALL_DETECTED")

        return flags

    def _generate_notes(self, v: dict, status: str, flags: list) -> str:
        """Generate human-readable notes from vitals analysis."""
        if flags:
            flag_messages = {
                "CRITICAL_HEART_RATE": f"Heart rate {v.get('heart_rate'):.0f} BPM is dangerously abnormal",
                "POSSIBLE_CARDIAC_ARREST": "Possible cardiac event — immediate medical attention required",
                "SEVERE_HYPOXIA": f"SpO2 {v.get('spo2'):.1f}% — oxygen levels critically low",
                "HYPOXIA_WARNING": f"SpO2 {v.get('spo2'):.1f}% — oxygen levels below safe threshold",
                "HYPERTENSIVE_CRISIS": f"Blood pressure {v.get('systolic_bp'):.0f}/{v.get('diastolic_bp'):.0f} mmHg — hypertensive crisis",
                "SHOCK_HYPOTENSION": f"Blood pressure {v.get('systolic_bp'):.0f} mmHg — possible shock",
                "FALL_DETECTED": "Fall detected — checking for response",
                "HYPERTHERMIA": f"Temperature {v.get('temperature'):.1f}°C — dangerous heat level",
                "HYPOTHERMIA": f"Temperature {v.get('temperature'):.1f}°C — dangerously cold",
            }
            return " | ".join(flag_messages.get(f, f) for f in flags)

        notes = {
            "healthy": "All vital signs within normal range. Keep it up!",
            "warning": f"Some vitals need attention. HR: {v.get('heart_rate', 0):.0f}, SpO2: {v.get('spo2', 0):.1f}%",
            "critical": "Multiple vital signs outside safe range. Please consult a doctor.",
        }
        return notes.get(status, "Vital signs recorded.")


# Singleton instance
_analyzer: VitalSignsAnalyzer = None


def get_analyzer() -> VitalSignsAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = VitalSignsAnalyzer()
    return _analyzer


if __name__ == "__main__":
    train_and_save_models()
