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
from datetime import datetime, timedelta, timezone
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
import threading
from flask import Flask, render_template, Response, jsonify, request
import cv2
from libcamera import controls
import numpy as np
import libcamera

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
			"unit_of_measurement": "minutes",
			"device_class": "duration",
			"state_class": "measurement",
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
		logger.info(f"Publishing to {topic}: {state}")
		result, mid = self.client.publish(topic, state, retain=True)
		logger.info(f"Publish result: {result} (0=success) with message ID: {mid}")

	def disconnect(self):
		"""Disconnect from MQTT broker"""
		self.client.loop_stop()
		self.client.disconnect()

class CameraWebInterface:
	def __init__(self, camera_instance, port=8000):
		self.camera = camera_instance
		self.app = Flask(__name__)
		self.port = port
		self.log_file = Path(config['paths']['base_dir']) / config['paths']['log_file']
		self.setup_routes()

	def setup_routes(self):
		@self.app.route('/')
		def index():
			last_capture_time = "No captures yet"
			if hasattr(self.camera, 'last_capture_time') and self.camera.last_capture_time:
				last_capture_time = self.camera.last_capture_time.strftime("%Y-%m-%d %H:%M:%S")
			return render_template('index.html',
								capturing=self.camera.capturing_enabled,
								preview_mode=self.camera.preview_mode,
								last_capture_time=last_capture_time)

		@self.app.route('/logs/latest')
		def get_latest_log():
			try:
				# Get the last line from the log file
				with open(self.log_file, 'r') as f:
					lines = f.readlines()
					if lines:
						return jsonify({'line': lines[-1].strip()})
					return jsonify({'line': 'No logs available'})
			except Exception as e:
				logger.error(f"Error reading latest log: {e}")
				return jsonify({'line': 'Error reading logs'})

		@self.app.route('/logs/recent')
		def get_recent_logs():
			try:
				num_lines = min(int(request.args.get('lines', 100)), 1000)  # Cap at 1000 lines
				with open(self.log_file, 'r') as f:
					# Read all lines and get the last n lines
					lines = f.readlines()
					recent_logs = lines[-num_lines:] if len(lines) > num_lines else lines
					return jsonify({'logs': [line.strip() for line in recent_logs]})
			except Exception as e:
				logger.error(f"Error reading recent logs: {e}")
				return jsonify({'logs': ['Error reading logs']})

		@self.app.route('/status')
		def status():
			current_time = datetime.now(tz=timezone(self.camera.config['location']['timezone']))
			start_time, end_time = self.camera.get_sun_times()

			status_info = {
				'capturing_enabled': self.camera.capturing_enabled,
				'preview_mode': self.camera.preview_mode,
				'last_capture_time': self.camera.last_capture_time.strftime("%Y-%m-%d %H:%M:%S") if self.camera.last_capture_time else None,
				'uptime_minutes': int((time.time() - self.camera.start_time) / 60),
				'sun_times': {
					'start': start_time.strftime("%H:%M"),
					'end': end_time.strftime("%H:%M")
				},
				'status_message': None
			}

			# Determine status message
			if current_time < start_time:
				status_info['status_message'] = f"Waiting for sunrise capture time ({start_time.strftime('%H:%M')})"
			elif current_time > end_time:
				status_info['status_message'] = f"Capture ended for today (sunset was at {end_time.strftime('%H:%M')})"
			elif not self.camera.capturing_enabled:
				status_info['status_message'] = "Capture manually disabled"
			elif self.camera.preview_mode:
				status_info['status_message'] = "Live preview mode active"
			else:
				status_info['status_message'] = "Capturing enabled"

			return jsonify(status_info)

		@self.app.route('/capture/start', methods=['POST'])
		def start_capture():
			if self.camera.preview_mode:
				return jsonify({'error': 'Cannot start capture while in preview mode'}), 400
			self.camera.start_capture()
			return jsonify({'success': True, 'capturing': True})

		@self.app.route('/capture/stop', methods=['POST'])
		def stop_capture():
			self.camera.stop_capture()
			return jsonify({'success': True, 'capturing': False})

		@self.app.route('/mode/preview', methods=['POST'])
		def set_preview_mode():
			self.camera.start_preview()
			return jsonify({
				'success': True,
				'preview_mode': True,
				'capturing_enabled': self.camera.capturing_enabled
			})

		@self.app.route('/mode/capture', methods=['POST'])
		def set_capture_mode():
			self.camera.stop_preview()
			return jsonify({
				'success': True,
				'preview_mode': False,
				'capturing_enabled': self.camera.capturing_enabled
			})

		@self.app.route('/stream')
		def stream():
			return Response(self.generate_frames(),
						  mimetype='multipart/x-mixed-replace; boundary=frame')

		@self.app.route('/last_image')
		def last_image():
			if hasattr(self.camera, 'last_capture_path') and self.camera.last_capture_path:
				try:
					if not Path(self.camera.last_capture_path).exists():
						logger.warning(f"Last capture file not found: {self.camera.last_capture_path}")
						return Response(status=404)

					with open(self.camera.last_capture_path, 'rb') as f:
						return Response(f.read(), mimetype='image/jpeg')
				except Exception as e:
					logger.error(f"Error reading last captured image: {e}")
			return Response(status=404)

		@self.app.route('/last_capture_time')
		def last_capture_time():
			if hasattr(self.camera, 'last_capture_time') and self.camera.last_capture_time:
				return jsonify({
					'timestamp': self.camera.last_capture_time.strftime("%Y-%m-%d %H:%M:%S")
				})
			return jsonify({'timestamp': 'No captures yet'})

		@self.app.route('/focus/set', methods=['POST'])
		def set_focus():
			value = request.json.get('value', 50)
			self.camera.set_focus(value)
			return jsonify({'status': 'success'})

		@self.app.route('/focus/auto', methods=['POST'])
		def auto_focus():
			self.camera.set_auto_focus()
			return jsonify({'status': 'success'})

	def generate_frames(self):
		while True:
			frame = self.camera.get_preview_frame()
			if frame is not None:
				ret, buffer = cv2.imencode('.jpg', frame)
				if ret:
					frame_bytes = buffer.tobytes()
					yield (b'--frame\r\n'
						   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
			time.sleep(0.1)

	def run(self):
		self.app.run(host='0.0.0.0', port=self.port, debug=False, threaded=True)

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
		self.preview_mode = False
		self.preview_lock = threading.Lock()
		self.last_capture_time = None
		self.last_capture_path = None
		self.service_state_file = self.base_dir / "service_state.json"
		self.load_service_state()

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
			# Configure camera for 4K
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

	def load_service_state(self):
		"""Load service state from file"""
		try:
			if self.service_state_file.exists():
				with open(self.service_state_file, 'r') as f:
					state = json.load(f)
					self.capturing_enabled = state.get('capturing_enabled', True)
					logger.info(f"Loaded service state: capturing_enabled={self.capturing_enabled}")
			else:
				self.save_service_state()
		except Exception as e:
			logger.error(f"Error loading service state: {e}")

	def save_service_state(self):
		"""Save service state to file"""
		try:
			state = {
				'capturing_enabled': self.capturing_enabled,
				'last_update': datetime.now().isoformat()
			}
			with open(self.service_state_file, 'w') as f:
				json.dump(state, f)
			logger.info(f"Saved service state: capturing_enabled={self.capturing_enabled}")
		except Exception as e:
			logger.error(f"Error saving service state: {e}")

	def start_preview(self):
		"""Switch to preview mode"""
		with self.preview_lock:
			# Temporarily disable capturing while in preview mode
			was_capturing = self.capturing_enabled
			if was_capturing:
				logger.info("Temporarily disabling capture for preview mode")
				self.capturing_enabled = False
				self.save_service_state()

			# Stop camera before reconfiguring
			logger.info("Stopping camera for preview mode configuration")
			self.camera.stop()

			self.preview_mode = True
			# Configure camera for preview (lower res for performance)
			preview_config = self.camera.create_preview_configuration(
				main={"size": (640, 480)},  # Simplified configuration
				transform=libcamera.Transform(hflip=0, vflip=0),
				buffer_count=1  # Reduce buffer count
			)
			self.camera.configure(preview_config)

			# Restart camera with new configuration
			logger.info("Starting camera in preview mode")
			self.camera.start()

			# Allow time for AWB and exposure to settle
			time.sleep(0.5)

	def stop_preview(self):
		"""Switch back to capture mode"""
		with self.preview_lock:
			self.preview_mode = False

			# Stop camera before reconfiguring
			logger.info("Stopping camera for capture mode configuration")
			self.camera.stop()

			# Restore full resolution configuration
			capture_config = self.camera.create_still_configuration(
				main={"size": (3840, 2160)},  # Simplified configuration
				transform=libcamera.Transform(hflip=0, vflip=0),
				buffer_count=1  # Single buffer for capture
			)
			self.camera.configure(capture_config)

			# Restart camera with new configuration
			logger.info("Starting camera in capture mode")
			self.camera.start()

			# Restore previous capture state
			self.load_service_state()
			logger.info(f"Restored capture state: capturing_enabled={self.capturing_enabled}")

	def get_preview_frame(self):
		"""Get a frame for the web preview"""
		with self.preview_lock:
			if not self.preview_mode:
				return None
			try:
				# Capture and convert to BGR for OpenCV
				frame = self.camera.capture_array()
				# Convert RGB to BGR for OpenCV
				frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
				return frame
			except Exception as e:
				logger.error(f"Error capturing preview frame: {e}")
				return None

	def take_photo(self):
		"""Capture a single photo with timestamp"""
		with self.preview_lock:
			# If we're in preview mode, switch back temporarily
			was_previewing = self.preview_mode
			if was_previewing:
				self.stop_preview()

			try:
				timestamp = datetime.now()
				filename = f"photo_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
				filepath = self.photos_dir / filename

				self.camera.capture_file(str(filepath))
				logger.info(f"Photo captured: {filename}")

				# Update last capture information
				self.last_capture_time = timestamp
				self.last_capture_path = str(filepath)

				# Publish to Home Assistant
				if self.ha_mqtt:
					try:
						# Open and resize image
						with Image.open(filepath) as img:
							# Calculate new size (1/8 of original)
							new_size = (img.width // 8, img.height // 8)
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

							# Publish timestamp in ISO format with timezone
							now = datetime.now().astimezone().isoformat()
							self.ha_mqtt.publish_state("last_capture", now)

							# Also publish the path for reference
							self.ha_mqtt.publish_state("latest_photo", str(filepath))
					except Exception as e:
						logger.error(f"Failed to publish image: {e}")
			finally:
				# Restore preview if we were in preview mode
				if was_previewing:
					self.start_preview()

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
			# Update uptime (convert to minutes)
			uptime_minutes = int((time.time() - self.start_time) / 60)
			self.ha_mqtt.publish_state("uptime", str(uptime_minutes))

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

	def set_focus(self, value):
		"""Set manual focus value"""
		with self.preview_lock:
			if not self.preview_mode:
				logger.warning("Cannot set focus while not in preview mode")
				return False
			if self.camera:
				try:
					# Convert 0-100 value to appropriate focus range
					focus_value = int((value / 100.0) * 1000)  # Adjust range as needed
					self.camera.set_controls({"AfMode": controls.AfModeEnum.Manual,
											"LensPosition": focus_value})
					return True
				except Exception as e:
					logger.error(f"Error setting focus: {e}")
					return False
			return False

	def set_auto_focus(self):
		"""Enable auto focus"""
		with self.preview_lock:
			if not self.preview_mode:
				logger.warning("Cannot set focus while not in preview mode")
				return False
			if self.camera:
				try:
					self.camera.set_controls({"AfMode": controls.AfModeEnum.Continuous})
					return True
				except Exception as e:
					logger.error(f"Error setting auto focus: {e}")
					return False
			return False

	def start_capture(self):
		"""Enable capture mode"""
		self.capturing_enabled = True
		self.save_service_state()
		logger.info("Capture mode enabled")

	def stop_capture(self):
		"""Disable capture mode"""
		self.capturing_enabled = False
		self.save_service_state()
		logger.info("Capture mode disabled")

if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='Timelapse Camera Control')
	parser.add_argument('--test', action='store_true', help='Run in test mode')
	parser.add_argument('--no-video', action='store_true', help='Skip video creation in test mode')
	parser.add_argument('--web', action='store_true', help='Start web interface')
	parser.add_argument('--web-port', type=int, default=8000, help='Web interface port')
	parser.add_argument('--capture', action='store_true', help='Run in capture mode (based on sunrise/sunset)')
	args = parser.parse_args()

	camera = TimelapseCamera(test_mode=args.test, skip_video=args.no_video)

	try:
		if args.web and args.capture:
			# Run both web interface and capture
			web_interface = CameraWebInterface(camera, port=args.web_port)
			web_thread = threading.Thread(target=web_interface.run)
			web_thread.daemon = True
			web_thread.start()
			camera.run()
		elif args.web:
			# Run only web interface
			web_interface = CameraWebInterface(camera, port=args.web_port)
			camera.capturing_enabled = False  # Start with capture disabled
			web_interface.run()  # This will block
		elif args.capture:
			# Run only capture functionality
			camera.run()
		else:
			parser.print_help()
	finally:
		camera.cleanup()