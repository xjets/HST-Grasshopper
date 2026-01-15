import scriptcontext as sc
import datetime
import os

"""
GRASSHOPPER STATE MONITOR COMPONENT
====================================

PURPOSE:
Monitors two input values and logs state changes to a persistent file.
Each time either input changes, appends a timestamped entry to the log.

INPUTS:
- mc_save_trigger (float/int): Trigger value from Processing
- mc_saturation (float): Saturation value from Processing

OUTPUTS:
- status: Current state message
- log_path: Path to the log file
"""

def monitor_state(mc_save_trigger, mc_saturation):
    """
    Monitor state changes and append to log file
    """

    # Setup log file path
    log_dir = "x:\\Shaw\\Helmets\\November\\Grasshopper\\Python\\PNG_Batch_Save\\logs"
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except:
            log_dir = "C:\\Temp"

    log_file_path = os.path.join(log_dir, "state_monitor.txt")

    # Create sticky key for this component instance
    sticky_key = "state_monitor_" + str(ghenv.Component.InstanceGuid)

    # Get previous values from sticky
    last_state = sc.sticky.get(sticky_key, None)

    # Current values (handle None)
    current_trigger = mc_save_trigger if mc_save_trigger is not None else 0.0
    current_saturation = mc_saturation if mc_saturation is not None else 0.0

    # Check if this is first run or if values have changed
    if last_state is None:
        # First run - initialize
        sc.sticky[sticky_key] = {
            'trigger': current_trigger,
            'saturation': current_saturation
        }

        # Write initial state to log
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            with open(log_file_path, 'a') as f:
                f.write("=" * 70 + "\n")
                f.write("STATE MONITOR INITIALIZED: {}\n".format(timestamp))
                f.write("  mc_save_trigger = {}\n".format(current_trigger))
                f.write("  mc_saturation   = {}\n".format(current_saturation))
                f.write("-" * 70 + "\n")
        except Exception as e:
            return "ERROR: Could not write to log: {}".format(str(e)), log_file_path

        status = "Initialized | trigger={} | saturation={}".format(current_trigger, current_saturation)
        return status, log_file_path

    # Check for changes
    trigger_changed = (last_state['trigger'] != current_trigger)
    saturation_changed = (last_state['saturation'] != current_saturation)

    if trigger_changed or saturation_changed:
        # State changed - log it
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        try:
            with open(log_file_path, 'a') as f:
                f.write("{} | ".format(timestamp))

                if trigger_changed and saturation_changed:
                    f.write("BOTH CHANGED | trigger: {} -> {} | saturation: {} -> {}\n".format(
                        last_state['trigger'], current_trigger,
                        last_state['saturation'], current_saturation))
                elif trigger_changed:
                    f.write("TRIGGER CHANGED | {} -> {} | saturation: {}\n".format(
                        last_state['trigger'], current_trigger, current_saturation))
                else:  # saturation_changed
                    f.write("SATURATION CHANGED | {} -> {} | trigger: {}\n".format(
                        last_state['saturation'], current_saturation, current_trigger))
        except Exception as e:
            return "ERROR: Could not write to log: {}".format(str(e)), log_file_path

        # Update sticky
        sc.sticky[sticky_key] = {
            'trigger': current_trigger,
            'saturation': current_saturation
        }

        status = "CHANGED | trigger={} | saturation={}".format(current_trigger, current_saturation)
    else:
        # No change
        status = "No change | trigger={} | saturation={}".format(current_trigger, current_saturation)

    return status, log_file_path

# ============================================================================
# COMPONENT EXECUTION
# ============================================================================
# Handle inputs that may not be connected
try:
    trig = mc_save_trigger
except NameError:
    trig = None

try:
    sat = mc_saturation
except NameError:
    sat = None

status, log_path = monitor_state(trig, sat)
