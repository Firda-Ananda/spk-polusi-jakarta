import numpy as np
import pandas as pd

CRITERIA = ["PM2.5", "PM10", "NO2", "O3", "SO2", "CO"]
CSV_COLS = [
    "pm_duakomalima",
    "pm_sepuluh",
    "nitrogen_dioksida",
    "ozon",
    "sulfur_dioksida",
    "karbon_monoksida",
]

DEFAULT_PAIRWISE_MATRIX = [
    [1.0, 3.0, 5.0, 5.0, 7.0, 7.0],
    [1 / 3, 1.0, 3.0, 3.0, 5.0, 5.0],
    [1 / 5, 1 / 3, 1.0, 1.0, 3.0, 3.0],
    [1 / 5, 1 / 3, 1.0, 1.0, 3.0, 3.0],
    [1 / 7, 1 / 5, 1 / 3, 1 / 3, 1.0, 1.0],
    [1 / 7, 1 / 5, 1 / 3, 1 / 3, 1.0, 1.0],
]

SAATY_SCALE_OPTIONS = [
    (1.0, "1 - Sama penting"),
    (2.0, "2 - Mendekati sedikit lebih penting"),
    (3.0, "3 - Sedikit lebih penting"),
    (4.0, "4 - Mendekati lebih penting"),
    (5.0, "5 - Lebih penting"),
    (6.0, "6 - Mendekati jelas lebih penting"),
    (7.0, "7 - Jelas lebih penting"),
    (8.0, "8 - Mendekati mutlak lebih penting"),
    (9.0, "9 - Mutlak lebih penting"),
    (0.5, "1/2 - Sedikit kurang penting"),
    (round(1 / 3, 6), "1/3 - Kurang penting"),
    (0.2, "1/5 - Jelas kurang penting"),
    (round(1 / 7, 6), "1/7 - Sangat kurang penting"),
    (round(1 / 9, 6), "1/9 - Mutlak kurang penting"),
]


def _standardize_station(name: str) -> str:
    text = str(name).upper()
    if "DKI1" in text:
        return "DKI1 Bundaran Hotel Indonesia (HI)"
    if "DKI2" in text:
        return "DKI2 Kelapa Gading"
    if "DKI3" in text:
        return "DKI3 Jagakarsa"
    if "DKI4" in text:
        return "DKI4 Lubang Buaya"
    if "DKI5" in text:
        return "DKI5 Kebon Jeruk Jakarta Barat"
    return str(name).strip()


def load_alternatives_from_csv(csv_source, period: str = "2025_jun_nov") -> list[dict]:
    df = pd.read_csv(csv_source).drop_duplicates()

    if "periode_data" in df.columns:
        if period == "2025_jun_nov":
            df = df[df["periode_data"].astype(str).str.startswith("2025")].copy()
            if "bulan" in df.columns:
                df = df[df["bulan"].between(6, 11)].copy()
        elif period == "2025_all":
            df = df[df["periode_data"].astype(str).str.startswith("2025")].copy()
        elif period == "2024_all":
            df = df[df["periode_data"].astype(str).str.startswith("2024")].copy()

    if "stasiun" not in df.columns:
        raise ValueError("Kolom 'stasiun' tidak ditemukan di dalam file CSV.")

    df["Wilayah"] = df["stasiun"].apply(_standardize_station)

    for col in CSV_COLS:
        if col not in df.columns:
            raise ValueError(f"Kolom kriteria '{col}' tidak ditemukan di dalam file CSV.")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "bulan" in df.columns:
        monthly_mean = df.groupby(["Wilayah", "bulan"])[CSV_COLS].mean()
        decision_df = monthly_mean.groupby("Wilayah").mean().round(2)
    else:
        decision_df = df.groupby("Wilayah")[CSV_COLS].mean().round(2)

    decision_df.columns = CRITERIA
    decision_df = decision_df.dropna(how="all").fillna(0.0)

    records = []
    for wilayah, row in decision_df.iterrows():
        item = {"wilayah": str(wilayah)}
        for c in CRITERIA:
            item[c] = round(float(row[c]), 2)
        records.append(item)
    return records


def calculate_ahp(pairwise_matrix: list[list[float]]) -> dict:
    A = np.array(pairwise_matrix, dtype=float)
    n = len(CRITERIA)

    col_sums = A.sum(axis=0)
    norm_matrix = A / col_sums
    weights = norm_matrix.mean(axis=1)

    weighted_sum = A @ weights
    consistency_vector = weighted_sum / weights
    lambda_max = float(consistency_vector.mean())
    ci = float((lambda_max - n) / (n - 1))
    ri = 1.24
    cr = float(ci / ri)

    weights_table = [
        {
            "kriteria": CRITERIA[i],
            "bobot": round(float(weights[i]), 6),
            "persen": round(float(weights[i]) * 100, 2),
        }
        for i in range(n)
    ]

    return {
        "weights": weights,
        "weights_table": weights_table,
        "col_sums": np.round(col_sums, 4).tolist(),
        "norm_matrix": np.round(norm_matrix, 4).tolist(),
        "lambda_max": round(lambda_max, 6),
        "ci": round(ci, 6),
        "ri": ri,
        "cr": round(cr, 6),
        "is_consistent": cr <= 0.10,
    }


def _generate_intervention_advice(dominant_pollutants: list[str]) -> str:
    actions = []
    if any(p in dominant_pollutants for p in ["PM2.5", "PM10"]):
        actions.append(
            "Perketat uji emisi kendaraan berat, lakukan penyiraman jalan protokol untuk menekan debu tersuspensi, dan awasi pembakaran terbuka."
        )
    if any(p in dominant_pollutants for p in ["NO2", "O3"]):
        actions.append(
            "Terapkan rekayasa lalu lintas pada jam sibuk serta dorong peralihan ke transportasi publik untuk menekan gas prekursor ozon."
        )
    if any(p in dominant_pollutants for p in ["SO2", "CO"]):
        actions.append(
            "Lakukan inspeksi emisi cerobong industri dan genset komersial serta perkuat ruang terbuka hijau penyangga."
        )
    return " ".join(actions)


def calculate_saw_decision(alternatives: list[dict], weights: np.ndarray) -> dict:
    df = pd.DataFrame(alternatives).set_index("wilayah")[CRITERIA]
    max_vals = df.max(axis=0).replace(0, 1.0)
    norm_df = df / max_vals
    weighted_df = norm_df * weights
    scores = weighted_df.sum(axis=1)

    ranking_records = []
    sorted_wilayah = scores.sort_values(ascending=False).index.tolist()

    for idx, wilayah in enumerate(sorted_wilayah):
        rank = idx + 1
        v_score = round(float(scores.loc[wilayah]), 6)
        w_row = weighted_df.loc[wilayah]
        r_row = norm_df.loc[wilayah]

        top_weighted = w_row.sort_values(ascending=False).index[:2].tolist()
        peak_norm = [c for c in CRITERIA if r_row[c] >= 0.85 and c not in top_weighted]
        key_pollutants = (top_weighted + peak_norm)[:3]

        if rank == 1:
            priority_label = "Prioritas Utama"
        elif rank <= 3:
            priority_label = "Prioritas Tinggi"
        else:
            priority_label = "Prioritas Menengah"

        ranking_records.append(
            {
                "ranking": rank,
                "wilayah": wilayah,
                "nilai_v": v_score,
                "priority_label": priority_label,
                "key_pollutants": key_pollutants,
                "advice": _generate_intervention_advice(key_pollutants),
                "contributions": [round(float(w_row[c]), 4) for c in CRITERIA],
            }
        )

    return {
        "decision_df": df.round(2),
        "norm_df": norm_df.round(4),
        "weighted_df": weighted_df.round(4),
        "max_vals": max_vals.round(2).to_dict(),
        "ranking": ranking_records,
    }