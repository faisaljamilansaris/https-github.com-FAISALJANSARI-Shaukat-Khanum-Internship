"""
L3 body composition analysis (Stage 1 baseline).

CT (DICOM folder or NIfTI) -> find L3 -> segment psoas L/R, muscle, SAT, VAT, IMAT
-> areas, psoas diameters, SMI, PMI, SAT/VAT index, HU, low psoas density flag
-> results.csv + l3_overlay.png + l3_labels.nii.gz

Models used (baseline, not yet fine-tuned):
  - TotalSegmentator v2: L3 vertebra + left/right iliopsoas
  - Comp2Comp muscle/fat nnU-Net (Task927_FatMuscle): muscle, SAT, VAT, IMAT

Usage:
  python l3_analysis.py -i /path/to/dicom_folder -o ~/l3_results/patient1 --height 1.70
  (height in metres or cm; if omitted it is read from DICOM tag 0010,1020)
"""
import argparse
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")

MUSCLE_HU = (-29, 150)
FAT_HU = (-190, -30)
PSOAS_HU_CUTOFF = 26.85
# L3_MODEL lets Docker (or any other install) point to the muscle/fat model without Comp2Comp in ~
DEFAULT_MODEL = os.environ.get("L3_MODEL") or os.path.expanduser(
    "~/Comp2Comp/models/.totalsegmentator/nnunet/results/nnUNet/2d/"
    "Task927_FatMuscle/nnUNetTrainerV2__nnUNetPlansv2.1"
)
# Comp2Comp label values
C2C_SAT, C2C_VAT, C2C_IMAT, C2C_MUSCLE = 1, 2, 3, 4
# Output label map values (requirements doc AI-02)
OUT_LABELS = {"SAT": 1, "VAT": 2, "IMAT": 3, "other_muscle": 4, "psoas_right": 5, "psoas_left": 6}


# ----------------------------------------------------------------------------
# 1. Load CT
# ----------------------------------------------------------------------------
def find_ct_series(folder):
    """Walk folder, return (file list, first file) of the largest CT series."""
    import SimpleITK as sitk
    import pydicom

    best = None
    for root, _, files in os.walk(folder):
        if not files:
            continue
        reader = sitk.ImageSeriesReader()
        try:
            sids = reader.GetGDCMSeriesIDs(root)
        except Exception:
            continue
        for sid in sids or []:
            names = reader.GetGDCMSeriesFileNames(root, sid)
            if not names:
                continue
            try:
                ds = pydicom.dcmread(names[0], stop_before_pixels=True)
                modality = str(getattr(ds, "Modality", ""))
            except Exception:
                modality = ""
            if modality and modality != "CT":
                continue  # skip PET etc.
            if best is None or len(names) > len(best):
                best = list(names)
    if best is None:
        sys.exit(f"ERROR: no CT DICOM series found in {folder}")
    return best


def read_dicom_info(path):
    import pydicom

    ds = pydicom.dcmread(path, stop_before_pixels=True)

    def get(tag, default=""):
        v = getattr(ds, tag, default)
        return str(v) if v is not None else default

    height = None
    try:
        h = float(getattr(ds, "PatientSize", 0) or 0)
        if h > 0:
            height = h
    except Exception:
        pass
    return {
        "patient_id": get("PatientID"),
        "sex": get("PatientSex"),
        "age": get("PatientAge"),
        "study_date": get("StudyDate"),
        "series_uid": get("SeriesInstanceUID"),
        "slice_thickness_mm": get("SliceThickness"),
        "contrast_agent": get("ContrastBolusAgent"),
        "dicom_height_m": height,
    }


def load_ct(input_path, work_dir):
    """Return path of a NIfTI CT in canonical (RAS) orientation, plus DICOM info."""
    import nibabel as nib
    import SimpleITK as sitk

    info = {}
    raw = os.path.join(work_dir, "ct_raw.nii.gz")
    if os.path.isdir(input_path):
        names = find_ct_series(input_path)
        print(f"Found CT series with {len(names)} slices")
        info = read_dicom_info(names[0])
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(names)
        img = reader.Execute()  # rescale slope/intercept applied -> HU
        sitk.WriteImage(img, raw)
    elif input_path.endswith((".nii", ".nii.gz")):
        raw = input_path
    else:
        sys.exit("ERROR: input must be a DICOM folder or a .nii/.nii.gz file")

    canon = nib.as_closest_canonical(nib.load(raw))
    data = np.asarray(canon.dataobj).astype(np.float32)
    if data.ndim == 4 and data.shape[3] == 1:
        data = data[..., 0]
    if data.ndim != 3 or min(data.shape) < 20:
        sys.exit(f"ERROR: the CT has shape {data.shape} - only {data.shape[2] if data.ndim >= 3 else 1} slice(s). "
                 "Give the whole CT series (a folder with all slices), not a single DICOM file.")
    canon = nib.Nifti1Image(data, canon.affine)
    ct_path = os.path.join(work_dir, "ct.nii.gz")
    nib.save(canon, ct_path)
    return ct_path, info


# ----------------------------------------------------------------------------
# 2. L3 + psoas with TotalSegmentator
# ----------------------------------------------------------------------------
def run_totalsegmentator(ct_path, ts_dir, fast=False):
    from totalsegmentatorv2.python_api import totalsegmentator

    rois = ["vertebrae_L3", "iliopsoas_left", "iliopsoas_right"]
    if all(os.path.exists(os.path.join(ts_dir, r + ".nii.gz")) for r in rois):
        print("TotalSegmentator masks already exist, reusing them")
        return
    print("Running TotalSegmentator (L3 + psoas). On CPU this can take 10-30 min...")
    totalsegmentator(ct_path, ts_dir, roi_subset=rois, fast=fast, device="gpu")


def load_mask(path, ref):
    import nibabel as nib

    m = nib.as_closest_canonical(nib.load(path))
    arr = np.asarray(m.dataobj) > 0
    if arr.shape != ref.shape:
        sys.exit(f"ERROR: mask {path} shape {arr.shape} != CT shape {ref.shape}")
    return arr


def l3_slice_index(l3_mask):
    zs = np.where(l3_mask.any(axis=(0, 1)))[0]
    if len(zs) == 0:
        sys.exit("ERROR: L3 vertebra not found in this scan (scan may not cover L3)")
    coords = np.argwhere(l3_mask)
    z = int(round(coords[:, 2].mean()))  # centre of mass = mid-L3
    x = int(round(coords[:, 0].mean()))
    return z, x, int(zs.min()), int(zs.max())


# ----------------------------------------------------------------------------
# 3. Muscle / fat with Comp2Comp model
# ----------------------------------------------------------------------------
def run_muscle_fat(ct_img, z, work_dir, model_dir):
    import nibabel as nib
    from nnunet.inference import predict

    nz = ct_img.shape[2]
    z0, z1 = max(0, z - 2), min(nz, z + 3)
    slab = ct_img.slicer[:, :, z0:z1]
    slab_path = os.path.join(work_dir, "l3_slab.nii.gz")
    pred_path = os.path.join(work_dir, "l3_slab_musclefat.nii.gz")
    nib.save(slab, slab_path)
    if not os.path.exists(model_dir):
        sys.exit(f"ERROR: Comp2Comp muscle/fat model not found at {model_dir}\n"
                 "Run Comp2Comp once (bin/C2C spine_muscle_adipose_tissue ...) so it downloads.")
    print("Running Comp2Comp muscle/fat model on the L3 slab...")
    predict.predict_cases(
        model=model_dir, list_of_lists=[[slab_path]], output_filenames=[pred_path],
        folds="all", save_npz=False, num_threads_preprocessing=2, num_threads_nifti_save=2,
        segs_from_prev_stage=None, do_tta=False, mixed_precision=False,
        overwrite_existing=True, all_in_gpu=False, step_size=0.5,
        checkpoint_name="model_final_checkpoint", segmentation_export_kwargs=None)
    pred = np.round(np.asarray(nib.load(pred_path).dataobj)).astype(np.int16)
    return pred[:, :, z - z0]


# ----------------------------------------------------------------------------
# 4. Measurements
# ----------------------------------------------------------------------------
def largest_component(mask2d):
    from scipy import ndimage

    lab, n = ndimage.label(mask2d)
    if n <= 1:
        return mask2d
    sizes = ndimage.sum(mask2d, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


def psoas_diameters(mask2d, sx, sy):
    """Longest diameter and longest chord perpendicular to it (mm).
    Returns (major_mm, minor_mm, major_line, minor_line) with lines as voxel (i, j) endpoints."""
    pts = np.argwhere(mask2d)
    if len(pts) < 3:
        return 0.0, 0.0, None, None
    mm = pts * np.array([sx, sy])
    # longest diameter (max Feret) using convex hull
    try:
        from scipy.spatial import ConvexHull
        hull = mm[ConvexHull(mm).vertices]
    except Exception:
        hull = mm
    d = np.linalg.norm(hull[:, None, :] - hull[None, :, :], axis=-1)
    a, b = np.unravel_index(np.argmax(d), d.shape)
    p1, p2 = hull[a], hull[b]
    u = (p2 - p1) / (np.linalg.norm(p2 - p1) + 1e-9)
    v = np.array([-u[1], u[0]])
    pix = (sx + sy) / 2
    major = float(np.linalg.norm(p2 - p1)) + pix
    # longest perpendicular chord: bin points along u, measure extent along v
    tu, tv = mm @ u, mm @ v
    bins = np.floor((tu - tu.min()) / pix).astype(int)
    best, best_line = 0.0, None
    for bidx in np.unique(bins):
        sel = bins == bidx
        w = tv[sel].max() - tv[sel].min()
        if w > best:
            t = tu[sel].mean()
            best = w
            best_line = (t * u + tv[sel].min() * v, t * u + tv[sel].max() * v)
    minor = float(best) + pix
    scale = np.array([sx, sy])
    major_line = (p1 / scale, p2 / scale)
    minor_line = (best_line[0] / scale, best_line[1] / scale) if best_line else None
    return major, minor, major_line, minor_line


def hu_stats(hu, mask):
    vals = hu[mask]
    if vals.size == 0:
        return np.nan, np.nan
    return float(vals.mean()), float(vals.std())


# ----------------------------------------------------------------------------
# 5. Picture
# ----------------------------------------------------------------------------
def to_display(a):
    """Canonical (RAS) slice -> radiological view (anterior up, patient right on screen left)."""
    return np.flip(np.flip(a, 0), 1).T


def make_figure(out_png, hu2d, labels2d, sag, sag_l3, sx, sy, sz, z, res, lines):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    ni, nj = hu2d.shape
    colors = ["#f4a460", "#7fbf7f", "#9370db", "#f08080", "#00e5ff", "#ffeb3b"]  # SAT VAT IMAT muscle psoasR psoasL
    cmap = ListedColormap(colors)
    lab_disp = to_display(labels2d)

    fig = plt.figure(figsize=(16, 7.5))
    ax1 = fig.add_axes([0.0, 0.05, 0.42, 0.9])
    ax2 = fig.add_axes([0.43, 0.05, 0.17, 0.9])
    ax3 = fig.add_axes([0.62, 0.05, 0.37, 0.9])

    ax1.imshow(to_display(np.clip(hu2d, -200, 300)), cmap="gray", aspect=sy / sx)
    ax1.imshow(np.ma.masked_where(lab_disp == 0, lab_disp), cmap=cmap, vmin=1, vmax=6,
               alpha=0.5, interpolation="nearest", aspect=sy / sx)
    for (p, q), col in lines:
        if p is None:
            continue
        xs = [ni - 1 - p[0], ni - 1 - q[0]]
        ys = [nj - 1 - p[1], nj - 1 - q[1]]
        ax1.plot(xs, ys, color=col, lw=1.5)
    ax1.set_title(f"L3 axial slice (index {z})   R = patient right", fontsize=10)
    ax1.axis("off")

    # sagittal with L3 line
    sag_disp = np.flip(np.flip(sag, 0), 1).T
    l3_disp = np.flip(np.flip(sag_l3, 0), 1).T
    nk = sag.shape[1]
    ax2.imshow(np.clip(sag_disp, -200, 500), cmap="gray", aspect=sz / sy)
    ax2.imshow(np.ma.masked_where(~l3_disp, l3_disp), cmap=ListedColormap(["#ffeb3b"]),
               alpha=0.5, aspect=sz / sy)
    ax2.axhline(nk - 1 - z, color="red", lw=1)
    ax2.set_title("Sagittal: L3 (yellow), slice (red)", fontsize=9)
    ax2.axis("off")

    ax3.axis("off")
    txt = [
        ("Legend", ""),
        ("  red = other muscle, cyan = R psoas, yellow = L psoas", ""),
        ("  orange = SAT, green = VAT, purple = IMAT", ""),
        ("", ""),
    ]
    order = [
        ("Height (m)", "height_m"), ("", None),
        ("Total skeletal muscle area (cm2)", "SMA_cm2"), ("SMI (cm2/m2)", "SMI"),
        ("Total muscle HU mean", "muscle_HU_mean"), ("", None),
        ("R psoas area (cm2)", "psoas_R_area_cm2"), ("L psoas area (cm2)", "psoas_L_area_cm2"),
        ("R psoas A x B (mm)", "psoas_R_AxB"), ("L psoas C x D (mm)", "psoas_L_CxD"),
        ("PMI diameters (A*B+C*D)/h2", "PMI_diam"), ("PMI area (areaR+areaL)/h2", "PMI_area"),
        ("R psoas HU mean", "psoas_R_HU_mean"), ("L psoas HU mean", "psoas_L_HU_mean"),
        ("Low psoas density flag", "low_psoas_density"), ("", None),
        ("SAT area (cm2) / SATI", "SAT_line"), ("VAT area (cm2) / VATI", "VAT_line"),
        ("IMAT area (cm2)", "IMAT_cm2"),
    ]
    y = 0.98
    for a, _ in txt:
        ax3.text(0, y, a, fontsize=10, family="monospace", transform=ax3.transAxes)
        y -= 0.04
    for label, key in order:
        if key is None:
            y -= 0.02
            continue
        val = res.get(key, "")
        if isinstance(val, float):
            val = "" if np.isnan(val) else f"{val:.2f}"
        ax3.text(0, y, f"{label:<34} {val}", fontsize=10, family="monospace", transform=ax3.transAxes)
        y -= 0.045
    ax3.text(0, 0.0, "Baseline models (TotalSegmentator + Comp2Comp). Research use only.",
             fontsize=8, color="gray", transform=ax3.transAxes)
    fig.savefig(out_png, dpi=100, facecolor="white")
    plt.close(fig)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="L3 body composition (baseline)")
    ap.add_argument("-i", "--input", required=True, help="DICOM folder or NIfTI file")
    ap.add_argument("-o", "--out", required=True, help="output folder")
    ap.add_argument("--height", type=float, default=None, help="height in m (or cm)")
    ap.add_argument("--fast", action="store_true", help="TotalSegmentator fast mode (3 mm, less accurate)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="Comp2Comp muscle/fat nnU-Net folder")
    ap.add_argument("--psoas-hu-cutoff", type=float, default=PSOAS_HU_CUTOFF)
    ap.add_argument("--summary-csv", default=None, help="also append the result row to this CSV")
    args = ap.parse_args()

    import nibabel as nib
    import pandas as pd

    out = os.path.abspath(os.path.expanduser(args.out))
    os.makedirs(out, exist_ok=True)
    work = os.path.join(out, "work")
    os.makedirs(work, exist_ok=True)

    # 1. load
    ct_path, info = load_ct(os.path.expanduser(args.input), work)
    ct_img = nib.load(ct_path)
    hu = np.asarray(ct_img.dataobj).astype(np.float32)
    sx, sy, sz = [float(v) for v in ct_img.header.get_zooms()[:3]]
    print(f"CT shape {hu.shape}, spacing {sx:.3f} x {sy:.3f} x {sz:.3f} mm")
    if sz > 5.0:
        print(f"WARNING: slice thickness {sz:.1f} mm is above 5 mm")

    # height
    height = args.height if args.height else info.get("dicom_height_m")
    if height and height > 3:
        height = height / 100.0  # given in cm
    if not height:
        print("WARNING: height unknown -> indices (SMI, PMI, SATI, VATI) left blank. Use --height.")

    # 2. L3 + psoas
    ts_dir = os.path.join(work, "totalseg")
    run_totalsegmentator(ct_path, ts_dir, fast=args.fast)
    l3 = load_mask(os.path.join(ts_dir, "vertebrae_L3.nii.gz"), hu)
    psoas_l3d = load_mask(os.path.join(ts_dir, "iliopsoas_left.nii.gz"), hu)
    psoas_r3d = load_mask(os.path.join(ts_dir, "iliopsoas_right.nii.gz"), hu)
    z, x_mid, z_lo, z_hi = l3_slice_index(l3)
    print(f"L3 found: slices {z_lo}-{z_hi}, using mid-L3 slice {z}")

    # 3. muscle / fat
    mf = run_muscle_fat(ct_img, z, work, os.path.expanduser(args.model))
    hu2d = hu[:, :, z]
    in_muscle_hu = (hu2d >= MUSCLE_HU[0]) & (hu2d <= MUSCLE_HU[1])
    in_fat_hu = (hu2d >= FAT_HU[0]) & (hu2d <= FAT_HU[1])

    psoas_r = largest_component(psoas_r3d[:, :, z]) & in_muscle_hu
    psoas_l = largest_component(psoas_l3d[:, :, z]) & in_muscle_hu
    muscle_c2c = (mf == C2C_MUSCLE) & in_muscle_hu
    total_muscle = muscle_c2c | psoas_r | psoas_l
    other_muscle = total_muscle & ~psoas_r & ~psoas_l
    sat = (mf == C2C_SAT) & in_fat_hu
    vat = (mf == C2C_VAT) & in_fat_hu
    imat = (mf == C2C_IMAT) & in_fat_hu

    px_cm2 = sx * sy / 100.0
    area = lambda m: float(m.sum() * px_cm2)

    A, B, rmaj, rmin = psoas_diameters(psoas_r, sx, sy)
    C, D, lmaj, lmin = psoas_diameters(psoas_l, sx, sy)
    pr_mean, pr_sd = hu_stats(hu2d, psoas_r)
    pl_mean, pl_sd = hu_stats(hu2d, psoas_l)
    m_mean, m_sd = hu_stats(hu2d, total_muscle)

    h2 = height ** 2 if height else np.nan
    res = {
        "patient_id": info.get("patient_id", ""),
        "input": os.path.abspath(os.path.expanduser(args.input)),
        "sex": info.get("sex", ""), "age": info.get("age", ""),
        "study_date": info.get("study_date", ""),
        "series_uid": info.get("series_uid", ""),
        "contrast_agent": info.get("contrast_agent", ""),
        "height_m": float(height) if height else np.nan,
        "height_source": "user" if args.height else ("dicom" if height else "missing"),
        "pixel_spacing_mm": f"{sx:.3f}x{sy:.3f}", "slice_thickness_mm": round(sz, 2),
        "L3_slice_index": z, "L3_slice_range": f"{z_lo}-{z_hi}",
        "SMA_cm2": area(total_muscle),
        "SMI": area(total_muscle) / h2,
        "muscle_HU_mean": m_mean, "muscle_HU_sd": m_sd,
        "psoas_R_area_cm2": area(psoas_r), "psoas_L_area_cm2": area(psoas_l),
        "psoas_total_area_cm2": area(psoas_r) + area(psoas_l),
        "psoas_R_A_mm": A, "psoas_R_B_mm": B, "psoas_L_C_mm": C, "psoas_L_D_mm": D,
        "PMI_diam": (A / 10 * B / 10 + C / 10 * D / 10) / h2,
        "PMI_area": (area(psoas_r) + area(psoas_l)) / h2,
        "psoas_R_HU_mean": pr_mean, "psoas_R_HU_sd": pr_sd,
        "psoas_L_HU_mean": pl_mean, "psoas_L_HU_sd": pl_sd,
        "low_psoas_density": bool(pl_mean <= args.psoas_hu_cutoff) if not np.isnan(pl_mean) else "",
        "psoas_HU_cutoff": args.psoas_hu_cutoff,
        "SAT_cm2": area(sat), "SATI": area(sat) / h2,
        "VAT_cm2": area(vat), "VATI": area(vat) / h2,
        "IMAT_cm2": area(imat),
        "models": "TotalSegmentatorV2(L3,iliopsoas) + Comp2Comp Task927_FatMuscle",
        "masks": "AI-only",
    }
    for k, v in list(res.items()):
        if isinstance(v, float):
            res[k] = round(v, 2)

    # outputs
    pd.DataFrame([res]).to_csv(os.path.join(out, "results.csv"), index=False)
    if args.summary_csv:
        sp = os.path.expanduser(args.summary_csv)
        pd.DataFrame([res]).to_csv(sp, mode="a", index=False, header=not os.path.exists(sp))

    labels = np.zeros(hu2d.shape, np.uint8)
    labels[sat] = OUT_LABELS["SAT"]
    labels[vat] = OUT_LABELS["VAT"]
    labels[imat] = OUT_LABELS["IMAT"]
    labels[other_muscle] = OUT_LABELS["other_muscle"]
    labels[psoas_r] = OUT_LABELS["psoas_right"]
    labels[psoas_l] = OUT_LABELS["psoas_left"]
    lab_img = nib.Nifti1Image(labels[:, :, None], ct_img.slicer[:, :, z:z + 1].affine)
    nib.save(lab_img, os.path.join(out, "l3_labels.nii.gz"))
    nib.save(ct_img.slicer[:, :, z:z + 1], os.path.join(out, "l3_ct.nii.gz"))

    fig_res = dict(res)
    fig_res["psoas_R_AxB"] = f"{A:.1f} x {B:.1f}"
    fig_res["psoas_L_CxD"] = f"{C:.1f} x {D:.1f}"
    fig_res["SAT_line"] = f"{res['SAT_cm2']:.1f} / " + ("" if not height else f"{res['SATI']:.2f}")
    fig_res["VAT_line"] = f"{res['VAT_cm2']:.1f} / " + ("" if not height else f"{res['VATI']:.2f}")
    lines = [((rmaj or (None, None)), "#00e5ff"), ((rmin or (None, None)), "#00e5ff"),
             ((lmaj or (None, None)), "#ffeb3b"), ((lmin or (None, None)), "#ffeb3b")]
    make_figure(os.path.join(out, "l3_overlay.png"), hu2d, labels,
                hu[x_mid, :, :], l3[x_mid, :, :], sx, sy, sz, z, fig_res, lines)

    print("\n===== L3 RESULTS =====")
    for k in ["height_m", "L3_slice_index", "SMA_cm2", "SMI", "muscle_HU_mean",
              "psoas_R_area_cm2", "psoas_L_area_cm2", "psoas_R_A_mm", "psoas_R_B_mm",
              "psoas_L_C_mm", "psoas_L_D_mm", "PMI_diam", "PMI_area",
              "psoas_R_HU_mean", "psoas_L_HU_mean", "low_psoas_density",
              "SAT_cm2", "SATI", "VAT_cm2", "VATI", "IMAT_cm2"]:
        print(f"{k:<20}: {res[k]}")
    print(f"\nSaved to {out}: results.csv, l3_overlay.png, l3_labels.nii.gz, l3_ct.nii.gz")


if __name__ == "__main__":
    main()
