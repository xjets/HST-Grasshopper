import Rhino
import scriptcontext as sc
import System.Drawing as Drawing
import System.Drawing.Imaging as Imaging
import System
import os
import time
import datetime

# OSC imports for sending messages to Processing
import clr
clr.AddReference("System")
from System.Net import IPEndPoint, IPAddress
from System.Net.Sockets import UdpClient
import struct

# ============================================================================
# GRASSHOPPER BATCH IMAGE SAVE COMPONENT
# ============================================================================
#
# PURPOSE:
# Saves multiple named views as PNG images with transparency, triggered by
# OSC messages from Processing. Sends progress updates back to Processing.
#
# INPUTS:
# - trigger (boolean): Rising edge (0→1) starts save sequence
# - view_names (string): Comma-delimited string of view names from OSC (e.g., "Front,Side,Top")
#                        Can also accept list of strings for backward compatibility
# - size (integer): Resolution for square images (width=height=size)
# - mc_save_package (string): "path,prefix,midfix,suffix,number"
# - viewmode (string): Display mode (e.g., "shaded", "rendered")
# - restore_view (string): Named view to return to after completion
# - mc_saturation_fg (float): Monitor value from Processing /mc_saturation_fg (optional)
#
# OUTPUTS:
# - status: Main status message
# - directory_check: Directory validation status
# - views_found: List of found/not found views
# - capture_results: Detailed capture progress
# - file_operations: File save results
# - debug_output: Full debug console output
#
# OSC MESSAGES SENT TO PROCESSING (127.0.0.1:7010):
# - /pngBatchStart: {runId,totalViews} - Batch starts
# - /pngViewSaved: {runId,viewIndex,viewName} - Each image saved
# - /pngBatchComplete: {runId,okCount,errCount} - Batch finishes
#
# NOTE: This component uses rising-edge trigger detection via sc.sticky
# ============================================================================

def send_osc_message(address, value, ip="127.0.0.1", port=7010, retries=3):
    """
    Send OSC message to Processing with retry logic

    Args:
        address (str): OSC address pattern (e.g., "/pngBatchStart")
        value: Integer, float, or string value to send
        ip (str): Target IP address (default: localhost)
        port (int): Target port (default: 7010 for Processing)
        retries (int): Number of send attempts before giving up

    Returns:
        bool: True if message sent successfully, False otherwise
    """

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
        print("ERROR: OSC message build failed: " + str(e))
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
                print("  OSC retry successful on attempt {}/{}".format(attempt + 1, retries))

            return True

        except Exception as e:
            if attempt < retries - 1:
                print("  OSC send attempt {}/{} failed, retrying...".format(attempt + 1, retries))
                time.sleep(0.01)  # Small delay before retry
            else:
                print("ERROR: OSC send failed after {} attempts: {}".format(retries, str(e)))
                return False

def gen_run_id():
    """Generate unique run ID with timestamp"""
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")

def send_osc_str(address, payload, ip="127.0.0.1", port=7010, retries=3):
    """Helper to send OSC string message"""
    return send_osc_message(address, str(payload), ip=ip, port=port, retries=retries)

def capture_views(trigger, view_names, size, mc_save_package, viewmode, restore_view, mc_saturation_fg=None):
    """
    Main capture function - handles the entire batch save sequence

    TRIGGER LOGIC:
    Uses sc.sticky to detect rising edge (0→1 transition)
    Only executes when trigger changes from False to True
    This prevents re-triggering on every component re-compute
    """

    status_msgs = []
    directory_status = ""
    views_status = []
    capture_status = []
    file_status = []
    debug_msgs = []  # Capture all print output

    # ========================================================================
    # RISING EDGE DETECTION: Only execute on trigger 0→1 transition
    # ========================================================================
    sticky_key = "capture_views_last_trigger_" + str(ghenv.Component.InstanceGuid)
    last_trigger = sc.sticky.get(sticky_key, False)

    # Update sticky with current trigger state
    sc.sticky[sticky_key] = trigger

    # If trigger is currently False, just wait
    if not trigger:
        main_status = "⏸ Trigger is False - ready for next capture"
        if status_msgs:
            main_status += " | " + "; ".join(status_msgs)
        return main_status, "", "", "", "", ""

    # If trigger was already True, we're waiting for reset
    if last_trigger == True:
        main_status = "⏳ Waiting for trigger reset (toggle OFF then ON to capture again)"
        if status_msgs:
            main_status += " | " + "; ".join(status_msgs)
        return main_status, "", "", "", "", ""

    # ========================================================================
    # EXECUTION STARTING - Create log file NOW
    # ========================================================================
    # Setup debug log file - use explicit path
    log_dir = "x:\\Shaw\\Helmets\\November\\Grasshopper\\Python\\PNG_Batch_Save\\logs"
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except:
            log_dir = "C:\\Temp"  # Fallback

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file_path = os.path.join(log_dir, "batch_capture_{}.txt".format(timestamp))

    # Create a mutable container to hold the log file reference
    log_state = {'file': None}

    try:
        log_state['file'] = open(log_file_path, 'w')
    except Exception as e:
        print("WARNING: Could not open log file: " + str(e))

    def log(msg):
        """Helper to log to debug_msgs, console, and file with timestamps"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        msg_str = "[{}] {}".format(timestamp, str(msg))
        debug_msgs.append(msg_str)
        print(msg_str)
        if log_state['file']:
            try:
                log_state['file'].write(msg_str + "\n")
                log_state['file'].flush()  # Immediately flush to disk
            except Exception as e:
                print("WARNING: Log write failed: " + str(e))

    # ========================================================================
    # EXECUTION STARTS HERE: Trigger just went from False→True (rising edge)
    # ========================================================================
    log("")
    log("=" * 70)
    log("GRASSHOPPER: BATCH SAVE TRIGGERED - RISING EDGE DETECTED")
    log("=" * 70)
    log("")
    log("[M-CHANNEL MONITOR] mc_saturation_fg = {}".format(mc_saturation_fg))

    # Store original document context
    ghdoc = sc.doc

    try:
        # Switch to Rhino document context
        sc.doc = Rhino.RhinoDoc.ActiveDoc

        # ====================================================================
        # STEP 1: Parse mc_save_package from Processing
        # ====================================================================
        log("[STEP 1] Parsing mc_save_package...")
        if not mc_save_package or not isinstance(mc_save_package, str):
            log("ERROR: mc_save_package is empty or invalid")
            return "ERROR: mc_save_package string is required", "", "", "", "", "\n".join(debug_msgs)

        parts = [p.strip() for p in mc_save_package.split(',')]
        if len(parts) < 5:
            log("ERROR: mc_save_package has {} parts, need 5".format(len(parts)))
            return "ERROR: mc_save_package must have 5 comma-separated values", "", "", "", "", "\n".join(debug_msgs)

        file_path = parts[0]
        file_prefix = parts[1]
        file_midfix = parts[2]
        file_suffix = parts[3]
        try:
            file_series_number = int(parts[4])
        except:
            file_series_number = 0

        log("  Path:   '{}'".format(file_path))
        log("  Prefix: '{}'".format(file_prefix))
        log("  Midfix: '{}'".format(file_midfix))
        log("  Suffix: '{}'".format(file_suffix))
        log("  Number: {}".format(file_series_number))

        status_msgs.append("Parsed package: path='{}', prefix='{}', midfix='{}', suffix='{}', number={}".format(
            file_path, file_prefix, file_midfix, file_suffix, file_series_number))

        # Validate path/prefix
        if not file_path or not file_prefix:
            log("ERROR: Missing file_path or file_prefix")
            return "ERROR: mc_save_package missing file_path or file_prefix", "", "", "", "", "\n".join(debug_msgs)

        # ====================================================================
        # STEP 2: Process view names and size
        # ====================================================================
        log("[STEP 2] Processing view names...")

        # WRITE DEBUG INFO TO SEPARATE FILE IMMEDIATELY
        debug_file_path = "x:\\Shaw\\Helmets\\November\\Grasshopper\\Python\\PNG_Batch_Save\\logs\\viewnames_debug.txt"
        try:
            with open(debug_file_path, 'w') as df:
                df.write("=" * 70 + "\n")
                df.write("VIEW_NAMES DEBUG INFO\n")
                df.write("=" * 70 + "\n")
                df.write("Type: {}\n".format(type(view_names)))
                df.write("Repr: {}\n".format(repr(view_names)))
                df.write("Str: {}\n".format(str(view_names)))
                df.write("Has comma: {}\n".format(',' in str(view_names)))
                df.write("Is string: {}\n".format(isinstance(view_names, str)))
                df.write("Is list: {}\n".format(isinstance(view_names, list)))
                df.write("=" * 70 + "\n")
        except Exception as e:
            print("WARNING: Could not write debug file: " + str(e))

        log("  DEBUG: view_names type = {}".format(type(view_names)))
        log("  DEBUG: view_names value = {}".format(repr(view_names)))

        # Convert view_names to list
        # Handles multiple input formats:
        # 1. List with single comma-delimited string: ['Front,Side,Top'] (Grasshopper OSC wrapping)
        # 2. Comma-delimited string: "Front,Side,Top"
        # 3. Multiline string: "Front\nSide\nTop"
        # 4. List of strings: ['Front', 'Side', 'Top'] (backward compatibility)

        # Handle Grasshopper wrapping: list with single comma-delimited string
        # Grasshopper 8's OSC receiver wraps strings in single-element lists
        if isinstance(view_names, list) and len(view_names) == 1:
            log("  Single-element list detected, checking for comma-delimited string...")
            first_element = view_names[0]
            log("    Element type: {}".format(type(first_element)))
            log("    Is string: {}".format(isinstance(first_element, str)))
            log("    Has comma: {}".format(',' in str(first_element)))
            if isinstance(first_element, str) and ',' in first_element:
                log("  Detected Grasshopper-wrapped comma-delimited string")
                view_names = first_element  # Extract the string from the list
            else:
                log("  Single-element list check failed - not extracting")

        # Now process as string or list
        if isinstance(view_names, str):
            # Check if comma-delimited (OSC format)
            if ',' in view_names:
                log("  Parsing comma-delimited view list from OSC...")
                view_names = [v.strip() for v in view_names.split(',') if v.strip()]
                log("  Parsed {} views from comma-delimited string".format(len(view_names)))
            else:
                # Fallback to newline-delimited (legacy format)
                view_names = [v.strip() for v in view_names.split('\n') if v.strip()]
                if len(view_names) == 0:
                    view_names = [view_names]
        # If already a proper list, keep it as is

        if not view_names or len(view_names) == 0:
            log("ERROR: view_names list is empty")
            return "ERROR: view_names list is empty", "", "", "", "", "\n".join(debug_msgs)

        num_views = len(view_names)
        log("  Total views to capture: {}".format(num_views))

        # Validate size input
        try:
            if isinstance(size, str):
                size_value = int(float(size.strip()))
            else:
                size_value = int(size)
        except:
            log("ERROR: Invalid size value")
            return "ERROR: size must be a single integer value", "", "", "", "", "\n".join(debug_msgs)

        if size_value <= 0:
            log("ERROR: size must be positive")
            return "ERROR: size must be a positive integer", "", "", "", "", "\n".join(debug_msgs)

        log("  Resolution: {}x{} pixels".format(size_value, size_value))

        for i, name in enumerate(view_names):
            log("    View {}: {}".format(i+1, name))

        # ====================================================================
        # STEP 3: Validate directory and setup
        # ====================================================================
        log("[STEP 3] Validating directory...")

        if not os.path.exists(file_path):
            directory_status = "ERROR: Directory not found: " + file_path
            log("ERROR: Directory does not exist")
            return "Directory Error", directory_status, "", "", "", "\n".join(debug_msgs)

        directory_status = "Directory OK: " + file_path
        log("  Directory exists: " + file_path)

        # Setup display mode
        if not viewmode:
            viewmode = "shaded"
        if not restore_view:
            restore_view = "Perspective"

        log("  Display mode: " + viewmode)
        log("  Restore view: " + restore_view)

        # ====================================================================
        # STEP 4: Setup viewport and display mode
        # ====================================================================
        log("[STEP 4] Setting up viewport...")

        active_view = sc.doc.Views.ActiveView
        if not active_view:
            log("ERROR: No active view found")
            return "ERROR: No active view", directory_status, "", "", "", "\n".join(debug_msgs)

        viewport = active_view.ActiveViewport
        original_display_mode = viewport.DisplayMode
        log("  Active view found, original display mode saved")

        # Find target display mode
        target_mode = None
        for mode in Rhino.Display.DisplayModeDescription.GetDisplayModes():
            if mode.EnglishName.lower() == viewmode.lower():
                target_mode = mode
                break

        if target_mode:
            viewport.DisplayMode = target_mode
            log("  Set display mode: " + viewmode)
        else:
            log("  WARNING: Display mode '{}' not found, using current".format(viewmode))

        # ====================================================================
        # STEP 5: Send batch start notification to Processing
        # ====================================================================
        run_id = gen_run_id()
        log("")
        log("[OSC->PROCESSING] Sending /pngBatchStart...")
        log("  RunID: {}".format(run_id))
        log("  Total views: {}".format(num_views))

        try:
            success = send_osc_str("/pngBatchStart", "{},{}".format(run_id, num_views))
            if success:
                log("  [OK] /pngBatchStart sent successfully")
            else:
                log("  [ERROR] /pngBatchStart send failed")
        except Exception as e:
            log("  [ERROR] /pngBatchStart exception: " + str(e))

        # ====================================================================
        # STEP 6: MAIN LOOP - Capture each view
        # ====================================================================
        log("")
        log("[STEP 6] Starting image capture loop...")
        log("-" * 70)

        t0 = time.time()
        ok_count = 0
        err_count = 0

        for idx in range(num_views):
            view_name = view_names[idx]
            width = height = size_value

            log("")
            log("  [{}/{}] Processing: {}".format(idx+1, num_views, view_name))
            log("  [M-CHANNEL] mc_saturation_fg = {}".format(mc_saturation_fg))
            capture_status.append("=== VIEW {} OF {} ===".format(idx+1, num_views))
            capture_status.append("Name: {}, Resolution: {}x{}".format(view_name, width, height))

            # Search for named view
            view_found = False
            named_view_index = -1

            for i in range(sc.doc.NamedViews.Count):
                if sc.doc.NamedViews[i].Name == view_name:
                    named_view_index = i
                    view_found = True
                    break

            if not view_found:
                log("    [ERROR] Named view not found: " + view_name)
                views_status.append("NOT FOUND: " + view_name)
                err_count += 1

                # Send error notification
                try:
                    send_osc_str("/pngViewError", "{},{},{}".format(run_id, idx+1, view_name))
                except:
                    pass
                continue

            log("    [OK] Found at index: {}".format(named_view_index))
            views_status.append("FOUND: {} at index {}".format(view_name, named_view_index))

            try:
                # Restore the named view
                success = sc.doc.NamedViews.Restore(named_view_index, active_view.ActiveViewport, True)

                if not success:
                    log("    [ERROR] Failed to restore named view")
                    capture_status.append("ERROR: Failed to restore view")
                    err_count += 1
                    try:
                        send_osc_str("/pngViewError", "{},{},{}".format(run_id, idx+1, view_name))
                    except:
                        pass
                    continue

                log("    [OK] View restored")

                # Reapply display mode
                if target_mode:
                    viewport.DisplayMode = target_mode

                # Generate filename
                per_view_base = "_".join([p for p in ([file_prefix, view_name] +
                    ([file_midfix] if file_midfix else []) +
                    ([file_suffix] if file_suffix else [])) if p])
                filename = "{}_{:03d}.png".format(per_view_base, file_series_number)
                full_path = os.path.join(file_path, filename)

                log("    File: " + filename)

                # Force redraw and wait
                sc.doc.Views.Redraw()
                time.sleep(0.3)

                # Send shutter sound trigger
                try:
                    send_osc_message("/gh_shutter_trigger", 1.0)
                    time.sleep(0.1)  # Audio delay
                except:
                    pass

                # Capture with transparency
                command_string = '-ViewCaptureToFile Width={} Height={} TransparentBackground=Yes "{}"'.format(
                    width, height, full_path)

                command_success = Rhino.RhinoApp.RunScript(command_string, False)

                if command_success:
                    time.sleep(0.5)  # Wait for file write

                    if os.path.exists(full_path):
                        # Verify file
                        saved_image = Drawing.Image.FromFile(full_path)
                        actual_width = saved_image.Width
                        actual_height = saved_image.Height
                        saved_image.Dispose()
                        file_size = os.path.getsize(full_path)

                        log("    [SAVED] {}x{} ({} bytes)".format(actual_width, actual_height, file_size))
                        file_status.append("SAVED: {} | {}x{} | {} bytes".format(
                            filename, actual_width, actual_height, file_size))
                        ok_count += 1

                        # Send success notification to Processing
                        try:
                            log("    [OSC->PROCESSING] Sending /pngViewSaved...")
                            send_osc_str("/pngViewSaved", "{},{},{}".format(run_id, idx+1, view_name))
                            log("    [OK] /pngViewSaved sent")
                        except Exception as e:
                            log("    [ERROR] /pngViewSaved failed: " + str(e))
                    else:
                        log("    [ERROR] File not found after capture")
                        capture_status.append("ERROR: File not created")
                        err_count += 1
                        try:
                            send_osc_str("/pngViewError", "{},{},{}".format(run_id, idx+1, view_name))
                        except:
                            pass
                else:
                    log("    [ERROR] ViewCaptureToFile command failed")
                    capture_status.append("ERROR: Capture command failed")
                    err_count += 1
                    try:
                        send_osc_str("/pngViewError", "{},{},{}".format(run_id, idx+1, view_name))
                    except:
                        pass

            except Exception as view_error:
                log("    [ERROR] Exception during capture: " + str(view_error))
                capture_status.append("ERROR: " + str(view_error))
                err_count += 1
                try:
                    send_osc_str("/pngViewError", "{},{},{}".format(run_id, idx+1, view_name))
                except:
                    pass

        # ====================================================================
        # STEP 7: Restore viewport to original state
        # ====================================================================
        log("")
        log("[STEP 7] Restoring viewport...")

        # Return to restore view
        restore_view_index = -1
        for i in range(sc.doc.NamedViews.Count):
            if sc.doc.NamedViews[i].Name == restore_view:
                restore_view_index = i
                break

        if restore_view_index >= 0:
            success = sc.doc.NamedViews.Restore(restore_view_index, active_view.ActiveViewport, True)
            if success:
                log("  [OK] Returned to view: " + restore_view)
            else:
                log("  [ERROR] Failed to return to: " + restore_view)
        else:
            log("  [ERROR] Restore view '{}' not found".format(restore_view))

        # Restore original display mode
        viewport.DisplayMode = original_display_mode
        sc.doc.Views.Redraw()
        log("  [OK] Display mode restored")

        # ====================================================================
        # STEP 8: Send batch complete notification to Processing
        # ====================================================================
        total_time = time.time() - t0

        log("")
        log("[OSC->PROCESSING] Sending /pngBatchComplete...")
        log("  RunID: {}".format(run_id))
        log("  Success: {} images".format(ok_count))
        log("  Errors:  {} images".format(err_count))
        log("  Time:    {:.2f} seconds".format(total_time))

        try:
            success = send_osc_str("/pngBatchComplete", "{},{},{}".format(run_id, ok_count, err_count))
            if success:
                log("  [OK] /pngBatchComplete sent successfully")
                status_msgs.append("Sent /pngBatchComplete to Processing")
            else:
                log("  [ERROR] /pngBatchComplete send failed")
                status_msgs.append("WARNING: Failed to send /pngBatchComplete")
        except Exception as e:
            log("  [ERROR] /pngBatchComplete exception: " + str(e))
            status_msgs.append("WARNING: /pngBatchComplete error: " + str(e))

        # Also send to OSC Pilot to reset trigger UI
        try:
            log("")
            log("[OSC->OSCPILOT] Sending /mc_save_trigger 0...")
            pilot_ok = send_osc_message("/mc_save_trigger", 0, ip="127.0.0.1", port=9012)
            if pilot_ok:
                log("  [OK] Trigger reset sent to OSC Pilot")
            else:
                log("  [ERROR] Trigger reset failed")
        except:
            pass

        # ====================================================================
        # FINAL SUMMARY
        # ====================================================================
        log("")
        log("=" * 70)
        log("GRASSHOPPER: BATCH SAVE COMPLETE")
        log("  {} images saved successfully".format(ok_count))
        log("  {} errors".format(err_count))
        log("  Total time: {:.2f} seconds".format(total_time))
        log("=" * 70)
        log("")
        log("Debug log saved to: " + log_file_path)

        # Compile outputs
        main_status = "COMPLETE: {} saved, {} errors in {:.1f}s | Log: {} | {}".format(
            ok_count, err_count, total_time, log_file_path, "; ".join(status_msgs))
        views_output = "\n".join(views_status)
        capture_output = "\n".join(capture_status)
        file_output = "\n".join(file_status)
        debug_output = "\n".join(debug_msgs)

        return main_status, directory_status, views_output, capture_output, file_output, debug_output

    except Exception as main_error:
        log("")
        log("=" * 70)
        log("GRASSHOPPER: FATAL ERROR")
        log("  " + str(main_error))
        log("=" * 70)
        log("Debug log saved to: " + log_file_path)
        return "MAIN ERROR: {} | Log: {}".format(str(main_error), log_file_path), "", "", "", "", "\n".join(debug_msgs)

    finally:
        # Close log file
        if log_state['file']:
            try:
                log_state['file'].close()
            except:
                pass
        # Always restore Grasshopper document context
        sc.doc = ghdoc

# ============================================================================
# COMPONENT EXECUTION
# ============================================================================
# Handle optional mc_saturation_fg input (may not be connected)
try:
    sat_fg = mc_saturation_fg
except NameError:
    sat_fg = None

status, directory_check, views_found, capture_results, file_operations, debug_output = capture_views(
    trigger, view_names, size, mc_save_package, viewmode, restore_view, sat_fg)
