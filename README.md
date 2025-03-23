# Raspberry Pi Timelapse Camera

This is a Python-based timelapse camera system for Raspberry Pi that automatically captures photos during daylight hours and creates daily timelapse videos.

## Features

- Automatic photo capture during daylight hours
- Configurable start/end times relative to sunrise/sunset
- 1080p resolution photos
- Automatic daily video creation
- Configurable capture interval
- Automatic restart on system boot

## Setup

1. Install dependencies:
```bash
# Update system and install required packages
sudo apt-get update
sudo apt-get install python3-pip python3-libcamera python3-picamera2 python3-astral ffmpeg
```

2. Configure the camera:
   - Edit the configuration in the script
   - Set your latitude/longitude
   - Adjust timing parameters as needed

3. Set up as a system service:
```bash
sudo cp timelapse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable timelapse
sudo systemctl start timelapse
```

## Directory Structure

- `/opt/timelapse/photos/` - Contains individual photos
- `/opt/timelapse/videos/` - Contains daily timelapse videos
- `/opt/timelapse/timelapse.log` - Log file

## Configuration

Edit the `config` dictionary in the script to adjust:
- Latitude/Longitude
- Hours before sunrise/after sunset
- Capture interval
- Resolution

## Monitoring

Check the log file for status and errors:
```bash
tail -f /opt/timelapse/timelapse.log
```