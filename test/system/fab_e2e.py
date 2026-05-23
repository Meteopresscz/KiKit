#!/usr/bin/env python3
"""
End-to-end test driver for `kikit fab`.

Workflow: snapshot the fab output of a list of real projects, then merge
upstream, then re-run and compare against the snapshot. Any non-trivial
pixel diff in a rendered gerber/drill layer or any change in bom.csv /
pos.csv is reported.

Snapshot/compare are intentionally separate commands so the user controls
when the baseline is refreshed (e.g. after a deliberate kikit change or a
KiCad version bump that reformats saved boards).
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml


# File extensions worth rendering. Covers jlcpcb (.gbr + variants, .drl)
# and gatema (.top/.bot/.pth/.mill/...). gerbv autodetects content type;
# we just gate which files we even hand to it.
RENDERABLE_EXTS = {
    # jlcpcb / kicad default
    ".gbr", ".gbl", ".gtl", ".gbs", ".gts", ".gbo", ".gto",
    ".gbp", ".gtp", ".gm1", ".gko",
    ".g1", ".g2", ".g3", ".g4", ".g5", ".g6",
    ".drl",
    # gatema rename table (kikit/fab/gatema.py:23)
    ".top", ".bot", ".pth", ".mill", ".dim",
    ".in1", ".in2", ".in3", ".in4", ".in5", ".in6",
    ".smb", ".smt", ".pastebot", ".pastetop", ".plb", ".plt",
}

# Standalone CSV/TXT files written by the assembly path (kikit/fab/jlcpcb.py:197-199)
ASSEMBLY_TEXT_OUTPUTS = ("bom.csv", "pos.csv", "unassigned.txt")

RENDER_DPI = 600
PIXEL_TOLERANCE = 50  # pixels allowed to differ in a 600 dpi render


@dataclass
class Project:
    name: str
    path: Path
    cmd: str
    args: list

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"],
            path=Path(os.path.expanduser(d["path"])).resolve(),
            cmd=d["cmd"],
            args=list(d.get("args", [])),
        )


def load_config(config_path):
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return [Project.from_dict(p) for p in cfg["projects"]]


def run_fab(project, outputdir):
    """Run `kikit fab <cmd> <args> <pcb> <outputdir>`. Raises on nonzero exit."""
    cmd = ["kikit", "fab", project.cmd, *project.args, str(project.path), str(outputdir)]
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def find_gerber_zip(outputdir):
    """Find the gerber archive produced by `kikit fab`. Both jlcpcb and gatema write a single .zip."""
    zips = list(Path(outputdir).glob("*.zip"))
    if len(zips) != 1:
        raise RuntimeError(f"expected exactly one .zip in {outputdir}, found {len(zips)}: {zips}")
    return zips[0]


def render_layers(gerber_dir, png_dir):
    """Render every renderable file in gerber_dir to PNG in png_dir. Returns list of PNG paths."""
    png_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for f in sorted(gerber_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in RENDERABLE_EXTS:
            continue
        png = png_dir / (f.name + ".png")
        proc = subprocess.run(
            ["gerbv", "-x", "png", "-a", "-B", "0",
             "-D", str(RENDER_DPI),
             "-b", "#000000", "-f", "#ffffffff",
             "-o", str(png), str(f)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not png.exists() or png.stat().st_size < 200:
            print(f"  ! gerbv failed or produced empty render for {f.name}, skipping")
            if proc.stderr.strip():
                print(f"    stderr: {proc.stderr.strip()}")
            png.unlink(missing_ok=True)
            continue
        rendered.append(png)
    return rendered


def collect_assembly_text(outputdir, dest):
    """Copy bom.csv, pos.csv, unassigned.txt if present (jlcpcb assembly mode only)."""
    copied = []
    for name in ASSEMBLY_TEXT_OUTPUTS:
        # Files may have a name template prefix; match by suffix.
        matches = list(Path(outputdir).glob(f"*{name}")) + list(Path(outputdir).glob(name))
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        for m in unique:
            shutil.copy(m, dest / m.name)
            copied.append(m.name)
    return copied


def generate_artifacts(project, dest):
    """Run fab, render gerbers, collect CSVs, dump everything into `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kikit-e2e-") as tmp:
        tmp = Path(tmp)
        outputdir = tmp / "out"
        outputdir.mkdir()
        run_fab(project, outputdir)

        gerber_zip = find_gerber_zip(outputdir)
        gerber_extracted = tmp / "gerber-extracted"
        gerber_extracted.mkdir()
        with zipfile.ZipFile(gerber_zip) as zf:
            zf.extractall(gerber_extracted)
        # The zip typically contains a `gerber/` subdir. Flatten if so.
        subdirs = [p for p in gerber_extracted.iterdir() if p.is_dir()]
        if len(subdirs) == 1 and not any(p.is_file() for p in gerber_extracted.iterdir()):
            gerber_extracted = subdirs[0]

        render_layers(gerber_extracted, dest / "layers")
        collect_assembly_text(outputdir, dest)


def sorted_bytes(path):
    """Sorted line-by-line content of a text file, for CSV comparison."""
    with open(path, "rb") as f:
        return b"".join(sorted(f.readlines()))


def compare_text(snap, fresh):
    """Compare two CSV/text files by sorted lines. Returns (ok, message)."""
    if not fresh.exists():
        return False, "missing in fresh output"
    if sorted_bytes(snap) == sorted_bytes(fresh):
        return True, ""
    return False, "content differs (sorted line diff)"


def compare_png(snap, fresh, diff_path):
    """Pixel-diff two PNGs via ImageMagick `compare -metric AE`. Writes diff PNG.
    Returns (ok, differing_pixels_or_message)."""
    if not fresh.exists():
        return False, "missing in fresh output"
    # `compare` writes to stderr; exit code 0 = identical, 1 = differ, 2 = error.
    proc = subprocess.run(
        ["compare", "-metric", "AE", "-fuzz", "1%",
         str(snap), str(fresh), str(diff_path)],
        capture_output=True, text=True,
    )
    if proc.returncode == 2:
        return False, f"ImageMagick compare error: {proc.stderr.strip()}"
    # AE count is the last token on stderr
    m = re.search(r"(\d+)", proc.stderr)
    if not m:
        return False, f"unexpected compare output: {proc.stderr.strip()}"
    diff_pixels = int(m.group(1))
    if diff_pixels <= PIXEL_TOLERANCE:
        diff_path.unlink(missing_ok=True)
        return True, f"{diff_pixels} px"
    return False, f"{diff_pixels} px differ (see {diff_path})"


def cmd_snapshot(args):
    projects = load_config(args.config)
    snap_root = Path(args.snapshot_dir).resolve()
    for p in projects:
        print(f"==> snapshot {p.name}")
        dest = snap_root / p.name
        if dest.exists():
            shutil.rmtree(dest)
        generate_artifacts(p, dest)
        print(f"    wrote {dest}")
    print(f"\nSnapshot complete: {snap_root}")


def cmd_compare(args):
    projects = load_config(args.config)
    snap_root = Path(args.snapshot_dir).resolve()
    if not snap_root.exists():
        sys.exit(f"snapshot dir not found: {snap_root}")

    overall_ok = True
    summary = []

    for p in projects:
        print(f"==> compare {p.name}")
        snap_dir = snap_root / p.name
        if not snap_dir.exists():
            print(f"  ! no snapshot for {p.name}, skipping")
            summary.append((p.name, False, "missing snapshot"))
            overall_ok = False
            continue

        with tempfile.TemporaryDirectory(prefix="kikit-e2e-cmp-") as tmp:
            fresh = Path(tmp) / "fresh"
            diffs_dir = snap_root / p.name / "_diffs"
            shutil.rmtree(diffs_dir, ignore_errors=True)
            generate_artifacts(p, fresh)

            failures = []

            # PNG layers
            snap_layers = snap_dir / "layers"
            fresh_layers = fresh / "layers"
            for snap_png in sorted(snap_layers.glob("*.png")):
                fresh_png = fresh_layers / snap_png.name
                diffs_dir.mkdir(parents=True, exist_ok=True)
                diff_png = diffs_dir / snap_png.name
                ok, msg = compare_png(snap_png, fresh_png, diff_png)
                status = "ok " if ok else "FAIL"
                print(f"    [{status}] layer {snap_png.name}: {msg}")
                if not ok:
                    failures.append(f"layer {snap_png.name}: {msg}")

            # Check for new layers that didn't exist in the snapshot
            for fresh_png in sorted(fresh_layers.glob("*.png")):
                if not (snap_layers / fresh_png.name).exists():
                    print(f"    [FAIL] new layer in fresh output: {fresh_png.name}")
                    failures.append(f"new layer: {fresh_png.name}")

            # Text outputs (BOM, pos, unassigned)
            for f in sorted(snap_dir.iterdir()):
                if f.is_file() and f.suffix in (".csv", ".txt"):
                    ok, msg = compare_text(f, fresh / f.name)
                    status = "ok " if ok else "FAIL"
                    print(f"    [{status}] text  {f.name}: {msg or 'identical'}")
                    if not ok:
                        failures.append(f"text {f.name}: {msg}")

            if failures:
                overall_ok = False
                summary.append((p.name, False, f"{len(failures)} diff(s)"))
            else:
                summary.append((p.name, True, "all match"))

    print("\n=== Summary ===")
    for name, ok, msg in summary:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {msg}")

    sys.exit(0 if overall_ok else 1)


def build_parser():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser(
        "snapshot",
        help="Run fab on each project and save outputs as the reference snapshot.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_snap.add_argument("config", help="Path to YAML config listing projects.")
    p_snap.add_argument("snapshot_dir", help="Directory to write the snapshot into.")
    p_snap.set_defaults(func=cmd_snapshot)

    p_cmp = sub.add_parser(
        "compare",
        help="Re-run fab on each project and diff against the snapshot.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p_cmp.add_argument("config", help="Path to YAML config listing projects.")
    p_cmp.add_argument("snapshot_dir", help="Directory containing a prior snapshot.")
    p_cmp.set_defaults(func=cmd_compare)

    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.func(args)
