#!/bin/bash

# Check if the timelapse service is running
if systemctl is-active --quiet timelapse.service; then
    echo "Timelapse service is running."
    echo "This means the camera is already in use by the service."
    echo ""
    echo "Options:"
    echo "1. Stop the service: sudo systemctl stop timelapse.service"
    echo "2. Run the script with sudo: sudo python3 timelapse.py --web --web-port 8080"
    echo ""
    echo "To check service status: sudo systemctl status timelapse.service"
    echo "To view service logs: sudo journalctl -u timelapse.service"
else
    echo "Timelapse service is not running."
    echo "You can start it with: sudo systemctl start timelapse.service"
    echo "Or run the script directly: python3 timelapse.py --web --web-port 8080"
fi