from pathlib import Path
import random

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "Data" / "minecraft_detector" / "weights" / "best.pt"
TEST_FOLDER = ROOT / "Data" / "test" / "images"

if not MODEL.exists():
    raise FileNotFoundError(f"Model not found: {MODEL}")

images = []
for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
    images.extend(TEST_FOLDER.glob(pattern))

if not images:
    raise FileNotFoundError(f"No test images found in: {TEST_FOLDER}")

model = YOLO(str(MODEL))
test_image = random.choice(images)

print("Testing:", test_image)

result = model(str(test_image), conf=0.25, device=0, verbose=False)[0]

print("\nDetected:")
if result.boxes is None or len(result.boxes) == 0:
    print("Nothing")
else:
    for box in result.boxes:
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        print(f"{result.names[class_id]}: {confidence * 100:.1f}%")

frame = result.plot()
cv2.imshow("Minecraft AI Detection", frame)
print("\nPress any key in the image window to close.")
cv2.waitKey(0)
cv2.destroyAllWindows()
