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

TODO: Home Assistant Integration
- Add MQTT support to connect with Home Assistant
- Features to implement:
	* Show latest captured photo in HA
	* Add toggle switch to control capturing
	* Add uptime sensor
	* Publish system status
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
import logging
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
from astral import LocationInfo
from astral.sun import sun
import argparse

# Configure logging
logging.basicConfig(
		level=logging.INFO,
		format='%(asctime)s - %(levelname)s - %(message)s',
		handlers=[
				logging.FileHandler('/opt/timelapse/timelapse.log'),
				logging.StreamHandler()
		]
)
logger = logging.getLogger(__name__)

class TimelapseCamera:
		def __init__(self, test_mode=False, skip_video=False):
				self.camera = Picamera2()
				self.setup_camera()
				self.base_dir = Path('/opt/timelapse')
				self.photos_dir = self.base_dir / 'photos'
				self.videos_dir = self.base_dir / 'videos'
				self.setup_directories()
				self.test_mode = test_mode
				self.skip_video = skip_video

				# Default configuration
				self.config = {
						'latitude': 48.4639,  # Latitude for Eningen unter Achalm, Germany
						'longitude': 9.2075,  # Longitude for Eningen unter Achalm, Germany
						'timezone': 'Europe/Berlin',  # Timezone for Eningen unter Achalm, Germany
						'hours_before_sunrise': 1,
						'hours_after_sunset': 1,
						'interval_minutes': 1,
						'resolution': (1920, 1080),  # 1080p
						# Test mode settings
						'test_capture_count': 10,
						'test_interval_seconds': 2
				}

		def setup_camera(self):
				"""Initialize camera settings"""
				try:
						# Configure camera for 1080p
						camera_config = self.camera.create_still_configuration(
								main={"size": (1920, 1080)},
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
								latitude=self.config['latitude'],
								longitude=self.config['longitude'],
								timezone=self.config['timezone']
						)
						s = sun(location.observer, date=datetime.now())

						start_time = s['sunrise'] - timedelta(hours=self.config['hours_before_sunrise'])
						end_time = s['sunset'] + timedelta(hours=self.config['hours_after_sunset'])
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
						for i in range(self.config['test_capture_count']):
								logger.info(f"Taking test photo {i+1}/{self.config['test_capture_count']}")
								self.take_photo()
								time.sleep(self.config['test_interval_seconds'])

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
								start_time, end_time = self.get_sun_times()
								current_time = datetime.now(start_time.tzinfo)  # Make current_time timezone-aware

								if start_time <= current_time <= end_time:
										self.take_photo()
										time.sleep(self.config['interval_minutes'] * 60)
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
										# Wait until start time
										sleep_seconds = (start_time - current_time).total_seconds()
										logger.info(f"Waiting {sleep_seconds/3600:.1f} hours until start time")
										time.sleep(sleep_seconds)

						except Exception as e:
								logger.error(f"Error in main loop: {e}")
								time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
		parser = argparse.ArgumentParser(description='Timelapse Camera')
		parser.add_argument('--test', action='store_true', help='Run in test mode')
		parser.add_argument('--no-video', action='store_true', help='Skip video creation in test mode')
		args = parser.parse_args()

		camera = TimelapseCamera(test_mode=args.test, skip_video=args.no_video)
		camera.run()