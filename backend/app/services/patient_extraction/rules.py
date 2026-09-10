"""Bounded, reviewable vocabulary and context rules; no inferred diagnoses."""

VERSION = "synthetic-facts-rules-v1"

# Canonical labels are project vocabulary, not licensed terminology codes.
LEXICON = {
    "condition": {
        "type_2_diabetes": r"type\s*(?:2|II)\s+diabetes(?:\s+mellitus)?",
        "diabetes": r"diabetes(?:\s+mellitus)?",
        "hypertension": r"hypertension|high blood pressure",
        "asthma": r"asthma",
        "copd": r"COPD|chronic obstructive pulmonary disease",
        "heart_failure": r"(?:congestive\s+)?heart failure",
        "atrial_fibrillation": r"atrial fibrillation",
        "chronic_kidney_disease": r"chronic kidney disease|CKD",
        "breast_cancer": r"breast cancer",
        "lung_cancer": r"(?:non[- ]small cell\s+)?lung cancer",
        "gastric_adenocarcinoma": r"gastric adenocarcinoma",
        "adenocarcinoma": r"adenocarcinoma",
        "lymphoma": r"lymphoma",
        "leukemia": r"leukemia|leukaemia",
        "melanoma": r"melanoma",
        "pneumonia": r"pneumonia",
        "tuberculosis": r"tuberculosis",
        "hiv": r"HIV",
        "hepatitis_c": r"hepatitis C",
        "stroke": r"stroke",
        "myocardial_infarction": r"myocardial infarction|heart attack",
        "depression": r"depression",
        "rheumatoid_arthritis": r"rheumatoid arthritis",
        "crohn_disease": r"Crohn(?:'s)? disease",
        "constipation": r"constipation",
        "cauda_equina_syndrome": r"cauda equina syndrome",
    },
    "medication": {
        name: name
        for name in (
            "metformin",
            "insulin",
            "aspirin",
            "warfarin",
            "apixaban",
            "lisinopril",
            "atorvastatin",
            "prednisone",
            "prednisolone",
            "methotrexate",
            "albuterol",
            "salbutamol",
            "ibuprofen",
            "amoxicillin",
            "cisplatin",
            "pembrolizumab",
        )
    },
    "treatment": {
        "chemotherapy": r"chemotherapy",
        "radiotherapy": r"radiotherapy|radiation therapy",
        "immunotherapy": r"immunotherapy",
        "dialysis": r"(?:hemo|haemo)?dialysis",
        "surgery": r"surgery|surgical resection",
        "transplant": r"(?:kidney|renal|liver|heart|bone marrow) transplant(?:ation)?",
    },
}

# Exact units only; unsupported units are retained as issues, never guessed.
MEASUREMENTS = {
    "hemoglobin": (r"ha?emoglobin|Hb", {"g/dL": "g/dL", "g/L": "g/L"}),
    "hba1c": (r"HbA1c", {"%": "%", "mmol/mol": "mmol/mol"}),
    "creatinine": (
        r"(?:serum\s+)?creatinine",
        {"mg/dL": "mg/dL", "umol/L": "umol/L", "µmol/L": "umol/L", "μmol/L": "umol/L"},
    ),
    "glucose": (r"(?:blood\s+)?glucose", {"mg/dL": "mg/dL", "mmol/L": "mmol/L"}),
    "weight": (r"weight", {"kg": "kg", "lb": "lb", "lbs": "lb"}),
    "height": (r"height", {"cm": "cm", "m": "m"}),
    "temperature": (r"temperature", {"°C": "C", "C": "C", "°F": "F", "F": "F"}),
    "heart_rate": (r"heart rate|pulse(?: rate)?", {"bpm": "bpm", "/min": "bpm"}),
    "oxygen_saturation": (r"oxygen saturation|SpO2", {"%": "%"}),
    "bmi": (r"BMI", {"kg/m2": "kg/m2", "kg/m²": "kg/m2"}),
}

FAMILY = (
    r"\b(?:mother|father|sisters?|brothers?|daughters?|sons?|parents?|children|child|"
    r"aunt|uncle|grandmother|grandfather|family history)\b"
)
PATIENT = r"\b(?:the patient|patient|he|she)\s+(?:has|had|is|was|denies|takes|reports|underwent)\b"
NEGATION = (
    r"\b(?:no(?: evidence of)?|denies|denied|without|not taking|not receiving|"
    r"negative for|free of|never had)\b"
)
UNCERTAIN = (
    r"\b(?:possible|possibly|suspected|suspect|may have|might have|rule out|cannot exclude|"
    r"cannot rule out|unlikely|uncertain|question of|concern for|if|risk of|evaluate for)\b"
)
HISTORICAL = (
    r"\b(?:history of|previously|prior|past|formerly|had|was|stopped|discontinued|resolved|"
    r"underwent)\b|\b\d+\s+(?:years?|months?|weeks?|days?) ago\b"
)
PLANNED = (
    r"\b(?:planned|scheduled|will receive|will undergo|considering|consider|recommended|plan for)\b"
)
