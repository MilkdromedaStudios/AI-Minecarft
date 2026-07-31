# AI Minecraft

Minecraft AI experiment using **Ultralytics YOLO26** for object detection and **Mineflayer** for controls.

Licensed under the **MIT License**.

## Automatic GitHub build

The GitHub Actions workflow **Build and Train Minecraft AI** runs on **every push to any branch**, on pull requests, and can also be started manually.

Every build:

1. installs Python and Node.js dependencies;
2. downloads the public Minecraft-Objects gameplay dataset from Roboflow;
3. downloads the CC BY 4.0 Minecraft mob gameplay dataset from Hugging Face;
4. merges both YOLO datasets and remaps overlapping class IDs;
5. trains a YOLO26 nano detector on CPU;
6. writes the resulting model to `models/best.pt`;
7. stores `models/best.pt` through **Git LFS** on push builds;
8. creates the downloadable `AI-Minecarft-Windows-Test-Package` artifact.

The automatic CI build currently uses a short CPU-friendly training run (`2` epochs, `416` image size). Increase `TRAIN_EPOCHS`, `TRAIN_IMGSZ`, or `TRAIN_BATCH` in `.github/workflows/build.yml` when you want longer training.

## Training datasets

Dataset definitions are kept in `dataset_sources.json`.

- **Minecraft-Objects**: `minecraftdataset/minecraft-objects/2` from Roboflow Universe.
- **Minecraft Mobs YOLO Dataset**: `hmnshudhmn24/minecraft-mobs-yolo-dataset` from Hugging Face, CC BY 4.0, credited to Draco TLW (Muhammad Alimuhammadi).

The raw ~844 MB mob dataset is downloaded/cached by Actions instead of being committed into normal Git history.

## AI control files

There are three control layers:

```text
controls.json
    low-level action vocabulary

controller.json
    detected object -> desired behavior/tool policy

controller.js
    receives commands and actually controls Mineflayer
```

Examples from `controller.json`:

```text
creeper -> back
diamond -> mine using pickaxe
iron -> mine using pickaxe
zombie -> attack using sword
skeleton -> attack using sword
enderman -> ignore by default
```

`controller.js` accepts either a direct action:

```json
{"action":"forward"}
```

or a YOLO detection:

```json
{"detected":"diamond-ore"}
```

and maps the detected label through `controller.json`.

## Download a ready build

1. Open **Actions** in this repository.
2. Open the newest successful **Build and Train Minecraft AI** run.
3. Download `AI-Minecarft-Windows-Test-Package`.
4. Extract it.
5. Run `setup_windows.bat`.
6. Start your Minecraft Java server/world.
7. Run `run_controller.bat`.

## Clone instead

If you clone the repository, make sure Git LFS is installed, then:

```powershell
git lfs install
git lfs pull
pip install -r requirements.txt
npm install
```

The trained GitHub model is:

```text
models/best.pt
```

## Test the controller manually

Start:

```powershell
node controller.js
```

Then from another terminal:

```powershell
python send_control.py forward
python send_control.py jump
python send_control.py turn_left
python send_control.py mine
python send_control.py attack
```

The Mineflayer receiver listens on `127.0.0.1:5050`.

## Test YOLO locally

If you have the Roboflow test images in `Data/test/images/`, run:

```powershell
python run.py
```

`run.py` prefers `models/best.pt` and prints both the detected label and the action selected by `controller.json`.

## Repository layout

```text
AI-Minecarft/
├── .github/workflows/build.yml
├── .gitattributes
├── LICENSE
├── README.md
├── controller.js
├── controller.json
├── controls.json
├── control_sequences.json
├── dataset_sources.json
├── prepare_dataset.py
├── train_ci.py
├── run.py
├── train.py
├── send_control.py
├── requirements.txt
├── package.json
├── setup_windows.bat
├── run_controller.bat
└── models/
    └── best.pt       # Git LFS after the first successful push build
```

Large temporary build datasets, Python environments, `node_modules`, IDE files, and Ultralytics caches are ignored.
