#!/usr/bin/env python3
# Andon system client application for logging data

import json
import sys
import time
import requests
import threading
import base64

import logging
import argparse
import os
from datetime import datetime
from enum import Enum
import sys

from PIL import Image, ImageTk
import cv2
import numpy as np

import tkinter as tk
from tkinter import ttk


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
                    if heartbeat_count % 5 == 0:  # Only log every 5 heartbeats
                        self.logger.info(f"Sent heartbeat #{heartbeat_count}")
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


class LoggingDataSubscriber:
    def __init__(self, ip="10.10.10.1", poll_interval=0.1, debug=False):
        
        # Enable debug features
        self.debug = debug

        self.ip = ip

        self.poll_interval = poll_interval
        self.poll_thread = None
        self.stop_flag = False
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Data storage
        self.last_system_state = None
        self.last_detection_data = None
        self.last_depth_data = None
        self.last_camera_data = None
        self.last_timestamp = None
        
        # Stats
        self.received_count = 0
        self.error_count = 0
        self.detection_counts = []
        
        # Create data directory
        if self.debug:
            self.data_dir = os.path.join("logs", datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.data_dir, exist_ok=True)
            
            # Setup CSV log file
            self.csv_path = os.path.join(self.data_dir, "detection_log.csv")
            with open(self.csv_path, 'w') as f:
                f.write("timestamp,system_state,detection_count,inference_time,depth_estimation_time\n")

    def start_polling(self):
        """Start polling for logging data"""
        if self.poll_thread and self.poll_thread.is_alive():
            self.logger.info("Polling already running")
            return
            
        self.stop_flag = False
        self.poll_thread = threading.Thread(target=self._poll_thread)
        self.poll_thread.daemon = True
        self.poll_thread.start()
        self.logger.info("Started logging data polling thread")
    
    def stop_polling(self):
        """Stop polling thread"""
        if self.poll_thread and self.poll_thread.is_alive():
            self.stop_flag = True
            self.poll_thread.join(timeout=2.0)
            self.logger.info("Stopped logging data polling")
    
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
            system_state = SystemState(system_state_int) if 0 <= system_state_int <= len(SystemState) else "UNKNOWN"
            detection_count = data.get('detection_count', 0)
            inference_time = data.get('inference_time', 0)
            depth_estimation_time = data.get('depth_estimation_time', 0)
            
            # Update state tracking
            self.last_timestamp = timestamp
            self.last_system_state = system_state
            
            if self.debug:
                # Save to CSV log
                with open(self.csv_path, 'a') as f:
                    f.write(f"{timestamp},{system_state_int},{detection_count},{inference_time},{depth_estimation_time}\n")
            
            # Process detection data if available
            if 'detections' in data and detection_count > 0:
                # Decode base64 detection data
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
                
                # Save detection data to file when people are detected
                if self.debug and detection_count > 0:
                    self._save_detection_data(timestamp, detection_data, depth_data)
            
            # Process camera image if available
            if 'image_data' in data and data.get('cam_width') and data.get('cam_height'):
                try:
                    width = data.get('cam_width')
                    height = data.get('cam_height')
                    image_bytes = base64.b64decode(data['image_data'])
                    
                    # Store camera data
                    self.last_camera_data = {
                        'width': width,
                        'height': height,
                        'format': data.get('cam_format', 0),
                        'timestamp': data.get('cam_timestamp', 0),
                        'data': image_bytes
                    }
                    
                    if self.debug:
                        if detection_count > 0:
                            # Save image if detections are present
                            cv2.imwrite(os.path.join(self.data_dir, f"image_{timestamp}.jpg"), np.frombuffer(image_bytes, dtype=np.uint8).reshape((height, width, 3)))
                        
                except Exception as img_err:
                    self.logger.error(f"Error processing image data: {img_err}")
        
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
    
    def _save_image(self, timestamp, width, height, image_bytes):
        """Save camera image to file"""
        try:
            # Create a filename
            filename = os.path.join(self.data_dir, f"image_{timestamp}.rgb")
            
            # Write raw image data
            with open(filename, 'wb') as f:
                f.write(image_bytes)
                
            # Also write metadata
            meta_filename = os.path.join(self.data_dir, f"image_{timestamp}.meta")
            with open(meta_filename, 'w') as f:
                f.write(f"width: {width}\n")
                f.write(f"height: {height}\n")
                f.write(f"format: RGB\n")
                
        except Exception as e:
            self.logger.error(f"Error saving image: {e}")
    
    def get_status_summary(self):
        """Get a status summary of the logging data receiver"""
        avg_detections = np.mean(self.detection_counts) if self.detection_counts else 0
        
        return {
            'received_count': self.received_count,
            'error_count': self.error_count,
            'current_state': str(self.last_system_state) if self.last_system_state else "Unknown",
            'avg_detections': avg_detections,
            'last_timestamp': self.last_timestamp
        }


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
        log_file = os.path.join(log_dir, f"client_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
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
    parser = argparse.ArgumentParser(description='Andon System Logging Client')
    parser.add_argument('--ip', type=str, default='10.10.10.1', help='Device IP address')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode. No GUI just data streaming')

    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_args()
    logger = setup_logging(args.debug)
    
    logger.info(f"Starting Andon System Logging Client - connecting to {args.ip}")
    
    # Create instances
    heartbeat = HeartbeatPublisher(ip=args.ip, debug=args.debug)
    logging_subscriber = LoggingDataSubscriber(ip=args.ip, poll_interval=0.1, debug=args.debug)
    
    try:

        heartbeat.start_heartbeat()
        # Start logging data subscriber
        logging_subscriber.start_polling()
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    except Exception as e:
        logger.error(f"Error in main loop: {e}")
    
    finally:
        # Cleanup
        logger.info("Shutting down...")
        heartbeat.stop_heartbeat()
        logging_subscriber.stop_polling()
        logger.info("Client stopped")


if __name__ == "__main__":
    main()