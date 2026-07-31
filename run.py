from pathlib import Path
import json
import random

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
MODEL_CANDIDATES = [
    ROOT / "models" / "best.pt",
    ROOT / "Data" / "minecraft_detector" / "weights" / "best.pt",
]
TEST_FOLDER = ROOT / "Data" / "test" / "images"
POLICY_FILE = ROOT / "controller.json"

MODEL = next((p for p in MODEL_CANDIDATES if p.exists()), None)
if MODEL is None:
    raise FileNotFoundError(
        "No best.pt found. Run the GitHub Actions build / git lfs pull, "
        "or place a local model in Data/minecraft_detector/weights/best.pt"
    )

policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))

images = []
for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
    images.extend(TEST_FOLDER.glob(pattern))

if not images:
    raise FileNotFoundError(f"No test images found in: {TEST_FOLDER}")

model = YOLO(str(MODEL))
test_image = random.choice(images)
print("Model:", MODEL)
print("Testing:", test_image)

result = model(str(test_image), conf=0.25, device=0, verbose=False)[0]

print("\nDetected:")
if result.boxes is None or len(result.boxes) == 0:
    print("Nothing")
else:
    for box in result.boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        label = str(result.names[class_id]).lower().replace("_", "-")
        key = policy.get("aliases", {}).get(label, label)
        rule = policy.get("objects", {}).get(key)
        if rule is None:
            rule = next(
                (v for k, v in policy.get("objects", {}).items() if k in key),
                {"action": policy.get("default_action", "forward")},
            )
        print(
            f"{label}: {confidence * 100:.1f}% -> "
            f"{rule.get('action')}"
            + (f" using {rule.get('tool')}" if rule.get("tool") else "")
        )

frame = result.plot()
cv2.imshow("Minecraft AI Detection", frame)
print("\nPress any key in the image window to close.")
cv2.waitKey(0)
cv2.destroyAllWindows()
