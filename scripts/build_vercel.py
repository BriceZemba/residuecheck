"""Assemble the Vercel deployment folder: build/vercel/ (FastAPI function + prebuilt React app).

Vercel runs app.py as a Python function (FastAPI framework preset). The React app is built here and shipped as
web/dist, which FastAPI serves, so the deployment needs no Node build step. No keys are included: the deployment
replays recordings from data/replays if any, else runs on fixed rules.

Usage:
  python scripts/build_vercel.py
  npx vercel login                                   # once, your own Vercel account
  npx vercel link --cwd build/vercel --project residuecheck --yes   # once
  npx vercel deploy build/vercel --prod              # prints the public URL
"""
import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "vercel"
SKIP = {"__pycache__", "raw"}
SKIP_FILES = {"rasff_pesticides_fv.csv"}  # eval input, not used by the app

APP = '''"""Vercel entrypoint: the ResidueCheck FastAPI app (see residuecheck/api.py)."""
from residuecheck.api import app  # noqa: F401
'''
VERCEL_JSON = {
    "$schema": "https://openapi.vercel.sh/vercel.json",
    "framework": "fastapi",
    "functions": {"app.py": {"maxDuration": 60}},
}


def copy_tree(src, dest):
    n = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if path.is_file() and not (set(rel.parts) & SKIP) and path.name not in SKIP_FILES and path.suffix != ".pyc":
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest / rel)
            n += 1
    return n


def main():
    subprocess.run("npm run build", cwd=ROOT / "web", shell=True, check=True, capture_output=True)
    # Clear the folder but keep .vercel/ (the link to the Vercel project; without it the next deploy creates a new
    # project). Never ship .env files: `vercel link` writes a token to .env.local.
    OUT.mkdir(parents=True, exist_ok=True)
    for child in OUT.iterdir():
        if child.name == ".vercel":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    n = copy_tree(ROOT / "residuecheck", OUT / "residuecheck")
    n += copy_tree(ROOT / "data", OUT / "data")
    n += copy_tree(ROOT / "web" / "dist", OUT / "web" / "dist")
    shutil.copy2(ROOT / "requirements-app.txt", OUT / "requirements.txt")
    shutil.copy2(ROOT / "LICENSE", OUT / "LICENSE")
    (OUT / "app.py").write_text(APP, encoding="utf-8", newline="\n")
    (OUT / "vercel.json").write_text(json.dumps(VERCEL_JSON, indent=2) + "\n", encoding="utf-8", newline="\n")
    (OUT / ".python-version").write_text("3.12\n", encoding="utf-8", newline="\n")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    replays = sorted(p.name for p in (OUT / "data" / "replays").glob("*.json")) if (OUT / "data" / "replays").exists() else []
    print(f"{OUT}: {n + 5} files, {size / 1e6:.1f} MB; replay recordings: {replays or 'none (fixed rules only)'}")


if __name__ == "__main__":
    main()
