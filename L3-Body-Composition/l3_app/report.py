"""
Colour L3 report: one image (PNG) + the same page as PDF.

Reads what l3_analysis.py saved in the output folder:
  results.csv, l3_ct.nii.gz, l3_labels.nii.gz, work/ct.nii.gz, work/totalseg/vertebrae_L3.nii.gz
and writes:
  report.png, report.pdf, evaluation.json (the same rows the web page shows)

Cut-offs are in CUTOFFS below. They are literature references, not a diagnosis
(requirements RG-05); change them when sir decides which ones to use.

Run on its own:  python report.py ~/l3_results/PANCREAS_0001 [--sex M] [--weight 70]
"""
import argparse
import importlib.util
import json
import os

import numpy as np

# ----------------------------------------------------------------------------
# Settings you may want to change
# ----------------------------------------------------------------------------
L3_SCRIPT = os.environ.get("L3_SCRIPT", os.path.expanduser("~/l3_analysis.py"))

# label value -> (name, colour); same values and colours as l3_analysis.py
LABELS = {
    1: ("SAT", "#f4a460"),
    2: ("VAT", "#7fbf7f"),
    3: ("IMAT", "#9370db"),
    4: ("Other muscle", "#f08080"),
    5: ("Right psoas", "#00e5ff"),
    6: ("Left psoas", "#ffeb3b"),
}

CUTOFFS = {
    # SMI below this = low muscle mass (Prado et al., Lancet Oncol 2008)
    "SMI": {"M": 52.4, "F": 38.5, "source": "Prado 2008"},
    # PMI (area) below this = low psoas mass (Hamaguchi et al., Nutrition 2016)
    "PMI_area": {"M": 6.36, "F": 3.92, "source": "Hamaguchi 2016"},
    # mean muscle HU below this = low muscle density (Martin et al., J Clin Oncol 2013)
    "muscle_HU": {"bmi_lt25": 41.0, "bmi_ge25": 33.0, "source": "Martin 2013"},
    # left psoas mean HU at or below this = low psoas density (requirements FR-16)
    "psoas_L_HU": {"value": 26.85, "source": "PMID 40308059 (mCRPC)"},
    # VAT area at or above this = high visceral fat
    "VAT_cm2": {"value": 100.0, "source": "visceral obesity, VAT >= 100 cm2"},
}

STATUS_STYLE = {  # status -> (chip text colour, chip background)
    "LOW": ("white", "#d9534f"),
    "HIGH": ("white", "#d9534f"),
    "NORMAL": ("white", "#3a9a5b"),
    "NEEDS SEX": ("#333333", "#e0e0e0"),
    "NEEDS BMI": ("#333333", "#e0e0e0"),
    "NO HEIGHT": ("#333333", "#e0e0e0"),
}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def load_l3_module():
    """Import l3_analysis.py so the report uses exactly the same diameter code."""
    spec = importlib.util.spec_from_file_location("l3_analysis", L3_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def num(v):
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def fmt(v, d=1):
    v = num(v)
    return "—" if v is None else f"{v:.{d}f}"


def norm_sex(s):
    s = str(s or "").strip().upper()[:1]
    return s if s in ("M", "F") else ""


def evaluate(res, sex, bmi):
    """Rows for the report table: dict(group, name, value, ref, status, color)."""
    rows = []
    no_h = num(res.get("height_m")) is None

    def add(group, name, value, ref="", status="", color=None):
        rows.append(dict(group=group, name=name, value=value, ref=ref, status=status, color=color))

    def sex_cut(key, value):
        c = CUTOFFS[key]
        if no_h:
            return f"M < {c['M']}, F < {c['F']}", "NO HEIGHT"
        if not sex:
            return f"M < {c['M']}, F < {c['F']}", "NEEDS SEX"
        return f"< {c[sex]} ({sex})", ("LOW" if value < c[sex] else "NORMAL")

    # --- muscle
    add("Muscle", "Total skeletal muscle area (SMA)", f"{fmt(res['SMA_cm2'])} cm²", color=LABELS[4][1])
    smi = num(res.get("SMI"))
    ref, st = sex_cut("SMI", smi or 0)
    add("Muscle", "SMI = SMA / height²", f"{fmt(smi)} cm²/m²", ref, st)
    mhu = num(res.get("muscle_HU_mean"))
    c = CUTOFFS["muscle_HU"]
    if bmi is None:
        add("Muscle", "Muscle density (mean HU)", f"{fmt(mhu)} HU",
            f"< {c['bmi_lt25']:g} (BMI<25), < {c['bmi_ge25']:g} (≥25)", "NEEDS BMI")
    else:
        cut = c["bmi_lt25"] if bmi < 25 else c["bmi_ge25"]
        add("Muscle", "Muscle density (mean HU)", f"{fmt(mhu)} HU",
            f"< {cut:g} (BMI {bmi:.1f})", "LOW" if mhu < cut else "NORMAL")

    # --- psoas
    add("Psoas", "Right psoas area", f"{fmt(res['psoas_R_area_cm2'], 2)} cm²", color=LABELS[5][1])
    add("Psoas", "Left psoas area", f"{fmt(res['psoas_L_area_cm2'], 2)} cm²", color=LABELS[6][1])
    add("Psoas", "Right psoas A × B", f"{fmt(res['psoas_R_A_mm'])} × {fmt(res['psoas_R_B_mm'])} mm", color=LABELS[5][1])
    add("Psoas", "Left psoas C × D", f"{fmt(res['psoas_L_C_mm'])} × {fmt(res['psoas_L_D_mm'])} mm", color=LABELS[6][1])
    add("Psoas", "PMI (diameters) = (A·B + C·D) / h²", f"{fmt(res['PMI_diam'], 2)} cm²/m²", "No agreed cut-off")
    pmi = num(res.get("PMI_area"))
    ref, st = sex_cut("PMI_area", pmi or 0)
    add("Psoas", "PMI (area) = (R + L area) / h²", f"{fmt(pmi, 2)} cm²/m²", ref, st)
    add("Psoas", "Right psoas density", f"{fmt(res['psoas_R_HU_mean'])} HU")
    phu = num(res.get("psoas_L_HU_mean"))
    cut = CUTOFFS["psoas_L_HU"]["value"]
    add("Psoas", "Left psoas density", f"{fmt(phu)} HU", f"≤ {cut} HU",
        "" if phu is None else ("LOW" if phu <= cut else "NORMAL"))

    # --- fat
    add("Fat", "SAT area / SAT index", f"{fmt(res['SAT_cm2'])} cm² / {fmt(res['SATI'])}", color=LABELS[1][1])
    vat = num(res.get("VAT_cm2"))
    vcut = CUTOFFS["VAT_cm2"]["value"]
    add("Fat", "VAT area / VAT index", f"{fmt(vat)} cm² / {fmt(res['VATI'])}", f"≥ {vcut:.0f} cm²",
        "" if vat is None else ("HIGH" if vat >= vcut else "NORMAL"), color=LABELS[2][1])
    add("Fat", "IMAT area", f"{fmt(res['IMAT_cm2'], 2)} cm²", color=LABELS[3][1])
    return rows


def to_display(a):
    """Canonical (RAS) slice -> radiological view (anterior up, patient right on screen left)."""
    return np.flip(np.flip(a, 0), 1).T


def bbox(mask, margin, shape):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return 0, shape[0], 0, shape[1]
    return (max(0, ys.min() - margin), min(shape[0], ys.max() + margin + 1),
            max(0, xs.min() - margin), min(shape[1], xs.max() + margin + 1))


def body_region(hu2d):
    from scipy import ndimage
    m = ndimage.binary_fill_holes(hu2d > -400)
    lab, n = ndimage.label(m)
    if n == 0:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


# ----------------------------------------------------------------------------
# Main figure
# ----------------------------------------------------------------------------
def make_report(out_dir, sex=None, weight_kg=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import nibabel as nib
    import pandas as pd
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import FancyBboxPatch, Rectangle

    res = pd.read_csv(os.path.join(out_dir, "results.csv")).iloc[0].to_dict()
    sex = norm_sex(sex) or norm_sex(res.get("sex"))
    h = num(res.get("height_m"))
    bmi = (float(weight_kg) / h ** 2) if (weight_kg and h) else None
    rows = evaluate(res, sex, bmi)

    ct_img = nib.as_closest_canonical(nib.load(os.path.join(out_dir, "l3_ct.nii.gz")))
    lab_img = nib.as_closest_canonical(nib.load(os.path.join(out_dir, "l3_labels.nii.gz")))
    hu2d = np.asarray(ct_img.dataobj)[:, :, 0].astype(np.float32)
    labels = np.asarray(lab_img.dataobj)[:, :, 0].astype(np.int16)
    sx, sy = [float(v) for v in ct_img.header.get_zooms()[:2]]

    # psoas diameter lines, same code as l3_analysis.py
    lines = []
    try:
        l3mod = load_l3_module()
        for lab_val, col in ((5, LABELS[5][1]), (6, LABELS[6][1])):
            _, _, maj, mnr = l3mod.psoas_diameters(labels == lab_val, sx, sy)
            lines += [(maj, col), (mnr, col)]
    except Exception as e:  # report still works without the lines
        print("Diameter lines not drawn:", e)

    # ---- page
    fig = plt.figure(figsize=(18, 10.5), facecolor="white")
    fig.text(0.02, 0.965, "L3 Body Composition Report", fontsize=22, weight="bold", color="#1d2a3a")
    info = [
        ("Patient", res.get("patient_id") or "—"),
        ("Sex", sex or "—"),
        ("Age", res.get("age") if str(res.get("age", "")) not in ("", "nan") else "—"),
        ("Height", f"{h:.2f} m ({res.get('height_source')})" if h else "missing"),
        ("BMI", f"{bmi:.1f}" if bmi else "—"),
        ("Study date", res.get("study_date") if str(res.get("study_date", "")) not in ("", "nan") else "—"),
        ("Slice", f"{res.get('slice_thickness_mm')} mm, L3 index {res.get('L3_slice_index')}"),
    ]
    x = 0.02
    for k, v in info:
        fig.text(x, 0.925, k.upper(), fontsize=8.5, color="#7a8796")
        fig.text(x, 0.903, str(v), fontsize=11.5, color="#1d2a3a")
        x += 0.135 if k in ("Height", "Slice") else 0.095
    fig.add_artist(plt.Line2D([0.02, 0.98], [0.885, 0.885], color="#d5dbe2", lw=1))

    # ---- axial image (cropped to the body)
    hu_d, lab_d = to_display(hu2d), to_display(labels)
    r0, r1, c0, c1 = bbox(to_display(body_region(hu2d)), 12, hu_d.shape)
    ax1 = fig.add_axes([0.01, 0.10, 0.44, 0.76])
    ax1.set_facecolor("black")
    ax1.imshow(np.clip(hu_d[r0:r1, c0:c1], -200, 300), cmap="gray", aspect=sy / sx, interpolation="bilinear")
    cmap = ListedColormap([LABELS[i][1] for i in range(1, 7)])
    ld = lab_d[r0:r1, c0:c1]
    ax1.imshow(np.ma.masked_where(ld == 0, ld), cmap=cmap, vmin=1, vmax=6, alpha=0.5,
               interpolation="nearest", aspect=sy / sx)
    ni, nj = hu2d.shape
    for line, col in lines:
        if not line or line[0] is None:
            continue
        p, q = line
        ax1.plot([ni - 1 - p[0] - c0, ni - 1 - q[0] - c0], [nj - 1 - p[1] - r0, nj - 1 - q[1] - r0],
                 color=col, lw=2.2, solid_capstyle="round")
        ax1.plot([ni - 1 - p[0] - c0, ni - 1 - q[0] - c0], [nj - 1 - p[1] - r0, nj - 1 - q[1] - r0],
                 color="black", lw=0.6, alpha=0.6)
    ax1.text(0.02, 0.97, "R", color="white", fontsize=16, weight="bold", transform=ax1.transAxes, va="top")
    ax1.text(0.98, 0.97, "L", color="white", fontsize=16, weight="bold", transform=ax1.transAxes, va="top", ha="right")
    ax1.set_xticks([]); ax1.set_yticks([])
    ax1.set_title("Axial slice at L3 (lines = psoas diameters A/B, C/D)", fontsize=11, color="#1d2a3a", pad=6)

    # ---- sagittal with L3
    ax2 = fig.add_axes([0.46, 0.10, 0.12, 0.76])
    ax2.set_xticks([]); ax2.set_yticks([])
    try:
        vol = nib.as_closest_canonical(nib.load(os.path.join(out_dir, "work", "ct.nii.gz")))
        l3 = nib.as_closest_canonical(nib.load(os.path.join(out_dir, "work", "totalseg", "vertebrae_L3.nii.gz")))
        l3a = np.asarray(l3.dataobj) > 0
        xm = int(round(np.argwhere(l3a)[:, 0].mean()))
        sag = np.asarray(vol.dataobj[xm, :, :]).astype(np.float32)
        _, vy, vz = [float(v) for v in vol.header.get_zooms()[:3]]
        sag_d = np.flip(np.flip(sag, 0), 1).T
        l3_d = np.flip(np.flip(l3a[xm], 0), 1).T
        nk = sag.shape[1]
        z = int(res["L3_slice_index"])
        cols = np.where((sag_d > -400).any(axis=0))[0]
        cc0, cc1 = (cols.min(), cols.max() + 1) if len(cols) else (0, sag_d.shape[1])
        ax2.set_facecolor("black")
        ax2.imshow(np.clip(sag_d[:, cc0:cc1], -200, 500), cmap="gray", aspect=vz / vy)
        ax2.imshow(np.ma.masked_where(~l3_d[:, cc0:cc1], l3_d[:, cc0:cc1]),
                   cmap=ListedColormap(["#ffd400"]), alpha=0.55, aspect=vz / vy)
        ax2.axhline(nk - 1 - z, color="#ff3030", lw=1.5)
        ax2.set_title("Sagittal: L3 (yellow)\nslice used (red)", fontsize=10, color="#1d2a3a", pad=6)
    except Exception as e:
        ax2.text(0.5, 0.5, "Sagittal view\nnot available", ha="center", va="center", transform=ax2.transAxes)
        print("Sagittal not drawn:", e)

    # ---- results table
    ax3 = fig.add_axes([0.60, 0.10, 0.39, 0.77])
    ax3.axis("off")
    y, step = 0.995, 0.047
    hdr = dict(fontsize=8.5, color="#7a8796", transform=ax3.transAxes)
    ax3.text(0.04, y, "MEASUREMENT", **hdr); ax3.text(0.47, y, "VALUE", **hdr)
    ax3.text(0.69, y, "STATUS          CUT-OFF", **hdr)
    y -= 0.03
    group = None
    for r in rows:
        if r["group"] != group:
            group = r["group"]
            y -= 0.012
            ax3.text(0.0, y, group, fontsize=12, weight="bold", color="#1d2a3a", transform=ax3.transAxes, va="center")
            ax3.add_line(plt.Line2D([0.0, 1.0], [y - 0.022, y - 0.022], color="#d5dbe2", lw=0.8, transform=ax3.transAxes))
            y -= step
        if r["color"]:
            ax3.add_patch(Rectangle((0.0, y - 0.011), 0.025, 0.022, color=r["color"], transform=ax3.transAxes))
        ax3.text(0.04, y, r["name"], fontsize=10.5, color="#1d2a3a", transform=ax3.transAxes, va="center")
        ax3.text(0.47, y, r["value"], fontsize=10.5, weight="bold", color="#1d2a3a", transform=ax3.transAxes, va="center")
        if r["status"]:
            fg, bg = STATUS_STYLE.get(r["status"], ("#333", "#e0e0e0"))
            ax3.add_patch(FancyBboxPatch((0.69, y - 0.013), 0.105, 0.026, boxstyle="round,pad=0.002,rounding_size=0.008",
                                         color=bg, transform=ax3.transAxes))
            ax3.text(0.7425, y, r["status"], fontsize=8, weight="bold", color=fg, ha="center", va="center",
                     transform=ax3.transAxes)
            ax3.text(0.805, y, r["ref"], fontsize=8.3, color="#55606d", transform=ax3.transAxes, va="center")
        elif r["ref"]:
            ax3.text(0.69, y, r["ref"], fontsize=8.3, color="#55606d", transform=ax3.transAxes, va="center")
        y -= step

    # ---- footer: colour legend + notes
    lx = 0.02
    fig.text(lx, 0.055, "Colours:", fontsize=10, weight="bold", color="#1d2a3a")
    lx += 0.05
    for i in range(1, 7):
        name, col = LABELS[i]
        fig.patches.append(Rectangle((lx, 0.051), 0.012, 0.018, color=col, transform=fig.transFigure, figure=fig))
        fig.text(lx + 0.016, 0.055, name, fontsize=10, color="#1d2a3a")
        lx += 0.016 + 0.0056 * len(name) + 0.02
    src = "; ".join(f"{k}: {v['source']}" for k, v in CUTOFFS.items())
    fig.text(0.02, 0.022, f"Cut-offs are literature references, not a diagnosis ({src}). "
             "Thresholds: muscle −29 to +150 HU, fat −190 to −30 HU.", fontsize=8, color="#7a8796")
    fig.text(0.02, 0.005, f"Models: {res.get('models', '')}. Masks: {res.get('masks', '')}. Research use only.",
             fontsize=8, color="#7a8796")

    png, pdf = os.path.join(out_dir, "report.png"), os.path.join(out_dir, "report.pdf")
    fig.savefig(png, dpi=110, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    with open(os.path.join(out_dir, "evaluation.json"), "w") as f:
        json.dump({"sex": sex, "bmi": bmi, "rows": rows}, f, indent=1)
    return png, pdf, rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", help="l3_analysis.py output folder")
    ap.add_argument("--sex", default=None, help="M or F (otherwise read from results.csv)")
    ap.add_argument("--weight", type=float, default=None, help="weight in kg, for BMI-based muscle HU cut-off")
    a = ap.parse_args()
    p, d, _ = make_report(os.path.expanduser(a.out_dir), a.sex, a.weight)
    print("Saved", p, "and", d)
