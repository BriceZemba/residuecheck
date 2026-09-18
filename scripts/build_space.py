"""Assemble the Hugging Face Space (Docker) folder: build/space/.

It holds only what the image needs: Dockerfile, the Space card as README.md, app requirements, the package, runtime
data (EU snapshot, ONSSA cache, crop map and index, demo lots, replay recordings) and the web sources.

Usage:
  python scripts/build_space.py
  huggingface-cli upload <user>/residuecheck build/space . --repo-type=space   # needs your own Hugging Face login
"""
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "space"
FILES = ["Dockerfile", ".dockerignore", "requirements-app.txt", "LICENSE"]
TREES = ["residuecheck", "data", "web"]
SKIP = {"__pycache__", "node_modules", "dist", "raw"}
SKIP_FILES = {"rasff_pesticides_fv.csv"}  # eval input, not used by the app


def keep(path):
    return not (set(path.relative_to(ROOT).parts) & SKIP) and path.name not in SKIP_FILES and path.suffix != ".pyc"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name in FILES:
        shutil.copy2(ROOT / name, OUT / name)
    shutil.copy2(ROOT / "deploy" / "huggingface" / "README.md", OUT / "README.md")
    count = size = 0
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*")):
            if path.is_file() and keep(path):
                dest = OUT / path.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
                count, size = count + 1, size + path.stat().st_size
    replays = sorted(p.name for p in (OUT / "data" / "replays").glob("*.json")) if (OUT / "data" / "replays").exists() else []
    print(f"{OUT}: {count} files, {size / 1e6:.1f} MB; replay recordings: {replays or 'none (the Space will run rules-only)'}")


if __name__ == "__main__":
    main()
