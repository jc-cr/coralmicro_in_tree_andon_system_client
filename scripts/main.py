#!/usr/bin/env python3

# main.py
import json
import sys
import time
import requests
import threading
from enum import Enum

class AndonSystemState(Enum):
    UNINITIALIZED = 0
    IDLE = 1
    WARNING = 2
    ERROR = 3

class HostCondition(Enum):
    UNCONNECTED = 0
    CONNECTED = 1
    ERROR = 2

class SimpleClient:
    def __init__(self, ip="10.10.10.1", heartbeat_interval=1.0):
        self.ip = ip
        self.heartbeat_interval = heartbeat_interval
        self.connected = False
        self.heartbeat_thread = None
        self.stop_flag = False
        
        # Connection check
        self.check_connection()
    
    def check_connection(self):
        """Check if the device is reachable"""
        try:
            response = requests.get(f'http://{self.ip}/', timeout=2)
            self.connected = response.status_code == 200
            print(f"Connected to device at {self.ip}: {self.connected}")
            return self.connected
        except Exception as e:
            print(f"Failed to connect to device: {e}")
            self.connected = False
            return False
    
    def start_heartbeat(self):
        """Start heartbeat thread"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            print("Heartbeat already running")
            return
            
        self.stop_flag = False
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_thread)
        self.heartbeat_thread.daemon = True
        self.heartbeat_thread.start()
        print("Started heartbeat thread")
    
    def stop_heartbeat(self):
        """Stop heartbeat thread"""
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            self.stop_flag = True
            self.heartbeat_thread.join(timeout=2.0)
            print("Stopped heartbeat")
    
    def _heartbeat_thread(self):
        """Background thread for heartbeats"""
        heartbeat_count = 0
        
        while not self.stop_flag:
            try:
                # Send heartbeat
                if self.send_heartbeat():
                    heartbeat_count += 1
                    if heartbeat_count % 5 == 0:  # Only log every 5 heartbeats
                        print(f"Sent heartbeat #{heartbeat_count}")
                        
                        # Get system status
                        state_data = self.get_system_state()
                        if state_data:
                            state = AndonSystemState(state_data.get('state', 0))
                            print(f"System State: {state.name}")
                else:
                    print("Failed to send heartbeat")
                    
            except Exception as e:
                print(f"Error in heartbeat thread: {e}")
            
            # Wait for next heartbeat
            time.sleep(self.heartbeat_interval)
    
    def _parse_json_response(self, response_text):
        """Safely parse JSON response handling potential errors"""
        try:
            # Strip any trailing garbage data that might be present
            # Find the last valid JSON closing brace
            last_brace = response_text.rfind('}')
            if last_brace >= 0:
                clean_json = response_text[:last_brace+1]
                return json.loads(clean_json)
            return None
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Raw response: {response_text[:100]}")  # Show only first 100 chars
            return None
    
    def get_system_state(self):
        """Get system state from device"""
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
                json=payload,  # Uses json.dumps with proper encoding
                headers={'Content-Type': 'application/json'},
                timeout=2.0
            )
            
            if response.status_code != 200:
                print(f"HTTP error {response.status_code}")
                return None
            
            # Use the safer JSON parsing method
            result = self._parse_json_response(response.text)
            if not result:
                print(f"Failed to parse JSON from response")
                return None
                
            if 'error' in result:
                print(f"RPC error: {result['error']}")
                return None
                
            return result.get('result')
            
        except Exception as e:
            print(f"Error getting system state: {e}")
            return None
    
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
                json=payload,  # Uses json.dumps with proper encoding
                headers={'Content-Type': 'application/json'},
                timeout=1.0
            )
            
            if response.status_code != 200:
                print(f"HTTP error: {response.status_code}")
                return False
            
            # Use the safer JSON parsing method
            result = self._parse_json_response(response.text)
            if not result:
                # If we can't parse JSON but got HTTP 200, consider it a success
                return response.status_code == 200
                
            if 'error' in result:
                print(f"RPC error: {result['error']}")
                return False
                
            return True
            
        except Exception as e:
            print(f"Error sending heartbeat: {e}")
            return False

def main():
    client = SimpleClient()
    
    if not client.connected:
        print("Not connected to device. Exiting.")
        return
    
    try:
        # Start heartbeat
        client.start_heartbeat()
        
        # Run for 30 seconds
        print("Running for 30 seconds (press Ctrl+C to exit)...")
        time.sleep(30)
        
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        # Stop heartbeat
        client.stop_heartbeat()
        print("Client stopped")

if __name__ == "__main__":
    main()