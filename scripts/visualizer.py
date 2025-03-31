import tkinter as tk
from tkinter import ttk
import logging
import os
import time
import argparse
import sys
from datetime import datetime
from PIL import ImageTk

from nodes import DataSubscriber, HeartbeatPublisher, HostStatePublisher
from enums import HostState

class Visualizer:
    def __init__(self, data_subscriber, host_state_manager):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.data_subscriber = data_subscriber
        self.host_state_manager = host_state_manager
        
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
        
        # Add Host State controls
        host_state_frame = ttk.LabelFrame(main_frame, text="Host State Control")
        host_state_frame.pack(fill=tk.X, padx=5, pady=5)
        
        host_state_grid = ttk.Frame(host_state_frame)
        host_state_grid.pack(fill=tk.X, padx=5, pady=5)
        
        # Current host state display
        ttk.Label(host_state_grid, text="Current Host State:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.host_state_var = tk.StringVar(value=HostState.IDLE.name)
        ttk.Label(host_state_grid, textvariable=self.host_state_var).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Host state selection dropdown
        ttk.Label(host_state_grid, text="Set Host State:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.host_state_combo = ttk.Combobox(host_state_grid, values=[state.name for state in HostState])
        self.host_state_combo.current(HostState.IDLE.value)
        self.host_state_combo.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        
        # Button to set host state
        ttk.Button(host_state_grid, text="Set State", command=self.set_host_state).grid(row=1, column=2, padx=5, pady=2)
        
        # Quick state buttons for common operations
        button_frame = ttk.Frame(host_state_frame)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Create buttons for common states
        ttk.Button(button_frame, text="IDLE", 
                  command=lambda: self.set_quick_state(HostState.IDLE)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="EXECUTE", 
                  command=lambda: self.set_quick_state(HostState.EXECUTE)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="STOPPED", 
                  command=lambda: self.set_quick_state(HostState.STOPPED)).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="ABORTED", 
                  command=lambda: self.set_quick_state(HostState.ABORTED)).pack(side=tk.LEFT, padx=5)
                  
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
    
    def set_host_state(self):
        """Set host state from dropdown selection"""
        selected_state = self.host_state_combo.get()
        try:
            # Find the HostState enum by name
            state = next(s for s in HostState if s.name == selected_state)
            
            # Update the state
            if self.host_state_manager.set_host_state(state):
                self.host_state_var.set(state.name)
                self.logger.info(f"Set host state to {state.name}")
            else:
                self.logger.error(f"Failed to set host state to {state.name}")
                
        except (StopIteration, ValueError) as e:
            self.logger.error(f"Invalid host state selected: {selected_state}, error: {e}")
    
    def set_quick_state(self, state):
        """Set host state using quick button"""
        if self.host_state_manager.set_host_state(state):
            self.host_state_var.set(state.name)
            self.host_state_combo.set(state.name)
            self.logger.info(f"Set host state to {state.name}")
        else:
            self.logger.error(f"Failed to set host state to {state.name}")
    
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
        host_state_manager = HostStatePublisher(ip=args.ip, debug=args.debug)

        # Start the heartbeat publisher regardless of mode
        heartbeat_publisher.start_heartbeat()
        
        # Set initial host state to IDLE
        host_state_manager.set_host_state(HostState.IDLE)

        if not args.headless:
            # Start GUI visualizer
            visualizer = Visualizer(data_subscriber, host_state_manager)
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