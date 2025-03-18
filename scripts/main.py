#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk
import logging
import os
import time
import threading
import json
import base64
import argparse
import sys
import requests
from datetime import datetime
from enum import Enum
import numpy as np
from PIL import Image, ImageTk
import cv2
from threading import Lock

class SystemState(Enum):
    UNINITIALIZED = 0
    HOST_READING = 1
    SCANNING = 2
    WARNING = 3
    STOPPED = 4
    HOST_ACTIVE_STATE = 5
    HOST_STOPPED_STATE = 6




class HeartbeatPublisher:
    def __init__(self, ip="10.10.10.1", heartbeat_interval=1.0, debug=False):
        # Enable debug features
        self.debug = debug

        self.ip = ip
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_thread = None
        self.stop_flag = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def start_heartbeat(self):
        """Start heartbeat thread"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.logger.info("Heartbeat already running")
            return
            
        self.stop_flag = False
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_thread)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        self.logger.info("Started heartbeat thread")
    
    def stop_heartbeat(self):
        """Stop heartbeat thread"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.stop_flag = True
            self.heartbeat_thread.join(timeout=2.0)
            self.logger.info("Stopped heartbeat")
    
    def _heartbeat_thread(self):
        """Background thread for heartbeats"""
        heartbeat_count = 0
        
        while not self.stop_flag:
            try:
                # Send heartbeat
                if self.send_heartbeat():
                    heartbeat_count += 1
                else:
                    self.logger.warning("Failed to send heartbeat")
            except Exception as e:
                self.logger.error(f"Error in heartbeat thread: {e}")
            
            # Wait for next heartbeat
            time.sleep(self.heartbeat_interval)
    
    def send_heartbeat(self):
        """Send heartbeat to device"""
        try:
            # Standard JSON-RPC 2.0 format
            payload = {
                'id': 1,
                'jsonrpc': '2.0',
                'method': 'rx_from_host',
                'params': {
                    'host_state': 1
                }
            }
            
            response = requests.post(
                f'http://{self.ip}/jsonrpc',
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=1.0
            )
            
            if response.status_code != 200:
                self.logger.warning(f"HTTP error: {response.status_code}")
                return False
            
            return True
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error sending heartbeat: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error in heartbeat: {e}")
            return False


class DataSubscriber:
    def __init__(self, ip="10.10.10.1", poll_interval=0.1, debug=False):
        self.ip = ip
        self.poll_interval = poll_interval
        self.debug = debug
        self.poll_thread = None
        self.stop_flag = False
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Data storage - initialize all the data fields we'll access
        self.last_timestamp = 0
        self.last_system_state = SystemState.UNINITIALIZED
        self.last_inference_time = 0
        self.last_depth_estimation_time = 0
        self.last_detection_data = None
        self.last_depth_data = None
        self.last_camera_data = None
        
        # Thread safety
        self.data_lock = Lock()
        
        # Recording state
        self.is_recording = False
        self.data_dir = None
        self.csv_path = None
        
        # Stats
        self.received_count = 0
        self.error_count = 0
        self.detection_counts = []

    def start_polling(self):
        """Start polling for logging data"""
        if self.poll_thread and self.poll_thread.is_alive():
            self.logger.info("Polling already running")
            return
            
        self.stop_flag = False
        self.poll_thread = threading.Thread(target=self._poll_thread)
        self.poll_thread.daemon = True
        self.poll_thread.start()
        self.logger.info("Started data polling thread")
    
    def stop_polling(self):
        """Stop polling thread"""
        if self.poll_thread and self.poll_thread.is_alive():
            self.stop_flag = True
            self.poll_thread.join(timeout=2.0)
            self.logger.info("Stopped data polling")
    
    def _poll_thread(self):
        """Background thread for polling logging data"""
        self.logger.info("Polling thread started")
        
        while not self.stop_flag:
            try:
                data = self.fetch_logging_data()
                if data:
                    self.process_logging_data(data)
                    self.received_count += 1
                time.sleep(self.poll_interval)
                    
            except Exception as e:
                self.error_count += 1
                self.logger.error(f"Error in polling thread: {e}")
                time.sleep(1.0)  # Longer delay on error
    
    def fetch_logging_data(self):
        """Fetch logging data from the device"""
        try:
            # Standard JSON-RPC 2.0 format
            payload = {
                'id': 1,
                'jsonrpc': '2.0',
                'method': 'tx_logs_to_host',
                'params': {}
            }
            
            response = requests.post(
                f'http://{self.ip}/jsonrpc',
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=2.0
            )
            
            if response.status_code != 200:
                self.logger.warning(f"HTTP error: {response.status_code}")
                return None
            
            # Parse the response
            result = response.json()
            if 'error' in result:
                self.logger.warning(f"RPC error: {result['error']}")
                return None
                
            if 'result' not in result:
                self.logger.warning("No result in response")
                return None
                
            return result['result']
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request error fetching logging data: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching logging data: {e}")
            return None
            
    def process_logging_data(self, data):
        """Process received logging data"""
        try:
            # Parse basic metadata
            timestamp = data.get('timestamp', 0)
            system_state_int = data.get('system_state', 0)
            system_state = SystemState(system_state_int) if 0 <= system_state_int < len(SystemState) else "UNKNOWN"
            detection_count = data.get('detection_count', 0)
            inference_time = data.get('inference_time', 0)
            depth_estimation_time = data.get('depth_estimation_time', 0)
            
            # Thread-safe update of state tracking
            with self.data_lock:
                self.last_timestamp = timestamp
                self.last_system_state = system_state
                self.last_inference_time = inference_time
                self.last_depth_estimation_time = depth_estimation_time
                
                # Process detection data if available
                if 'detections' in data:
                    # Decode base64 detection data if there are detections
                    if detection_count > 0:
                        detection_bytes = base64.b64decode(data['detections'])
                        detection_data = self._parse_detections(detection_bytes, detection_count)
                        self.last_detection_data = detection_data
                        
                        # For stats tracking
                        self.detection_counts.append(detection_count)
                        
                        # Process depth data if available
                        if 'depths' in data:
                            depth_bytes = base64.b64decode(data['depths'])
                            depth_data = self._parse_depths(depth_bytes, detection_count)
                            self.last_depth_data = depth_data
                    else:
                        # Clear detection data when no detections are present
                        self.logger.debug("No detections in this frame, clearing last detection data")
                        self.last_detection_data = None
                        self.last_depth_data = None
                    
                if 'image_data' in data and data.get('cam_width') and data.get('cam_height'):
                    try:
                        width = data.get('cam_width')
                        height = data.get('cam_height')
                        image_bytes = base64.b64decode(data['image_data'])
                        
                        # Convert bytes to numpy array right away to verify format
                        img_data = np.frombuffer(image_bytes, dtype=np.uint8)
                        
                        # Check if the size matches what we expect
                        expected_size = width * height * 3  # Assuming RGB format (3 bytes per pixel)
                        if len(img_data) != expected_size:
                            self.logger.warning(f"Image data size mismatch: got {len(img_data)}, expected {expected_size}")
                            # Try to determine if it's a different format or needs reshaping
                            
                        # Store camera data - store the actual numpy array
                        self.last_camera_data = {
                            'width': width,
                            'height': height,
                            'format': data.get('cam_format', 0),
                            'timestamp': data.get('cam_timestamp', 0),
                            'img_bytes': image_bytes,
                            'img_array': img_data.reshape((height, width, 3)) if len(img_data) == expected_size else None
                        }
                        
                    except Exception as img_err:
                        self.logger.error(f"Error processing image data: {img_err}", exc_info=True)
            


            # If recording, save to CSV log (outside the lock to minimize lock time)
            if self.is_recording and self.csv_path:
                with open(self.csv_path, 'a') as f:
                    f.write(f"{timestamp},{system_state_int},{detection_count},{inference_time},{depth_estimation_time}\n")
                
                # Save detection data when recording
                if detection_count > 0:
                    with self.data_lock:  # Re-acquire lock to safely access the data
                        self._save_detection_data(timestamp, self.last_detection_data, self.last_depth_data)
                        
                        # If recording, save image if detections present
                        if self.last_camera_data:
                            img_path = os.path.join(self.data_dir, f"image_{timestamp}.jpg")

                            img_data = np.frombuffer(self.last_camera_data['img_bytes'], dtype=np.uint8)
                            img_data = img_data.reshape((height, width, 3))
                            frame = Image.fromarray(img_data)

                            frame.save(img_path)
        
        except Exception as e:
            self.logger.error(f"Error processing logging data: {e}")
    
    def _parse_detections(self, detection_bytes, count):
        """Parse binary detection data according to tensorflow::Object structure
        
        Structure:
        - id (int)
        - score (float)
        - bbox (BBox<float>):
          - ymin (float)
          - xmin (float)
          - ymax (float)
          - xmax (float)
        """
        try:
            detection_data = {
                'count': count,
                'objects': []
            }
            
            # Calculate the size of each Object struct
            # int + float + 4 floats for bbox = 24 bytes (on most platforms)
            # This might need adjustment based on alignment/padding
            object_size = 4 + 4 + (4 * 4)  # int + float + 4 floats
            
            for i in range(count):
                # Calculate offset for this object
                offset = i * object_size
                
                # Ensure we have enough data
                if offset + object_size > len(detection_bytes):
                    self.logger.warning(f"Detection data too short for object {i}")
                    break
                
                # Parse components
                obj_id = int.from_bytes(detection_bytes[offset:offset+4], byteorder='little')
                offset += 4
                
                score = np.frombuffer(detection_bytes[offset:offset+4], dtype=np.float32)[0]
                offset += 4
                
                # Parse BBox
                ymin = np.frombuffer(detection_bytes[offset:offset+4], dtype=np.float32)[0]
                offset += 4
                xmin = np.frombuffer(detection_bytes[offset:offset+4], dtype=np.float32)[0]
                offset += 4
                ymax = np.frombuffer(detection_bytes[offset:offset+4], dtype=np.float32)[0]
                offset += 4
                xmax = np.frombuffer(detection_bytes[offset:offset+4], dtype=np.float32)[0]
                
                # Add to objects list
                detection_data['objects'].append({
                    'id': obj_id,
                    'score': float(score),
                    'bbox': {
                        'ymin': float(ymin),
                        'xmin': float(xmin),
                        'ymax': float(ymax),
                        'xmax': float(xmax)
                    }
                })
            
            return detection_data
            
        except Exception as e:
            self.logger.error(f"Error parsing detection data: {e}")
            return {'count': 0, 'objects': []}
    
    def _parse_depths(self, depth_bytes, count):
        """Parse binary depth data"""
        try:
            # Parse as array of floats
            depths = np.frombuffer(depth_bytes, dtype=np.float32, count=count)
            return {
                'count': count,
                'depths': depths.tolist()
            }
            
        except Exception as e:
            self.logger.error(f"Error parsing depth data: {e}")
            return {'count': 0, 'depths': []}
    
    def _save_detection_data(self, timestamp, detection_data, depth_data):
        """Save detection and depth data to file"""
        try:
            # Create a combined data structure
            data = {
                'timestamp': timestamp,
                'system_state': str(self.last_system_state),
                'detection_count': detection_data['count'],
                'detections': detection_data.get('objects', []),
                'depths': depth_data.get('depths', []) if depth_data else []
            }
            
            # Save to JSON file
            filename = os.path.join(self.data_dir, f"detection_{timestamp}.json")
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"Error saving detection data: {e}")
    
    def toggle_recording(self):
        """Toggle recording state"""
        if self.is_recording:
            self.is_recording = False
            self.logger.info("Stopped recording")
            return False
        else:
            # Create data directory
            self.data_dir = os.path.join("logs", datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.data_dir, exist_ok=True)
            
            # Setup CSV log file
            self.csv_path = os.path.join(self.data_dir, "detection_log.csv")
            with open(self.csv_path, 'w') as f:
                f.write("timestamp,system_state,detection_count,inference_time,depth_estimation_time\n")
            

            self.is_recording = True
            self.logger.info(f"Started recording to {self.data_dir}")
            return True
    
    def get_current_frame(self):
        """Get current frame"""
        with self.data_lock:
            if not self.last_camera_data:
                return None
            
            try:
                # Check if we have pre-processed array
                if 'img_array' in self.last_camera_data and self.last_camera_data['img_array'] is not None:
                    frame = self.last_camera_data['img_array'].copy()
                else:
                    # Fallback to processing the bytes
                    image_data = self.last_camera_data['img_bytes']
                    width = self.last_camera_data['width']
                    height = self.last_camera_data['height']
                    
                    try:
                        frame = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 3))
                    except ValueError as e:
                        self.logger.error(f"Error reshaping image data: {e}, data size={len(image_data)}, expected={(height*width*3)}")
                        return None
                
                # If we have detection data, draw it on the frame
                if self.last_detection_data and self.last_detection_data.get('count', 0) > 0:
                    frame = self._draw_detections(frame.copy())
                
                # Convert to PIL Image for tkinter
                return Image.fromarray(frame)
            
            except Exception as e:
                self.logger.error(f"Error getting current frame: {e}", exc_info=True)
                return None
        
    def _draw_detections(self, frame):
        """Draw detection boxes and info on frame"""
        try:
            if not self.last_detection_data or self.last_detection_data.get('count', 0) == 0:
                        # No detections to draw
                        return frame

            height, width = frame.shape[:2]
            

            for i, obj in enumerate(self.last_detection_data.get('objects', [])):

                bbox = obj['bbox']

                # Use absolute coordinates directly, just ensure they're in bounds
                ymin = max(0, min(int(bbox['ymin']), height-1))
                xmin = max(0, min(int(bbox['xmin']), width-1))
                ymax = max(0, min(int(bbox['ymax']), height-1))
                xmax = max(0, min(int(bbox['xmax']), width-1))
                
                # Draw bounding box
                cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
                
                # Get depth if available
                depth_text = ""
                if self.last_depth_data and i < len(self.last_depth_data.get('depths', [])):
                    depth = self.last_depth_data['depths'][i]
                    depth_text = f"Dist: {int(depth)}mm"
                
                # Create label with ID, confidence, and depth
                label = f"ID: {obj['id']}, Conf: {obj['score']:.2f}"
                if depth_text:
                    label += f", {depth_text}"
                
                # Draw label background
                label_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(frame, 
                              (xmin, ymin - label_size[1] - 10), 
                              (xmin + label_size[0], ymin), 
                              (0, 255, 0), 
                              -1)
                
                # Draw label text
                cv2.putText(frame, 
                            label, 
                            (xmin, ymin - 7), 
                            cv2.FONT_HERSHEY_SIMPLEX, 
                            0.5, 
                            (0, 0, 0), 
                            1)
            
            return frame
            
        except Exception as e:
            self.logger.error(f"Error drawing detections: {e}")
            return frame
    
    def get_status_info(self):
        """Get current status information"""
        with self.data_lock:
            return {
                'timestamp': self.last_timestamp,
                'inference_time': self.last_inference_time,
                'depth_estimation_time': self.last_depth_estimation_time,
                'system_state': self.last_system_state,
                'detection_count': self.last_detection_data.get('count', 0) if self.last_detection_data else 0
            }


class Visualizer:
    def __init__(self, data_subscriber):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.data_subscriber = data_subscriber
        
        # Setup main window
        self.root = tk.Tk()
        self.root.title("Data Stream Visualizer")
        self.root.geometry("800x700")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self.create_gui()
    
    def create_gui(self):
        """Create GUI components"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Info header
        info_frame = ttk.LabelFrame(main_frame, text="Stream Information")
        info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Info grid
        info_grid = ttk.Frame(info_frame)
        info_grid.pack(fill=tk.X, padx=5, pady=5)
        
        # Timestamp info
        ttk.Label(info_grid, text="Timestamp:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.timestamp_var = tk.StringVar(value="--")
        ttk.Label(info_grid, textvariable=self.timestamp_var).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Detection time info
        ttk.Label(info_grid, text="Detection Time:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.detection_time_var = tk.StringVar(value="--")
        ttk.Label(info_grid, textvariable=self.detection_time_var).grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Depth estimation time
        ttk.Label(info_grid, text="Depth Time:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        self.depth_time_var = tk.StringVar(value="--")
        ttk.Label(info_grid, textvariable=self.depth_time_var).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        
        # System state
        ttk.Label(info_grid, text="System State:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        self.system_state_var = tk.StringVar(value="--")
        ttk.Label(info_grid, textvariable=self.system_state_var).grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
        
        # Detection count
        ttk.Label(info_grid, text="Detections:").grid(row=1, column=2, sticky=tk.W, padx=5, pady=2)
        self.detection_count_var = tk.StringVar(value="--")
        ttk.Label(info_grid, textvariable=self.detection_count_var).grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
        
        # Recording status
        ttk.Label(info_grid, text="Recording:").grid(row=2, column=2, sticky=tk.W, padx=5, pady=2)
        self.recording_var = tk.StringVar(value="OFF")
        self.recording_label = ttk.Label(info_grid, textvariable=self.recording_var)
        self.recording_label.grid(row=2, column=3, sticky=tk.W, padx=5, pady=2)
        
        # Image display
        self.image_frame = ttk.LabelFrame(main_frame, text="RGB Stream")
        self.image_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.image_label = ttk.Label(self.image_frame)
        self.image_label.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Control buttons
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.record_button = ttk.Button(control_frame, text="Record Data", command=self.toggle_recording)
        self.record_button.pack(side=tk.LEFT, padx=5, pady=5)
        
        ttk.Button(control_frame, text="Exit", command=self.on_close).pack(side=tk.RIGHT, padx=5, pady=5)
    
    def update_display(self):
        """Update display with latest data"""
        # Update info variables
        status = self.data_subscriber.get_status_info()
        
        if status['timestamp']:
            self.timestamp_var.set(f"{status['timestamp']}")
        
        if status['inference_time'] is not None:
            self.detection_time_var.set(f"{status['inference_time']:.2f} ms")
        
        if status['depth_estimation_time'] is not None:
            self.depth_time_var.set(f"{status['depth_estimation_time']:.2f} ms")
        
        if status['system_state']:
            self.system_state_var.set(f"{status['system_state']}")
        
        self.detection_count_var.set(f"{status['detection_count']}")
        
        # Update image - this needs to be stored to prevent garbage collection
        frame = self.data_subscriber.get_current_frame()
        if frame is not None:
            # Convert to PhotoImage and update display
            self.photo = ImageTk.PhotoImage(frame)  # Store as instance variable
            self.image_label.configure(image=self.photo)
        
        # Schedule next update
        self.root.after(33, self.update_display)  # ~30 FPS
    
    def toggle_recording(self):
        """Toggle recording state"""
        is_recording = self.data_subscriber.toggle_recording()
        
        if is_recording:
            self.recording_var.set("ON")
            self.recording_label.configure(foreground="red")
            self.record_button.configure(text="Stop Recording")
        else:
            self.recording_var.set("OFF")
            self.recording_label.configure(foreground="black")
            self.record_button.configure(text="Record Data")
    
    def on_close(self):
        """Handle window close event"""
        self.logger.info("Shutting down...")
        self.root.destroy()
    
    def run(self):
        """Start visualizer"""
        # Start data services
        self.data_subscriber.start_polling()
        
        # Start display updates
        self.root.after(100, self.update_display)
        
        # Start main loop
        self.root.mainloop()


def setup_logging(enable_debug=False):
    """Setup logging configuration"""
    # Create logs directory
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # Configure logging
    log_level = logging.DEBUG if enable_debug else logging.INFO
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Setup handlers
    handlers = [
        logging.StreamHandler(sys.stdout)
    ]
    
    # Add file handler if debug is enabled
    if enable_debug:
        log_file = os.path.join(log_dir, f"visualizer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        file_handler = logging.FileHandler(log_file)
        handlers.append(file_handler)
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=handlers
    )
    
    return logging.getLogger("main")


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Data Stream Visualizer')
    parser.add_argument('--ip', type=str, default='10.10.10.1', help='Device IP address')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode (no GUI)')
    
    return parser.parse_args()


def main():
    """Main entry point"""
    # Parse arguments
    args = parse_args()
    
    # Setup logging
    logger = setup_logging(args.debug)
    logger.info(f"Starting Data Stream Visualizer - connecting to {args.ip}")
    
    try:
        # Create components
        data_subscriber = DataSubscriber(ip=args.ip, debug=args.debug)
        heartbeat_publisher = HeartbeatPublisher(ip=args.ip, debug=args.debug)

        # Start the heartbeat publisher regardless of mode
        heartbeat_publisher.start_heartbeat()

        if not args.headless:
            # Start GUI visualizer
            visualizer = Visualizer(data_subscriber)
            visualizer.run()
        else:
            # Run in headless mode (no GUI)
            logger.info("Starting in headless mode")
            data_subscriber.start_polling()
            
            # Keep the main thread alive
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, shutting down")
                heartbeat_publisher.stop_heartbeat()
                data_subscriber.stop_polling()

            finally:
                heartbeat_publisher.stop_heartbeat()
                data_subscriber.stop_polling()
                logger.info("Stopped all services")
        
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())