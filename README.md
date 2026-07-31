# AI Minecraft

A small Minecraft AI project using:

- **Ultralytics YOLO26** for object detection
- **Mineflayer** for Minecraft controls
- a tiny local TCP bridge so Python can send actions to the bot

## Project layout

```text
AI-Minecarft/
├── run.py
├── train.py
├── send_control.py
├── controller.js
├── controls.json
├── control_sequences.json
├── requirements.txt
├── package.json
└── Data/                 # keep your local Roboflow dataset/model here
```

## 1. Python setup

```powershell
pip install -r requirements.txt
```

## 2. Mineflayer setup

Install Node.js once, then run:

```powershell
npm install
```

## 3. Start the Minecraft controller

Open `controller.js` and change these settings if needed:

```js
host: "localhost",
port: 25565,
username: "MinecraftAI",
auth: "offline"
```

Then run:

```powershell
node controller.js
```

The controller listens on:

```text
127.0.0.1:5050
```

## 4. Test controls manually

In another terminal:

```powershell
python send_control.py forward
python send_control.py jump
python send_control.py turn_left
python send_control.py mine
python send_control.py attack
```

Supported commands include:

```text
forward
back
left
right
jump
stop
turn_left
turn_right
look_up
look_down
mine
attack
```

## 5. Test your trained detector

Keep the trained detection model at:

```text
Data/minecraft_detector/weights/best.pt
```

and your Roboflow test images at:

```text
Data/test/images/
```

Then run:

```powershell
python run.py
```

`run.py` picks a random test image, runs YOLO, prints detections, and shows bounding boxes.

## 6. Train again if needed

Keep the Roboflow YOLO26 export at:

```text
Data/data.yaml
Data/train/images/
Data/train/labels/
Data/valid/images/
Data/valid/labels/
Data/test/images/
Data/test/labels/
```

Then:

```powershell
python train.py
```

## How the pieces fit

```text
YOLO -> sees objects
Python brain -> chooses a command
controller.js -> Mineflayer performs the command
```

`controls.json` and `control_sequences.json` are the action vocabulary/reference for the decision layer. The detector itself does not learn JavaScript controls from JSON.

## Not stored in GitHub

The `.gitignore` excludes large or machine-specific files such as:

- `.venv/`
- `node_modules/`
- `.idea/`
- `*.pt` model weights
- local datasets under `Data/`
- Ultralytics run/cache output

Keep your dataset and `best.pt` on your PC unless you intentionally decide to publish them later.
