from pathlib import Path
import os
import shutil

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "build_data" / "merged" / "data.yaml"
OUT = ROOT / "build_output"
MODEL_OUT = ROOT / "models" / "best.pt"

EPOCHS = int(os.getenv("TRAIN_EPOCHS", "2"))
IMGSZ = int(os.getenv("TRAIN_IMGSZ", "416"))
BATCH = int(os.getenv("TRAIN_BATCH", "4"))

if not DATA.exists():
    raise FileNotFoundError(f"Merged dataset not found: {DATA}")

MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)

model = YOLO("yolo26n.pt")
model.train(
    data=str(DATA),
    epochs=EPOCHS,
    imgsz=IMGSZ,
    batch=BATCH,
    device="cpu",
    workers=2,
    project=str(OUT),
    name="minecraft_detector",
    exist_ok=True,
    verbose=True,
)

best = OUT / "minecraft_detector" / "weights" / "best.pt"
if not best.exists():
    raise FileNotFoundError(f"Training finished but best.pt was not found at {best}")

shutil.copy2(best, MODEL_OUT)
print(f"Saved trained model to {MODEL_OUT}")
