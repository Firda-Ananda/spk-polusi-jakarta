import os
from flask import Flask, redirect, render_template, request, session, url_for
from spk_engine import (
    CRITERIA,
    DEFAULT_PAIRWISE_MATRIX,
    SAATY_SCALE_OPTIONS,
    calculate_ahp,
    calculate_saw_decision,
    load_alternatives_from_csv,
)

app = Flask(__name__)
app.secret_key = "spk-polusi-dki-jakarta-ahp-saw-2026"

DEFAULT_CSV = os.path.join(
    "data",
    "data-indeks-standar-pencemar-udara-(ispu)-di-provinsi-dki-jakarta-komponen-data.csv",
)

PERIOD_LABELS = {
    "2025_jun_nov": "Juni – November 2025",
    "2025_all": "Januari – November 2025",
    "2024_all": "Januari – Desember 2024",
    "all": "Gabungan 2024 – 2025",
}


def _get_state():
    if "alternatives" not in session:
        session["alternatives"] = load_alternatives_from_csv(DEFAULT_CSV, "2025_jun_nov")
        session["period_label"] = PERIOD_LABELS["2025_jun_nov"]
        session["source_type"] = "Dataset Satu Data Jakarta"
        session["active_period"] = "2025_jun_nov"
    if "pairwise_matrix" not in session:
        session["pairwise_matrix"] = [row[:] for row in DEFAULT_PAIRWISE_MATRIX]

    alternatives = session["alternatives"]
    matrix = session["pairwise_matrix"]
    ahp = calculate_ahp(matrix)
    saw = calculate_saw_decision(alternatives, ahp["weights"])

    return {
        "criteria": CRITERIA,
        "alternatives": alternatives,
        "matrix": matrix,
        "ahp": ahp,
        "saw": saw,
        "period_label": session.get("period_label", PERIOD_LABELS["2025_jun_nov"]),
        "source_type": session.get("source_type", "Dataset Satu Data Jakarta"),
        "active_period": session.get("active_period", "2025_jun_nov"),
    }


@app.route("/")
def dashboard():
    ctx = _get_state()
    return render_template("dashboard.html", active_page="dashboard", **ctx)


@app.route("/data", methods=["GET", "POST"])
def data_wilayah():
    _get_state()
    message = None
    error_msg = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "load_default":
            period = request.form.get("period", "2025_jun_nov")
            session["alternatives"] = load_alternatives_from_csv(DEFAULT_CSV, period)
            session["period_label"] = PERIOD_LABELS.get(period, PERIOD_LABELS["2025_jun_nov"])
            session["source_type"] = "Dataset Satu Data Jakarta"
            session["active_period"] = period
            message = f"Data wilayah berhasil dimuat untuk periode {session['period_label']}."

        elif action == "upload_csv":
            uploaded = request.files.get("csv_file")
            if uploaded and uploaded.filename.endswith(".csv"):
                try:
                    alts = load_alternatives_from_csv(uploaded, period="all")
                    if len(alts) < 2:
                        raise ValueError("File CSV minimal harus memuat 2 wilayah pemantauan.")
                    session["alternatives"] = alts
                    session["period_label"] = "Sesuai File CSV"
                    session["source_type"] = uploaded.filename
                    session["active_period"] = "custom_csv"
                    message = f"Berhasil memuat {len(alts)} wilayah dari file {uploaded.filename}."
                except Exception as e:
                    error_msg = f"Gagal memproses file CSV: {e}"
            else:
                error_msg = "Pilih file dengan format .csv terlebih dahulu."

        elif action == "save_table":
            try:
                count = int(request.form.get("row_count", 0))
                updated = []
                for idx in range(count):
                    wilayah = request.form.get(f"wilayah_{idx}", "").strip()
                    if not wilayah:
                        continue
                    row_data = {"wilayah": wilayah}
                    for c in CRITERIA:
                        val = float(request.form.get(f"val_{idx}_{c}", 0))
                        if val < 0:
                            raise ValueError("Nilai parameter tidak boleh negatif.")
                        row_data[c] = round(val, 2)
                    updated.append(row_data)

                if len(updated) < 2:
                    raise ValueError("Minimal diperlukan 2 wilayah untuk dilakukan perangkingan.")

                session["alternatives"] = updated
                session["source_type"] = "Input Manual Pengguna"
                session["active_period"] = "manual"
                message = "Perubahan data wilayah berhasil disimpan."
            except ValueError as e:
                error_msg = f"Data tidak valid: {e}"

        elif action == "add_row":
            try:
                wilayah = request.form.get("new_wilayah", "").strip()
                if not wilayah:
                    raise ValueError("Nama stasiun atau wilayah wajib diisi.")
                new_row = {"wilayah": wilayah}
                for c in CRITERIA:
                    val = float(request.form.get(f"new_{c}", 0))
                    if val < 0:
                        raise ValueError("Nilai parameter tidak boleh negatif.")
                    new_row[c] = round(val, 2)

                alts = session["alternatives"]
                alts.append(new_row)
                session["alternatives"] = alts
                session["source_type"] = "Input Manual Pengguna"
                session["active_period"] = "manual"
                message = f"Wilayah {wilayah} berhasil ditambahkan."
            except ValueError as e:
                error_msg = f"Gagal menambah wilayah: {e}"

        elif action and action.startswith("delete_"):
            del_idx = int(action.split("_")[1])
            alts = session["alternatives"]
            if len(alts) <= 2:
                error_msg = "Minimal 2 wilayah harus dipertahankan agar perangkingan dapat berjalan."
            elif 0 <= del_idx < len(alts):
                removed = alts.pop(del_idx)
                session["alternatives"] = alts
                session["source_type"] = "Input Manual Pengguna"
                message = f"Wilayah {removed['wilayah']} telah dihapus."

    ctx = _get_state()
    return render_template(
        "data.html",
        active_page="data",
        message=message,
        error_msg=error_msg,
        **ctx,
    )


@app.route("/ahp", methods=["GET", "POST"])
def pembobotan_ahp():
    _get_state()
    message = None
    error_msg = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "reset_ahp":
            session["pairwise_matrix"] = [row[:] for row in DEFAULT_PAIRWISE_MATRIX]
            message = "Matriks perbandingan dikembalikan ke nilai acuan penelitian."
        elif action == "update_ahp":
            try:
                n = len(CRITERIA)
                new_matrix = [[1.0] * n for _ in range(n)]
                for i in range(n):
                    for j in range(i + 1, n):
                        val = float(request.form.get(f"cell_{i}_{j}", 1.0))
                        if val <= 0:
                            raise ValueError("Nilai skala perbandingan harus lebih besar dari 0.")
                        new_matrix[i][j] = val
                        new_matrix[j][i] = round(1.0 / val, 6)

                session["pairwise_matrix"] = new_matrix
                check = calculate_ahp(new_matrix)
                if check["is_consistent"]:
                    message = f"Bobot kriteria berhasil diperbarui dan dinyatakan konsisten (CR = {check['cr']})."
                else:
                    error_msg = (
                        f"Penilaian belum konsisten (CR = {check['cr']}, batas maksimum 0,10). "
                        "Silakan sesuaikan kembali nilai perbandingan."
                    )
            except ValueError as e:
                error_msg = f"Input perbandingan tidak valid: {e}"

    ctx = _get_state()
    return render_template(
        "ahp.html",
        active_page="ahp",
        saaty_options=SAATY_SCALE_OPTIONS,
        message=message,
        error_msg=error_msg,
        **ctx,
    )


@app.route("/keputusan")
def hasil_keputusan():
    ctx = _get_state()
    return render_template("keputusan.html", active_page="keputusan", **ctx)


@app.route("/perhitungan")
def detail_perhitungan():
    ctx = _get_state()
    return render_template("perhitungan.html", active_page="perhitungan", **ctx)


if __name__ == "__main__":
    app.run(debug=True)