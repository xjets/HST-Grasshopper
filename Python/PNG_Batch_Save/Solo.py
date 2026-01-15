    import Rhino
    import scriptcontext as sc
    import System.Drawing as Drawing
    import System.Drawing.Imaging as Imaging
    import System
    import os
    import time

    # OSC imports for sending messages to Processing
    import clr
    clr.AddReference("System")
    from System.Net import IPEndPoint, IPAddress
    from System.Net.Sockets import UdpClient
    import struct

    # INPUTS: osc_string (string), restore_view (string)
    # OSC format: width,height,view_name,file_prefix,file_path,viewmode,transparent,file_midfix,file_suffix,file_series_number
    # Outputs: status, directory_check, views_found, capture_results, file_operations

    def send_osc_message(address, value, ip="127.0.0.1", port=7010, retries=3):
        """Send OSC message to Processing with retry logic"""
        
        # Build OSC message once
        try:
            # Address string with null terminator
            addr_bytes = bytearray(address + '\0', 'utf-8')
            # Pad to multiple of 4
            while len(addr_bytes) % 4 != 0:
                addr_bytes.append(0)
            
            # Type tag string (comma + type + null terminator)
            if isinstance(value, int):
                type_tag = bytearray(',i\0\0', 'utf-8')
                # Pack integer as big-endian
                value_bytes = bytearray(struct.pack('>i', value))
            elif isinstance(value, float):
                type_tag = bytearray(',f\0\0', 'utf-8')
                # Pack float as big-endian
                value_bytes = bytearray(struct.pack('>f', value))
            else:
                # String
                type_tag = bytearray(',s\0\0', 'utf-8')
                str_bytes = bytearray(str(value) + '\0', 'utf-8')
                while len(str_bytes) % 4 != 0:
                    str_bytes.append(0)
                value_bytes = str_bytes
            
            # Combine all parts
            message = bytes(addr_bytes + type_tag + value_bytes)
            
        except Exception as e:
            print("OSC message build error: " + str(e))
            return False
        
        # Try sending with retries
        endpoint = IPEndPoint(IPAddress.Parse(ip), port)
        
        for attempt in range(retries):
            try:
                # Create new UDP client for each attempt
                client = UdpClient()
                client.Send(message, len(message), endpoint)
                client.Close()
                
                # Log success on retry
                if attempt > 0:
                    print("OSC message sent successfully on attempt {} of {}".format(attempt + 1, retries))
                
                return True
                
            except Exception as e:
                if attempt < retries - 1:
                    print("OSC send attempt {} failed: {}, retrying...".format(attempt + 1, str(e)))
                    time.sleep(0.01)  # Small delay before retry
                else:
                    print("OSC send error after {} attempts: ".format(retries) + str(e))
                    return False
        
        return False

    def capture_views(osc_string, restore_view):
        
        # Track start time
        start_time = time.time()
        
        # PARSE OSC STRING - Enhanced format with optional extras
        if not osc_string:
            return "Waiting for OSC message...", "", "", "", ""
        
        try:
            parts = osc_string.split(',')
            if len(parts) < 5:
                return "ERROR: osc_string must have at least 5 comma-separated values, got {}".format(len(parts)), "", "", "", ""
            
            # Required parameters
            width = int(parts[0].strip())
            height = int(parts[1].strip())
            view_name = parts[2].strip()
            file_prefix = parts[3].strip()
            file_path = parts[4].strip()
            
            # Optional parameters with defaults
            viewmode = parts[5].strip() if len(parts) > 5 and parts[5].strip() else "shaded"
            transparent_str = parts[6].strip().lower() if len(parts) > 6 and parts[6].strip() else "true"
            transparent = transparent_str in ["true", "1", "yes", "on"]

            # New optional naming parameters
            file_midfix = parts[7].strip() if len(parts) > 7 else ""
            file_suffix = parts[8].strip() if len(parts) > 8 else ""
            try:
                file_series_number = int(parts[9].strip()) if len(parts) > 9 and parts[9].strip() else 0
            except ValueError:
                file_series_number = 0
            
        except ValueError as parse_error:
            return "ERROR: Failed to parse osc_string: {}".format(str(parse_error)), "", "", "", ""
        except Exception as parse_error:
            return "ERROR: Unexpected parsing error: {}".format(str(parse_error)), "", "", "", ""
        
        # SEND START ACKNOWLEDGEMENT
        osc_sent = send_osc_message("/pngSaveStarted", 1.0)
        start_msg_result = "Sent start acknowledgement to Processing" if osc_sent else "Failed to send start acknowledgement"
        
        # Store original document context
        ghdoc = sc.doc
        
        try:
            # Switch to Rhino document context
            sc.doc = Rhino.RhinoDoc.ActiveDoc
            
            status_msgs = []
            directory_status = ""
            views_status = []
            capture_status = []
            file_status = []
            
            status_msgs.append(start_msg_result)
            
            # Validate parsed inputs
            if not file_path or not file_prefix:
                return "ERROR: file_path and file_prefix are required", "", "", "", ""
            
            if not view_name:
                return "ERROR: view_name is required", "", "", "", ""
            
            if width <= 0 or height <= 0:
                return "ERROR: width and height must be positive integers", "", "", "", ""
            
            status_msgs.append("Parsed from OSC: {}x{} | View: {} | Prefix: {} | Midfix: {} | Suffix: {} | Path: {} | Mode: {} | Transparent: {} | Series: {}".format(
                width, height, view_name, file_prefix, file_midfix, file_suffix, file_path, viewmode, transparent, file_series_number))
            
            if not restore_view:
                restore_view = "Perspective"
            
            # Check directory
            if os.path.exists(file_path):
                directory_status = "Directory OK: " + file_path
                status_msgs.append("Directory exists")
            else:
                directory_status = "ERROR: Directory not found: " + file_path
                return "Directory Error", directory_status, "", "", ""
            
            # Build base filename parts (skip empty midfix/suffix to avoid double underscores)
            base_parts = [file_prefix, view_name]
            if file_midfix:
                base_parts.append(file_midfix)
            if file_suffix:
                base_parts.append(file_suffix)
            base_name = "_".join([p for p in base_parts if p])

            # Determine sequence number: use provided series if > 0, else find next available
            if 'file_series_number' in locals() and file_series_number and file_series_number > 0:
                sequence_num = int(file_series_number)
                status_msgs.append("Using provided series number: {:03d}".format(sequence_num))
            else:
                sequence_num = 1
                while True:
                    test_filename = "{}_{:03d}.png".format(base_name, sequence_num)
                    test_path = os.path.join(file_path, test_filename)
                    if not os.path.exists(test_path):
                        break
                    sequence_num += 1
                    if sequence_num > 999:
                        return "ERROR: Reached maximum sequence number (999)", "", "", "", ""
                status_msgs.append("Auto-selected next available series: {:03d}".format(sequence_num))
            status_msgs.append("Transparent background: " + str(transparent))
            status_msgs.append("Will restore to view: " + restore_view)
            
            # Check active view
            active_view = sc.doc.Views.ActiveView
            if not active_view:
                return "ERROR: No active view", directory_status, "", "", ""
            
            status_msgs.append("Active view found")
            viewport = active_view.ActiveViewport
            original_display_mode = viewport.DisplayMode
            
            # Check available named views
            total_named_views = sc.doc.NamedViews.Count
            status_msgs.append("Total named views: " + str(total_named_views))
            
            # Find requested display mode
            target_mode = None
            available_modes = []
            for mode in Rhino.Display.DisplayModeDescription.GetDisplayModes():
                available_modes.append(mode.EnglishName)
                if mode.EnglishName.lower() == viewmode.lower():
                    target_mode = mode
            
            status_msgs.append("Available display modes: " + ", ".join(available_modes))
            
            if target_mode:
                viewport.DisplayMode = target_mode
                status_msgs.append("Set to display mode: " + viewmode)
            else:
                status_msgs.append("WARNING: Display mode '" + viewmode + "' not found, using current mode")
            
            # Process the single view
            capture_status.append("=== PROCESSING VIEW ===")
            capture_status.append("View: {}, Width: {}, Height: {}".format(view_name, width, height))
            
            view_found = False
            named_view_index = -1
            
            # Search for named view
            for i in range(sc.doc.NamedViews.Count):
                if sc.doc.NamedViews[i].Name == view_name:
                    named_view_index = i
                    view_found = True
                    break
            
            if view_found:
                views_status.append("FOUND: {} at index {} - resolution {}x{}".format(
                    view_name, named_view_index, width, height))
                
                try:
                    # Restore the named view
                    success = sc.doc.NamedViews.Restore(named_view_index, active_view.ActiveViewport, True)
                    
                    if success:
                        capture_status.append("Named view restored successfully: " + view_name)
                        
                        # Reapply display mode after view restoration
                        if target_mode:
                            viewport.DisplayMode = target_mode
                        
                        # Generate filename with sequence number and midfix/suffix
                        filename = "{}_{:03d}.png".format(base_name, sequence_num)
                        full_path = os.path.join(file_path, filename)
                        
                        capture_status.append("Target file: " + filename)
                        capture_status.append("USING DIMENSIONS: {}x{} for {}".format(width, height, view_name))
                        
                        # Force redraw to update viewport
                        sc.doc.Views.Redraw()
                        
                        # Small delay to ensure view is updated
                        time.sleep(0.3)
                        
                        # **** SEND OSC MESSAGE TO PLAY SHUTTER SOUND ****
                        osc_sent = send_osc_message("/gh_shutter_trigger", 1.0)
                        if osc_sent:
                            capture_status.append("Sent shutter sound trigger to Processing")
                        
                        # Small delay for audio to start
                        time.sleep(0.1)
                        
                        # Capture using appropriate method
                        try:
                            if transparent:
                                # CORRECTED: Options BEFORE filename
                                command_string = '-ViewCaptureToFile Width={} Height={} TransparentBackground=Yes "{}"'.format(
                                width, height, full_path)
                                
                                capture_status.append("COMMAND STRING: " + command_string)
                                command_success = Rhino.RhinoApp.RunScript(command_string, False)
                                
                                if command_success:
                                    time.sleep(0.5)
                                    if os.path.exists(full_path):
                                        # Check actual dimensions of saved file
                                        saved_image = Drawing.Image.FromFile(full_path)
                                        actual_width = saved_image.Width
                                        actual_height = saved_image.Height
                                        saved_image.Dispose()
                                        
                                        file_size = os.path.getsize(full_path)
                                        file_status.append("SAVED: {} | Expected: {}x{} | Actual: {}x{} | Size: {} bytes".format(
                                            filename, width, height, actual_width, actual_height, file_size))
                                    else:
                                        capture_status.append("ERROR: Transparent capture - file not found")
                                else:
                                    capture_status.append("ERROR: ViewCaptureToFile command failed")
                            else:
                                # Non-transparent: use CaptureToBitmap directly
                                bitmap = active_view.CaptureToBitmap(Drawing.Size(width, height))
                                if bitmap:
                                    capture_status.append("Bitmap captured: {}x{}".format(bitmap.Width, bitmap.Height))
                                    bitmap.Save(full_path, Imaging.ImageFormat.Png)
                                    bitmap.Dispose()
                                    
                                    file_size = os.path.getsize(full_path)
                                    file_status.append("SAVED: " + filename + " (" + str(file_size) + " bytes)")
                                else:
                                    capture_status.append("ERROR: Bitmap capture failed for " + view_name)
                        
                        except Exception as capture_error:
                            capture_status.append("Capture error for " + view_name + ": " + str(capture_error))
                            
                    else:
                        capture_status.append("ERROR: Failed to restore named view: " + view_name)
                        
                except Exception as view_error:
                    capture_status.append("VIEW ERROR for " + view_name + ": " + str(view_error))
            else:
                views_status.append("NOT FOUND: " + view_name)
            
            # Return viewport to restore view
            restore_view_index = -1
            for i in range(sc.doc.NamedViews.Count):
                if sc.doc.NamedViews[i].Name == restore_view:
                    restore_view_index = i
                    break
            
            if restore_view_index >= 0:
                success = sc.doc.NamedViews.Restore(restore_view_index, active_view.ActiveViewport, True)
                if success:
                    status_msgs.append("Viewport returned to: " + restore_view)
                else:
                    status_msgs.append("WARNING: Failed to return to: " + restore_view)
            else:
                status_msgs.append("WARNING: Restore view '" + restore_view + "' not found")
            
            # Restore original display mode
            viewport.DisplayMode = original_display_mode
            sc.doc.Views.Redraw()
            
            # Calculate elapsed time
            elapsed_time = time.time() - start_time
            
            # Small delay to ensure all file operations are complete before sending completion message
            time.sleep(0.2)
            
            # SEND COMPLETION MESSAGE with retry logic
            complete_msg_result = "Sending completion message to Processing..."
            osc_sent = send_osc_message("/pngSaveComplete", float(elapsed_time))
            
            if osc_sent:
                complete_msg_result = "Sent completion message to Processing (elapsed: {:.2f}s)".format(elapsed_time)
            else:
                complete_msg_result = "Failed to send completion message after retries"
            
            # Compile outputs
            status_msgs.append(complete_msg_result)
            main_status = "; ".join(status_msgs)
            views_output = "\n".join(views_status)
            capture_output = "\n".join(capture_status)
            file_output = "\n".join(file_status)
            
            return main_status, directory_status, views_output, capture_output, file_output
            
        except Exception as main_error:
            return "MAIN ERROR: " + str(main_error), "", "", "", ""
        
        finally:
            # Always restore Grasshopper document context
            sc.doc = ghdoc

    # Execute
    status, directory_check, views_found, capture_results, file_operations = capture_views(
        osc_string, restore_view)