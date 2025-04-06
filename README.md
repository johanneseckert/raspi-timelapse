# Raspberry Pi Timelapse Camera with Web Interface

This project provides a timelapse camera system for the Raspberry Pi with a web interface for live preview and control.

## Features

- 4K (3840x2160) photo capture
- Live preview through web interface
- Manual and automatic focus control
- Start/stop capture control
- MQTT integration with Home Assistant
- Configurable capture intervals

## Installation

1. Install system dependencies:
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-opencv
```

2. Install Python dependencies:
```bash
pip3 install -r requirements.txt
```

3. Create necessary directories:
```bash
mkdir -p photos
```

## Usage

1. Start the camera with web interface:
```bash
python3 timelapse.py --web --web-port 8000
```

2. Access the web interface:
Open a web browser and navigate to:
```
http://<raspberry-pi-ip>:8000
```

## Web Interface Controls

- **Live Preview**: Toggle the live camera preview
- **Capture Control**: Start/stop timelapse capture
- **Focus Control**:
  - Auto Focus: Switch to automatic focus mode
  - Manual Focus: Use the slider to adjust focus manually

## Configuration

Edit `config.json` to modify:
- Capture interval
- Image quality settings
- MQTT settings
- Other camera parameters

## MQTT Integration

The system publishes:
- Latest photo (resized to 480x270 for MQTT)
- Camera status
- Uptime information

## Notes

- The camera captures at 4K resolution but sends smaller preview images to reduce bandwidth usage
- The web interface runs on port 8000 by default
- Photos are saved in the `photos` directory with timestamps