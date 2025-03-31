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
# System packages
sudo apt-get update
sudo apt-get install -y python3-pip python3-libcamera python3-picamera2 python3-astral python3-paho-mqtt python3-pil ffmpeg

# Or if you prefer using pip (not recommended on Debian/Raspberry Pi OS):
# sudo pip3 install -r requirements.txt
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

1. Copy the template configuration file:
```bash
cp config.template.json config.json
```

2. Edit `config.json` to match your setup:
```json
{
	"location": {
		"latitude": 48.4639,      // Your latitude
		"longitude": 9.2075,      // Your longitude
		"timezone": "Europe/Berlin"  // Your timezone
	},
	"camera": {
		"hours_before_sunrise": 1,  // Start capturing this many hours before sunrise
		"hours_after_sunset": 1,    // Continue capturing this many hours after sunset
		"interval_minutes": 1,      // Minutes between photos
		"resolution": {
			"width": 1920,         // Photo width
			"height": 1080         // Photo height
		}
	},
	"mqtt": {
		"host": "localhost",      // MQTT broker host (for Home Assistant)
		"port": 1883,            // MQTT broker port
		"username": null,        // MQTT username if required
		"password": null         // MQTT password if required
	},
	"test_mode": {
		"capture_count": 10,     // Number of photos in test mode
		"interval_seconds": 2     // Seconds between photos in test mode
	},
	"paths": {
		"base_dir": "/opt/timelapse",  // Base directory for all files
		"photos_dir": "photos",        // Photo directory (relative to base_dir)
		"videos_dir": "videos",        // Video directory (relative to base_dir)
		"log_file": "timelapse.log"    // Log file (relative to base_dir)
	}
}
```

The `config.json` file is ignored by git to keep your settings private. The template file (`config.template.json`) contains default values and is version controlled.

## Monitoring

Check the log file for status and errors:
```bash
tail -f /opt/timelapse/timelapse.log
```