#!/bin/bash

echo "===== TIMELAPSE CAMERA DIAGNOSTIC TOOL ====="
echo ""

# Check if timelapse service is running
echo "Checking timelapse service status..."
if systemctl is-active --quiet timelapse.service; then
    echo "✅ Timelapse service is RUNNING"
    echo "   This is likely using the camera already"
else
    echo "❌ Timelapse service is NOT running"
fi

# Check for any processes using the camera
echo ""
echo "Checking for processes using the camera..."
CAMERA_PROCESSES=$(lsof /dev/video* 2>/dev/null || echo "No processes found")
if [ "$CAMERA_PROCESSES" != "No processes found" ]; then
    echo "✅ Found processes using the camera:"
    echo "$CAMERA_PROCESSES"
else
    echo "❌ No processes found using the camera directly"
fi

# Check for libcamera processes
echo ""
echo "Checking for libcamera processes..."
LIBCAMERA_PROCESSES=$(ps aux | grep -i libcamera | grep -v grep)
if [ -n "$LIBCAMERA_PROCESSES" ]; then
    echo "✅ Found libcamera processes:"
    echo "$LIBCAMERA_PROCESSES"
else
    echo "❌ No libcamera processes found"
fi

# Check for Python processes running timelapse
echo ""
echo "Checking for Python processes running timelapse..."
TIMELAPSE_PROCESSES=$(ps aux | grep -i "python.*timelapse" | grep -v grep)
if [ -n "$TIMELAPSE_PROCESSES" ]; then
    echo "✅ Found Python processes running timelapse:"
    echo "$TIMELAPSE_PROCESSES"
else
    echo "❌ No Python processes running timelapse found"
fi

# Check camera device files
echo ""
echo "Checking camera device files..."
if [ -e /dev/video0 ]; then
    echo "✅ Camera device /dev/video0 exists"
    ls -la /dev/video*
else
    echo "❌ Camera device /dev/video0 not found"
fi

# Check media devices
echo ""
echo "Checking media devices..."
if [ -e /dev/media0 ]; then
    echo "✅ Media device /dev/media0 exists"
    ls -la /dev/media*
else
    echo "❌ Media device /dev/media0 not found"
fi

echo ""
echo "===== RECOMMENDED ACTIONS ====="
echo "1. If the timelapse service is running, stop it:"
echo "   sudo systemctl stop timelapse.service"
echo ""
echo "2. Kill any processes using the camera:"
echo "   sudo killall -9 python3"
echo "   sudo killall -9 libcamera"
echo ""
echo "3. Restart the camera subsystem:"
echo "   sudo systemctl restart libcamera"
echo ""
echo "4. Try running the timelapse script again:"
echo "   python3 /opt/timelapse/timelapse.py --web --web-port 8080"
echo ""
echo "5. If still having issues, try rebooting the Raspberry Pi:"
echo "   sudo reboot"