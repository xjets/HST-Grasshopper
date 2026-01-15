# Custom sweep implementation to replace Grasshopper's Sweep1 component
# October 2025, Claude
#
# Problem: The standard Sweep1 component enables "global shape blending" by default
# in Rhino WIP 9, with no way to disable it in the component interface.
#
# Solution: Use RhinoCommon's CreateFromSweep method directly, which does not use
# global shape blending by default.
#
# Inputs:
#   R - Rail curve (single 3D spline) - set to "Item" access
#   S - Section curves (lines positioned along rail) - set to "List" access
#   closed - Boolean toggle for closed/open sweep - set to "Item" access
#   T - Tolerance value for sweep operation
#
# Output:
#   a - Resulting Brep surface(s)

import Rhino.Geometry as rg

# Verify inputs exist and are valid
if R and S and len(S) > 0:
    # Convert closed to boolean (default to False if not provided)
    is_closed = bool(closed) if closed else False

    # CreateFromSweep parameters:
    # - R: rail curve
    # - S: list of cross-section curves
    # - is_closed: sweep is closed (True) or open (False)
    # - T: tolerance
    breps = rg.Brep.CreateFromSweep(R, S, is_closed, T)

    # Check if sweep operation succeeded
    if breps and len(breps) > 0:
        a = breps
    else:
        a = []  # Return empty list instead of None to avoid type warnings
else:
    a = []  # Handle missing or invalid inputs
