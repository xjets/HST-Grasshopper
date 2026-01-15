import Rhino.Geometry as rg
import math

# Inputs:
# equator_curve: Rhino.Geometry.Curve (expects a 3D curve)
# location: float in [0, 1]
# length: float
# angle: float (degrees)
# G3_ratio: float

# 1. Evaluate "mid_point" on the curve
curve_domain = equator_curve.Domain
t = curve_domain.T0 + (curve_domain.T1 - curve_domain.T0) * location
mid_point = equator_curve.PointAt(t)

# 2. Get local tangent at this location (this will be rotation axis)
tangent = equator_curve.TangentAt(t)
tangent.Unitize()

# 3. Find a local "up" or reference direction not parallel to the tangent
# We'll use the world Z axis as default up, unless it's parallel to tangent
z_axis = rg.Vector3d(0,0,1)
if abs(tangent * z_axis) > 0.999: # Nearly parallel
    ref_dir = rg.Vector3d(1,0,0) # Use global X if tangent is almost Z
else:
    ref_dir = z_axis

# 4. Construct lower and upper lines along "reference" direction
# The directions will be rotated around the equator (tangent) axis below

# The reference "down" direction (will be rotated about axis)
down_dir = rg.Vector3d(ref_dir)
down_dir.Unitize()

# 5. Lower ("mag_line") line, downward from mid_point
start_lower = mid_point
end_lower = mid_point + down_dir * -length
mag_line = rg.Line(start_lower, end_lower).ToNurbsCurve()

# 6. Upper line ("G3_line"), upward, scaled by G3_ratio
start_upper = mid_point
end_upper = mid_point + down_dir * (length * G3_ratio)
G3_line = rg.Line(start_upper, end_upper).ToNurbsCurve()

# 7. Rotation around equator (tangent at mid_point), using supplied angle
rot_rad = math.radians(angle)
rot_axis = tangent # already unitized
rot_center = mid_point
rot_transform = rg.Transform.Rotation(rot_rad, rot_axis, rot_center)

mag_line.Transform(rot_transform)
G3_line.Transform(rot_transform)

skirt_point = mag_line.PointAtEnd
G3_point = G3_line.PointAtEnd

# Grasshopper outputs (assign as needed)
# mag_line = mag_line
# mid_point = mid_point
# G3_point = G3_point
# skirt_point = skirt_point
