from pathlib import Path
from ultralytics import YOLO

if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parent
    DATA = ROOT / "Data" / "data.yaml"

    model = YOLO("yolo26n.pt")

    model.train(
        data=str(DATA),
        epochs=50,
        imgsz=640,
        batch=8,
        device=0,
        workers=0,
        project=str(ROOT / "Data"),
        name="minecraft_detector",
        exist_ok=True,
    )
