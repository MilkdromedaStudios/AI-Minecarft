# AI Minecraft

A small Minecraft AI project using:

- **Ultralytics YOLO26** for object detection
- **Mineflayer** for Minecraft controls
- a tiny local TCP bridge so Python can send actions to the bot

Licensed under the **MIT License**.

## Easiest way to get a tested build

GitHub Actions now checks and packages the project automatically on every push to `main`.

1. Open this repository on GitHub.
2. Open **Actions**.
3. Select **Build Minecraft AI**.
4. Open the newest successful run.
5. Under **Artifacts**, download:

```text
AI-Minecarft-Windows-Test-Package
```

6. Extract the downloaded artifact ZIP.
7. Extract `AI-Minecarft.zip` inside it.
8. On Windows, run:

```text
setup_windows.bat
```

That installs the Python requirements and Mineflayer. Then start your Minecraft server and run:

```text
run_controller.bat
```

## What GitHub Actions checks

The build workflow:

- installs Python 3.12
- installs the Python dependencies from `requirements.txt`
- installs Node.js 20
- installs Mineflayer
- syntax-checks `run.py`, `train.py`, and `send_control.py`
- syntax-checks `controller.js`
- validates the JSON control files
- creates a downloadable Windows test package

GitHub Actions cannot test the actual Minecraft connection because your Minecraft world/server runs on your PC. The final in-game test is therefore local.

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
├── setup_windows.bat
├── run_controller.bat
├── LICENSE
└── Data/                 # keep your local Roboflow dataset/model here
```

## Manual setup

If you clone the repository instead of downloading the Actions artifact:

```powershell
pip install -r requirements.txt
npm install
```

Or just run:

```text
setup_windows.bat
```

## Start the Minecraft controller

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

or double-click:

```text
run_controller.bat
```

The controller listens on:

```text
127.0.0.1:5050
```

## Test controls manually

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

## Test your trained detector

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

## Train again if needed

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
