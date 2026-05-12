"""
VitalSync LLM Health Advisor
Uses Claude API for:
1. Daily evening check-in conversation (lifestyle questions)
2. Doctor-like analysis of combined vitals + lifestyle data
3. Medicine prescription for minor ailments
"""
import anthropic
from app.core.config import get_settings

settings = get_settings()


def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


# ── Daily Check-In ─────────────────────────────────────────────────────────────

def run_daily_checkin(
    patient_name: str,
    avg_vitals: dict,
    user_responses: dict
) -> dict:
    """
    Sends today's vitals + user lifestyle answers to Claude.
    Returns structured analysis.

    avg_vitals: { heart_rate, spo2, temperature, systolic_bp, diastolic_bp }
    user_responses: { food, symptoms, diet, sleep_hours, exercise_minutes, stress_level }
    """
    client = get_client()

    prompt = f"""You are VitalSync's AI health advisor acting like a knowledgeable, caring doctor. 
Analyze the following health data for patient {patient_name} and provide a daily health assessment.

TODAY'S AVERAGE VITALS:
- Heart Rate: {avg_vitals.get('heart_rate', 'N/A')} BPM
- SpO2 (Blood Oxygen): {avg_vitals.get('spo2', 'N/A')}%
- Body Temperature: {avg_vitals.get('temperature', 'N/A')}°C
- Blood Pressure: {avg_vitals.get('systolic_bp', 'N/A')}/{avg_vitals.get('diastolic_bp', 'N/A')} mmHg

PATIENT SELF-REPORT:
- Food intake today: {user_responses.get('food', 'Not reported')}
- Symptoms experienced: {user_responses.get('symptoms', 'None reported')}
- Diet notes: {user_responses.get('diet', 'Not reported')}
- Sleep last night: {user_responses.get('sleep_hours', 'N/A')} hours
- Exercise today: {user_responses.get('exercise_minutes', '0')} minutes
- Stress level: {user_responses.get('stress_level', '5')}/10

Provide your response as a JSON object with these exact keys:
{{
  "overall_assessment": "2-3 sentence overall health summary",
  "health_score": <number 0-100>,
  "positive_observations": ["list of good health indicators"],
  "concerns": ["list of concerns or areas to watch"],
  "recommendations": ["3-5 specific actionable recommendations for tomorrow"],
  "diet_advice": "specific dietary advice based on their report",
  "warning_level": "green|yellow|orange|red",
  "follow_up_needed": true|false,
  "follow_up_reason": "why follow-up is needed (or null)"
}}

Be warm, encouraging, specific, and clinically accurate. Do not be alarmist unless truly warranted."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text
    # Parse JSON from response
    import json, re
    try:
        # Extract JSON even if wrapped in markdown
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    # Fallback if parsing fails
    return {
        "overall_assessment": raw_text[:300],
        "health_score": 75,
        "positive_observations": [],
        "concerns": [],
        "recommendations": ["Please consult VitalSync tomorrow for a detailed check-in."],
        "diet_advice": "Maintain a balanced diet.",
        "warning_level": "green",
        "follow_up_needed": False,
        "follow_up_reason": None
    }


# ── AI Prescription ────────────────────────────────────────────────────────────

def generate_ai_prescription(
    patient_name: str,
    age: int,
    symptoms: str,
    vitals: dict,
    known_allergies: str = ""
) -> dict:
    """
    Generate an AI prescription for minor, self-limiting conditions.
    DISCLAIMER: Always included — not a substitute for professional medical advice.
    """
    client = get_client()

    prompt = f"""You are VitalSync's AI medical advisor. A patient needs guidance for a minor health issue.

PATIENT: {patient_name}, Age: {age}
SYMPTOMS: {symptoms}
CURRENT VITALS: HR {vitals.get('heart_rate')} BPM, SpO2 {vitals.get('spo2')}%, Temp {vitals.get('temperature')}°C, BP {vitals.get('systolic_bp')}/{vitals.get('diastolic_bp')}
KNOWN ALLERGIES: {known_allergies or 'None reported'}

IMPORTANT: Only provide recommendations for MINOR, SELF-LIMITING conditions (common cold, mild headache, minor indigestion, etc.). If the condition appears serious or the vitals are abnormal, strongly recommend seeing a real doctor.

Respond with a JSON object:
{{
  "condition_assessment": "what you think this might be",
  "severity": "minor|moderate|serious",
  "can_treat_at_home": true|false,
  "medicines": [
    {{
      "name": "Medicine name (generic)",
      "dosage": "dosage instructions",
      "frequency": "how often",
      "duration": "for how long",
      "notes": "any special instructions"
    }}
  ],
  "home_remedies": ["list of safe home remedies"],
  "do_not_do": ["things to avoid"],
  "see_doctor_if": ["list of warning signs that require real medical attention"],
  "disclaimer": "Standard medical disclaimer"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_text = response.content[0].text
    import json, re
    try:
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            result = json.loads(match.group())
            result["disclaimer"] = (
                "⚠️ IMPORTANT: This AI-generated guidance is for informational purposes only and is NOT "
                "a substitute for professional medical advice, diagnosis, or treatment. Always consult a "
                "qualified healthcare provider for medical concerns."
            )
            return result
    except Exception:
        pass

    return {
        "condition_assessment": "Unable to assess. Please consult a doctor.",
        "severity": "unknown",
        "can_treat_at_home": False,
        "medicines": [],
        "home_remedies": [],
        "do_not_do": [],
        "see_doctor_if": ["Any persistent or worsening symptoms"],
        "disclaimer": "Please consult a qualified healthcare provider."
    }


# ── Emergency Budget Estimation ────────────────────────────────────────────────

def estimate_treatment_budget(
    diagnosis: str,
    city: str,
    hospital_data: dict
) -> dict:
    """
    Use Claude to estimate treatment budget range based on hospital data.
    """
    client = get_client()

    prompt = f"""You are a medical financial advisor in India. Estimate the treatment budget for:

CONDITION: {diagnosis}
CITY: {city}
HOSPITAL INFO: {hospital_data}

Provide a JSON response:
{{
  "estimated_min": <number in INR>,
  "estimated_max": <number in INR>,
  "cost_breakdown": {{
    "consultation": <amount>,
    "tests": <amount>,
    "medicines": <amount>,
    "hospitalization_per_day": <amount or null>,
    "other": <amount>
  }},
  "insurance_tip": "brief tip about insurance coverage",
  "cost_saving_tips": ["2-3 tips to reduce costs"]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    import json, re
    try:
        match = re.search(r'\{.*\}', response.content[0].text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    return {"estimated_min": 0, "estimated_max": 0, "cost_breakdown": {}, "insurance_tip": "", "cost_saving_tips": []}


# ── Check-In Questions ──────────────────────────────────────────────────────────

DAILY_CHECKIN_QUESTIONS = [
    {
        "id": "food",
        "question": "What did you eat today? (breakfast, lunch, dinner, snacks)",
        "type": "text"
    },
    {
        "id": "symptoms",
        "question": "Did you experience any unusual symptoms today? (headache, fatigue, pain, etc.)",
        "type": "text"
    },
    {
        "id": "diet",
        "question": "How would you describe your diet today?",
        "type": "select",
        "options": ["Healthy & balanced", "Mostly healthy", "Mixed", "Mostly unhealthy", "Skipped meals"]
    },
    {
        "id": "sleep_hours",
        "question": "How many hours did you sleep last night?",
        "type": "number",
        "min": 0, "max": 24
    },
    {
        "id": "exercise_minutes",
        "question": "How many minutes of physical activity did you get today?",
        "type": "number",
        "min": 0, "max": 300
    },
    {
        "id": "stress_level",
        "question": "Rate your stress level today (1 = very relaxed, 10 = extremely stressed)",
        "type": "number",
        "min": 1, "max": 10
    },
    {
        "id": "water_intake",
        "question": "How many glasses of water did you drink today?",
        "type": "number",
        "min": 0, "max": 20
    }
]
