#!/bin/bash

echo "===== TIMELAPSE CAMERA FIX TOOL ====="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run as root (with sudo)"
    echo "   Please run: sudo $0"
    exit 1
fi

# Stop the timelapse service
echo "Stopping timelapse service..."
systemctl stop timelapse.service
echo "✅ Timelapse service stopped"

# Kill any Python processes running timelapse
echo "Killing any Python processes running timelapse..."
pkill -f "python.*timelapse" || echo "No timelapse Python processes found"
echo "✅ Python processes killed"

# Kill any libcamera processes
echo "Killing any libcamera processes..."
pkill -f libcamera || echo "No libcamera processes found"
echo "✅ Libcamera processes killed"

# Restart the camera subsystem
echo "Restarting camera subsystem..."
systemctl restart libcamera || echo "Could not restart libcamera service"
echo "✅ Camera subsystem restarted"

# Wait a moment for everything to settle
echo "Waiting for system to settle..."
sleep 2

echo ""
echo "===== CAMERA SHOULD NOW BE AVAILABLE ====="
echo "Try running the timelapse script again:"
echo "python3 /opt/timelapse/timelapse.py --web --web-port 8080"
echo ""
echo "If you still have issues, you may need to reboot:"
echo "sudo reboot"