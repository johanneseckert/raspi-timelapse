#!/usr/bin/env python3

"""
Timelapse Camera Script

This script captures photos throughout the day and creates a timelapse video.
It operates in two modes:

1. Normal Mode (default):
	 - Captures photos from before sunrise until after sunset
	 - Creates a video at the end of each day
	 Run with: python timelapse.py

2. Test Mode:
	 - Quick test that captures 10 photos with 2-second intervals
	 - Creates a test video immediately after capturing
	 - Total runtime approximately 20-30 seconds
	 # Test mode with video (original behavior)
	 python timelapse.py --test

	 # Test mode without video creation
	 python timelapse.py --test --no-video

The test mode is useful for verifying camera setup and video creation
without waiting for a full day cycle.

Configuration:
- Copy config.template.json to config.json
- Adjust settings in config.json to match your setup
- The config.json file is ignored by git to keep sensitive data private

TODO: Home Assistant Integration
- Add MQTT support to connect with Home Assistant
- Features to implement:
	* Show latest captured photo in HA
	* Add toggle switch to control capturing
	* Add uptime sensor
	* Publish system status
	* Add reboot button to safely restart the Pi
	* Latest status message (like "waiting for capture start time" or "capturing…" or "waiting for next capture")
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging
import json
from picamera2 import Picamera2 # type: ignore
from picamera2.encoders import H264Encoder # type: ignore
from picamera2.outputs import FfmpegOutput # type: ignore
from astral import LocationInfo # type: ignore
from astral.sun import sun # type: ignore
import argparse
import paho.mqtt.client as mqtt

def load_config():
	"""Load configuration from JSON file"""
	config_path = Path(__file__).parent / "config.json"
	template_path = Path(__file__).parent / "config.template.json"

	if not config_path.exists():
		if template_path.exists():
			logger.info("No config.json found. Creating from template.")
			with open(template_path, 'r') as f:
				config = json.load(f)
			with open(config_path, 'w') as f:
				json.dump(config, f, indent=4)
		else:
			raise FileNotFoundError("Neither config.json nor config.template.json found!")
	else:
		with open(config_path, 'r') as f:
			config = json.load(f)

	return config

# Configure logging
config = load_config()  # Load config first to get log file path
log_file = Path(config['paths']['base_dir']) / config['paths']['log_file']
log_file.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s - %(levelname)s - %(message)s',
	handlers=[
		logging.FileHandler(str(log_file)),
		logging.StreamHandler()
	]
)
logger = logging.getLogger(__name__)

class HomeAssistantMQTT:
	"""Handles MQTT communication with Home Assistant"""
	def __init__(self, host="localhost", port=1883, username=None, password=None):
		self.client = mqtt.Client()
		if username and password:
			self.client.username_pw_set(username, password)

		# Set up callbacks
		self.client.on_connect = self.on_connect
		self.client.on_message = self.on_message

		# MQTT settings
		self.host = host
		self.port = port
		self.base_topic = "homeassistant"
		self.device_name = "timelapse_camera"

		# Device info for Home Assistant
		self.device_info = {
			"identifiers": [self.device_name],
			"name": "Timelapse Camera",
			"model": "Raspberry Pi Camera",
			"manufacturer": "Custom",
			"sw_version": "1.0.0"
		}

		# Connect to MQTT broker
		try:
			self.client.connect(host, port, 60)
			self.client.loop_start()
			logger.info(f"Connected to MQTT broker at {host}:{port}")
		except Exception as e:
			logger.error(f"Failed to connect to MQTT broker: {e}")
			raise

	def on_connect(self, client, userdata, flags, rc):
		"""Callback when connected to MQTT broker"""
		if rc == 0:
			logger.info("Connected to MQTT broker")
			# Subscribe to command topics
			self.client.subscribe(f"{self.device_name}/command/#")
			# Register entities with Home Assistant
			self.register_entities()
		else:
			logger.error(f"Failed to connect to MQTT broker with code {rc}")

	def on_message(self, client, userdata, msg):
		"""Handle incoming MQTT messages"""
		try:
			topic = msg.topic
			payload = msg.payload.decode()
			logger.info(f"Received MQTT message on topic {topic}: {payload}")

			if topic == f"{self.device_name}/command/capture":
				if payload == "ON":
					logger.info("Capture enabled via MQTT")
					# TODO: Enable capture
				else:
					logger.info("Capture disabled via MQTT")
					# TODO: Disable capture
			elif topic == f"{self.device_name}/command/reboot":
				logger.info("Reboot command received")
				# TODO: Implement safe reboot
		except Exception as e:
			logger.error(f"Error processing MQTT message: {e}")

	def register_entities(self):
		"""Register entities with Home Assistant via MQTT discovery"""
		# Switch for enabling/disabling capture
		switch_config = {
			"name": "Timelapse Capture",
			"unique_id": f"{self.device_name}_capture",
			"command_topic": f"{self.device_name}/command/capture",
			"state_topic": f"{self.device_name}/state/capture",
			"device": self.device_info
		}
		self.client.publish(
			f"{self.base_topic}/switch/{self.device_name}/capture/config",
			json.dumps(switch_config),
			retain=True
		)

		# Button for reboot
		button_config = {
			"name": "Timelapse Camera Reboot",
			"unique_id": f"{self.device_name}_reboot",
			"command_topic": f"{self.device_name}/command/reboot",
			"device": self.device_info
		}
		self.client.publish(
			f"{self.base_topic}/button/{self.device_name}/reboot/config",
			json.dumps(button_config),
			retain=True
		)

		# Sensor for uptime
		sensor_config = {
			"name": "Timelapse Uptime",
			"unique_id": f"{self.device_name}_uptime",
			"state_topic": f"{self.device_name}/state/uptime",
			"device": self.device_info,
			"unit_of_measurement": "seconds"
		}
		self.client.publish(
			f"{self.base_topic}/sensor/{self.device_name}/uptime/config",
			json.dumps(sensor_config),
			retain=True
		)

	def publish_state(self, entity_type, state):
		"""Publish state updates to Home Assistant"""
		self.client.publish(
			f"{self.device_name}/state/{entity_type}",
			json.dumps({"state": state}),
			retain=True
		)

	def disconnect(self):
		"""Disconnect from MQTT broker"""
		self.client.loop_stop()
		self.client.disconnect()

class TimelapseCamera:
	def __init__(self, test_mode=False, skip_video=False):
		self.config = load_config()
		self.camera = Picamera2()
		self.setup_camera()
		self.base_dir = Path(self.config['paths']['base_dir'])
		self.photos_dir = self.base_dir / self.config['paths']['photos_dir']
		self.videos_dir = self.base_dir / self.config['paths']['videos_dir']
		self.setup_directories()
		self.test_mode = test_mode
		self.skip_video = skip_video
		self.capturing_enabled = True
		self.start_time = time.time()

		# Initialize MQTT connection
		try:
			self.ha_mqtt = HomeAssistantMQTT(
				host=self.config['mqtt']['host'],
				port=self.config['mqtt']['port'],
				username=self.config['mqtt']['username'],
				password=self.config['mqtt']['password']
			)
		except Exception as e:
			logger.error(f"Failed to initialize MQTT: {e}")
			self.ha_mqtt = None

	def setup_camera(self):
		"""Initialize camera settings"""
		try:
			# Configure camera for 1080p
			camera_config = self.camera.create_still_configuration(
				main={"size": (
					self.config['camera']['resolution']['width'],
					self.config['camera']['resolution']['height']
				)},
				controls={"FrameDurationLimits": (33333, 33333)}  # ~30fps
			)
			self.camera.configure(camera_config)
			self.camera.start()
			logger.info("Camera initialized successfully")
		except Exception as e:
			logger.error(f"Failed to initialize camera: {e}")
			raise

	def setup_directories(self):
		"""Create necessary directories if they don't exist"""
		try:
			self.photos_dir.mkdir(parents=True, exist_ok=True)
			self.videos_dir.mkdir(parents=True, exist_ok=True)
			logger.info("Directories setup complete")
		except Exception as e:
			logger.error(f"Failed to create directories: {e}")
			raise

	def get_sun_times(self):
		"""Calculate sunrise and sunset times for the current day"""
		try:
			location = LocationInfo(
				latitude=self.config['location']['latitude'],
				longitude=self.config['location']['longitude'],
				timezone=self.config['location']['timezone']
			)
			s = sun(location.observer, date=datetime.now())

			start_time = s['sunrise'] - timedelta(hours=self.config['camera']['hours_before_sunrise'])
			end_time = s['sunset'] + timedelta(hours=self.config['camera']['hours_after_sunset'])
			logger.info(f"Today's recording from {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')} ")

			return start_time, end_time
		except Exception as e:
			logger.error(f"Failed to calculate sun times: {e}")
			raise

	def take_photo(self):
		"""Capture a single photo with timestamp"""
		try:
			timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
			filename = f"photo_{timestamp}.jpg"
			filepath = self.photos_dir / filename

			self.camera.capture_file(str(filepath))
			logger.info(f"Photo captured: {filename}")

			# Publish latest photo info to Home Assistant
			if self.ha_mqtt:
				self.ha_mqtt.publish_state("latest_photo", str(filepath))
		except Exception as e:
			logger.error(f"Failed to capture photo: {e}")

	def create_video(self):
		"""Create video from photos taken today"""
		try:
			# Video creation temporarily disabled for stability testing
			logger.info("Video creation temporarily disabled for stability testing")
			return

			# today = datetime.now().strftime('%Y%m%d')
			# output_file = self.videos_dir / f"timelapse_{today}.mp4"
			#
			# # Use ffmpeg to create video from photos
			# # -y: Override output file if it exists
			# # -b:v 8M: Set video bitrate to 8 Mbps
			# os.system(f"ffmpeg -y -framerate 30 -pattern_type glob -i '{self.photos_dir}/photo_{today}_*.jpg' "
			#          f"-c:v libx264 -pix_fmt yuv420p -b:v 8M {output_file}")
			#
			# logger.info(f"Video created: {output_file}")
		except Exception as e:
			logger.error(f"Failed to create video: {e}")

	def update_ha_status(self):
		"""Update Home Assistant with current status"""
		if self.ha_mqtt:
			# Update uptime
			uptime = int(time.time() - self.start_time)
			self.ha_mqtt.publish_state("uptime", uptime)

			# Update capture state
			self.ha_mqtt.publish_state("capture", "ON" if self.capturing_enabled else "OFF")

	def run(self):
		"""Main loop for the timelapse system"""
		if self.test_mode:
			self._run_test_mode()
		else:
			self._run_normal_mode()

	def _run_test_mode(self):
		"""Quick test mode for capturing photos and creating a video"""
		try:
			logger.info("Running in test mode")
			self.update_ha_status()  # Initial status update

			for i in range(self.config['camera']['test_capture_count']):
				if not self.capturing_enabled:
					logger.info("Capture disabled, skipping test photos")
					break

				logger.info(f"Taking test photo {i+1}/{self.config['camera']['test_capture_count']}")
				self.take_photo()
				self.update_ha_status()
				time.sleep(self.config['camera']['test_interval_seconds'])

			# Video creation temporarily disabled for stability testing
			logger.info("Video creation temporarily disabled for stability testing")
			# if not self.skip_video:
			#     logger.info("Creating test video")
			#     self.create_video()
			# else:
			#     logger.info("Skipping video creation (--no-video flag set)")

			logger.info("Test completed")

		except Exception as e:
			logger.error(f"Error in test mode: {e}")

	def _run_normal_mode(self):
		"""Original production mode"""
		while True:
			try:
				self.update_ha_status()  # Update Home Assistant status

				start_time, end_time = self.get_sun_times()
				current_time = datetime.now(start_time.tzinfo)  # Make current_time timezone-aware

				if start_time <= current_time <= end_time and self.capturing_enabled:
					self.take_photo()
					time.sleep(self.config['camera']['interval_minutes'] * 60)
				elif current_time > end_time:
					# Video creation temporarily disabled for stability testing
					logger.info("Video creation temporarily disabled for stability testing")
					# self.create_video()
					# Wait until next day
					tomorrow = current_time + timedelta(days=1)
					tomorrow_start = tomorrow.replace(
							hour=start_time.hour,
							minute=start_time.minute,
							second=0,
							microsecond=0
					)
					sleep_seconds = (tomorrow_start - current_time).total_seconds()
					logger.info(f"Waiting {sleep_seconds/3600:.1f} hours until next day")
					time.sleep(sleep_seconds)
				else:
					# Wait until start time or until capturing is enabled
					sleep_seconds = min(
							(start_time - current_time).total_seconds(),
							60  # Check status every minute
					)
					logger.info(f"Waiting {sleep_seconds/3600:.1f} hours until start time")
					time.sleep(sleep_seconds)

			except Exception as e:
				logger.error(f"Error in main loop: {e}")
				time.sleep(60)  # Wait a minute before retrying

	def cleanup(self):
		"""Cleanup resources before exit"""
		try:
			if self.camera:
				self.camera.stop()
			if self.ha_mqtt:
				self.ha_mqtt.disconnect()
		except Exception as e:
			logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Timelapse Camera')
	parser.add_argument('--test', action='store_true', help='Run in test mode')
	parser.add_argument('--no-video', action='store_true', help='Skip video creation in test mode')
	args = parser.parse_args()

	camera = TimelapseCamera(test_mode=args.test, skip_video=args.no_video)
	try:
		camera.run()
	finally:
		camera.cleanup()