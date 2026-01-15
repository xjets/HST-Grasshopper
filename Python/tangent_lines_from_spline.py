"""
Generate tangent lines from spline endpoints, rotated in YZ plane
Inputs:
    spline: Input curve (spline)
    entry_angle: Rotation angle in degrees for entry line (YZ plane)
    exit_angle: Rotation angle in degrees for exit line (YZ plane)
Outputs:
    entry_line: Line at endpoint with more positive Y (tangent, rotated, 50mm, inboard)
    exit_line: Line at endpoint with less positive Y (tangent, rotated, 50mm, inboard)
"""

import Rhino.Geometry as rg
import math

# Line length
line_length = 50.0

# Get spline start and end points
start_pt = spline.PointAtStart
end_pt = spline.PointAtEnd

# Get tangent vectors at start and end
# TangentAtStart points FROM start ALONG the curve (outboard)
# TangentAtEnd points FROM end ALONG the curve continuation (outboard)
start_tangent = spline.TangentAtStart
end_tangent = spline.TangentAtEnd

# For inboard direction:
# Start: tangent already points into the curve, keep it as-is
# End: tangent points away from curve, reverse it to point inboard
start_tangent_inboard = start_tangent   # Keep as-is (points into curve)
end_tangent_inboard = -end_tangent      # Reverse (points back toward curve)

# Normalize tangents
start_tangent_inboard.Unitize()
end_tangent_inboard.Unitize()

# Function to rotate a vector in YZ plane around a point
def rotate_vector_yz(vector, angle_degrees):
    """Rotate a vector in the YZ plane (around X axis)"""
    angle_rad = math.radians(angle_degrees)

    # Extract components
    x = vector.X
    y = vector.Y
    z = vector.Z

    # Rotate in YZ plane (around X axis)
    # X remains unchanged
    # Y' = Y * cos(θ) - Z * sin(θ)
    # Z' = Y * sin(θ) + Z * cos(θ)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    y_new = y * cos_a - z * sin_a
    z_new = y * sin_a + z * cos_a

    return rg.Vector3d(x, y_new, z_new)

# Determine which endpoint is entry (more positive Y) and which is exit
if start_pt.Y > end_pt.Y:
    # Start point is entry, end point is exit
    entry_pt = start_pt
    exit_pt = end_pt
    entry_tangent = start_tangent_inboard
    exit_tangent = end_tangent_inboard
    entry_angle_val = entry_angle
    exit_angle_val = exit_angle
else:
    # End point is entry, start point is exit
    entry_pt = end_pt
    exit_pt = start_pt
    entry_tangent = end_tangent_inboard
    exit_tangent = start_tangent_inboard
    entry_angle_val = entry_angle
    exit_angle_val = exit_angle

# Rotate tangent vectors in YZ plane
entry_tangent_rotated = rotate_vector_yz(entry_tangent, entry_angle_val)
exit_tangent_rotated = rotate_vector_yz(exit_tangent, exit_angle_val)

# Normalize rotated vectors and scale to line length
entry_tangent_rotated.Unitize()
entry_tangent_rotated *= line_length

exit_tangent_rotated.Unitize()
exit_tangent_rotated *= line_length

# Create lines from endpoints extending inboard
entry_line = rg.Line(entry_pt, entry_pt + entry_tangent_rotated)
exit_line = rg.Line(exit_pt, exit_pt + exit_tangent_rotated)
