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
from PIL import Image
import io
import base64

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
		logger.info(f"Initializing MQTT connection to {host}:{port}")
		try:
			# Enable MQTT internal logging
			mqtt.Client.bad_connection_flag = False
			mqtt_logger = logging.getLogger('mqtt')
			mqtt_logger.setLevel(logging.DEBUG)

			self.client = mqtt.Client()
			self.client.enable_logger(mqtt_logger)

			# Set up callbacks
			self.client.on_connect = self.on_connect
			self.client.on_message = self.on_message
			self.client.on_publish = self.on_publish
			self.client.on_disconnect = self.on_disconnect
			self.client.on_log = self.on_log  # Add logging callback

			if username and password:
				logger.info(f"Configuring MQTT authentication with username: {username}")
				self.client.username_pw_set(username, password)

			# MQTT settings
			self.host = host
			self.port = port
			self.base_topic = "homeassistant"
			self.device_name = "timelapse_camera"
			self.connected = False

			# Device info for Home Assistant
			self.device_info = {
				"identifiers": [self.device_name],
				"name": "Timelapse Camera",
				"model": "Raspberry Pi Zero 2W with Pi Camera",
				"manufacturer": "Johannes Eckert",
				"sw_version": "1.0.0"
			}

			# Connect to MQTT broker
			logger.info(f"Attempting to connect to MQTT broker at {host}:{port}...")
			self.client.connect(host, port, 60)
			self.client.loop_start()
			logger.info("MQTT network loop started")

		except Exception as e:
			logger.error(f"Failed to initialize MQTT: {str(e)}")
			logger.error(f"Exception type: {type(e).__name__}")
			logger.error(f"Stack trace:", exc_info=True)
			raise

	def on_log(self, client, userdata, level, buf):
		"""Callback for MQTT internal logging"""
		level_map = {
			mqtt.MQTT_LOG_INFO: logging.INFO,
			mqtt.MQTT_LOG_NOTICE: logging.INFO,
			mqtt.MQTT_LOG_WARNING: logging.WARNING,
			mqtt.MQTT_LOG_ERR: logging.ERROR,
			mqtt.MQTT_LOG_DEBUG: logging.DEBUG
		}
		logger.log(level_map.get(level, logging.DEBUG), f"MQTT Internal: {buf}")

	def on_connect(self, client, userdata, flags, rc):
		"""Callback when connected to MQTT broker"""
		connection_responses = {
			0: "Connected successfully",
			1: "Incorrect protocol version",
			2: "Invalid client identifier",
			3: "Server unavailable",
			4: "Bad username or password",
			5: "Not authorized"
		}
		if rc == 0:
			self.connected = True
			logger.info(f"Connected to MQTT broker: {connection_responses.get(rc, 'Unknown response')}")
			logger.info(f"Connection flags: {flags}")

			# Subscribe to command topics
			topic = f"{self.device_name}/command/#"
			logger.info(f"Subscribing to topic: {topic}")
			result, mid = self.client.subscribe(topic)
			logger.info(f"Subscription result: {result} (0=success) with message ID: {mid}")

			# Register entities with Home Assistant
			logger.info("Registering entities with Home Assistant")
			self.register_entities()

			# Set LWT (Last Will and Testament) for availability
			self.client.will_set(f"{self.device_name}/status", "offline", retain=True)
		else:
			self.connected = False
			logger.error(f"Failed to connect to MQTT broker: {connection_responses.get(rc, 'Unknown error')}")
			logger.error(f"Connection flags: {flags}")

	def on_disconnect(self, client, userdata, rc):
		"""Callback when disconnected from MQTT broker"""
		self.connected = False
		if rc != 0:
			logger.error(f"Unexpected MQTT disconnection (code {rc}). Will auto-reconnect.")
		else:
			logger.info("Disconnected from MQTT broker")

	def on_publish(self, client, userdata, mid):
		"""Callback when a message is published"""
		logger.debug(f"Message {mid} published successfully")

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
		logger.info("Starting entity registration with Home Assistant")

		# Camera image
		camera_config = {
			"name": "Timelapse Latest Photo",
			"unique_id": f"{self.device_name}_latest_photo",
			"topic": f"{self.device_name}/camera/image",
			"encoding": "base64",
			"content_type": "image/jpeg",
			"device": self.device_info,
			"availability_topic": f"{self.device_name}/status"
		}
		topic = f"{self.base_topic}/camera/{self.device_name}/config"
		logger.info(f"Publishing camera configuration to {topic}")
		self.client.publish(topic, json.dumps(camera_config), retain=True)

		# Uptime sensor
		uptime_config = {
			"name": "Timelapse Uptime",
			"unique_id": f"{self.device_name}_uptime",
			"state_topic": f"{self.device_name}/state/uptime",
			"device": self.device_info,
			"unit_of_measurement": "seconds",
			"availability_topic": f"{self.device_name}/status"
		}
		topic = f"{self.base_topic}/sensor/{self.device_name}/uptime/config"
		logger.info(f"Publishing uptime sensor configuration to {topic}")
		self.client.publish(topic, json.dumps(uptime_config), retain=True)

		# Last capture timestamp
		timestamp_config = {
			"name": "Last Photo Capture",
			"unique_id": f"{self.device_name}_last_capture",
			"state_topic": f"{self.device_name}/state/last_capture",
			"device": self.device_info,
			"device_class": "timestamp",
			"entity_category": "diagnostic",
			"availability_topic": f"{self.device_name}/status"
		}
		topic = f"{self.base_topic}/sensor/{self.device_name}/last_capture/config"
		logger.info(f"Publishing timestamp sensor configuration to {topic}")
		self.client.publish(topic, json.dumps(timestamp_config), retain=True)

		# Publish initial online status
		self.client.publish(f"{self.device_name}/status", "online", retain=True)

	def publish_state(self, entity_type, state):
		"""Publish state updates to Home Assistant"""
		if not self.connected:
			logger.warning(f"Cannot publish state - MQTT not connected")
			return

		topic = f"{self.device_name}/state/{entity_type}"
		payload = json.dumps({"state": state})
		logger.info(f"Publishing to {topic}: {payload}")
		result, mid = self.client.publish(topic, payload, retain=True)
		logger.info(f"Publish result: {result} (0=success) with message ID: {mid}")

	def disconnect(self):
		"""Disconnect from MQTT broker"""
		self.client.loop_stop()
		self.client.disconnect()

class TimelapseCamera:
	def __init__(self, test_mode=False, skip_video=False):
		self.config = load_config()
		logger.info("Loaded configuration:")
		logger.info(f"MQTT Settings - Host: {self.config['mqtt']['host']}, Port: {self.config['mqtt']['port']}")
		logger.info(f"MQTT Auth - Username: {'configured' if self.config['mqtt']['username'] else 'not configured'}")

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
			logger.info("Attempting to initialize MQTT handler...")
			self.ha_mqtt = HomeAssistantMQTT(
				host=self.config['mqtt']['host'],
				port=self.config['mqtt']['port'],
				username=self.config['mqtt']['username'],
				password=self.config['mqtt']['password']
			)
			logger.info("MQTT handler initialized successfully")
		except Exception as e:
			logger.error(f"Failed to initialize MQTT handler: {str(e)}")
			logger.error("MQTT will be disabled")
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

			# Publish to Home Assistant
			if self.ha_mqtt:
				try:
					# Open and resize image
					with Image.open(filepath) as img:
						# Calculate new size (1/4 of original)
						new_size = (img.width // 4, img.height // 4)
						resized_img = img.resize(new_size, Image.Resampling.LANCZOS)

						# Convert to JPEG bytes
						img_byte_arr = io.BytesIO()
						resized_img.save(img_byte_arr, format='JPEG', quality=70)
						img_byte_arr = img_byte_arr.getvalue()

						# Convert to base64
						img_base64 = base64.b64encode(img_byte_arr).decode('utf-8')
						img_size_kb = len(img_byte_arr) / 1024

						# Log size information
						logger.info(f"Image size before base64: {img_size_kb:.1f}KB")
						logger.info(f"Image dimensions after resize: {new_size[0]}x{new_size[1]}")

						# Publish to MQTT
						topic = f"{self.ha_mqtt.device_name}/camera/image"
						logger.info(f"Publishing resized image ({len(img_base64)} bytes) to {topic}")
						self.ha_mqtt.client.publish(topic, img_base64, retain=True)

						# Publish timestamp in ISO format
						now = datetime.now().isoformat()
						self.ha_mqtt.publish_state("last_capture", now)

						# Also publish the path for reference
						self.ha_mqtt.publish_state("latest_photo", str(filepath))
				except Exception as e:
					logger.error(f"Failed to publish image: {e}")
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
			self.ha_mqtt.publish_state("uptime", str(uptime))

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
				current_time = datetime.now(start_time.tzinfo)

				if start_time <= current_time <= end_time and self.capturing_enabled:
					self.take_photo()
					time.sleep(self.config['camera']['interval_minutes'] * 60)
				elif current_time > end_time:
					# Video creation temporarily disabled for stability testing
					logger.info("Video creation temporarily disabled for stability testing")
					# Wait until next day
					tomorrow = current_time + timedelta(days=1)
					tomorrow_start = tomorrow.replace(
						hour=start_time.hour,
						minute=start_time.minute,
						second=0,
						microsecond=0
					)
					sleep_seconds = min((tomorrow_start - current_time).total_seconds(), 60)
					logger.info(f"Waiting {sleep_seconds/3600:.1f} hours until next day")
					time.sleep(sleep_seconds)
					self.update_ha_status()  # Update status after long sleep
				else:
					# Wait until start time or until capturing is enabled
					sleep_seconds = min(
						(start_time - current_time).total_seconds(),
						60  # Check status every minute
					)
					logger.info(f"Waiting {sleep_seconds/3600:.1f} hours until start time")
					time.sleep(sleep_seconds)
					self.update_ha_status()  # Update status after sleep

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