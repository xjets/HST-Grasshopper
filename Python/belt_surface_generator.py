"""
Belt Surface Generator - Grasshopper Python Component
Generates a periodic NURBS surface connecting two trimmed convex surfaces
with controllable tangency and cross-section profiles using Sweep 2 Rails.

Component Inputs:
    dome - Trimmed NURBS surface (convex up)
    bowl - Trimmed NURBS surface (convex down)
    A_position - float (0.0-1.0), default: 0.33
    B_position - float (0.0-1.0), default: 0.66
    entry_angle_dome - float (degrees)
    entry_angle_bowl - float (degrees)
    A_angle_dome - float (degrees)
    A_angle_bowl - float (degrees)
    B_angle_dome - float (degrees)
    B_angle_bowl - float (degrees)
    exit_angle_dome - float (degrees)
    exit_angle_bowl - float (degrees)
    entry_mag_dome - float (0.0-1.0)
    entry_mag_bowl - float (0.0-1.0)
    A_mag_dome - float (0.0-1.0)
    A_mag_bowl - float (0.0-1.0)
    B_mag_dome - float (0.0-1.0)
    B_mag_bowl - float (0.0-1.0)
    exit_mag_dome - float (0.0-1.0)
    exit_mag_bowl - float (0.0-1.0)
    include_A - bool, default: True
    include_B - bool, default: True
    intermediate_sections - int, default: 3 (number of interpolated sections between each primary control point)
    transition_bias - float (0.0-1.0), default: 0.5
    rebuild_tolerance - float

Component Outputs:
    belt_surface - NURBS surface from Sweep 2 Rails
    warnings - List of warning strings
    debug_curves - List of cross-section bezier curves
    debug_vectors - List of vectors for visualization
"""

import Rhino.Geometry as rg
import Rhino
import math
import scriptcontext as sc

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_trim_curve(brep_surface):
    """
    Extract the outermost trim curve from a trimmed BrepFace.
    Returns a 3D curve representing the surface boundary.
    """
    if not brep_surface:
        return None

    face = brep_surface.Faces[0]

    # Get the outer loop
    loops = face.Loops
    outer_loop = None

    for loop in loops:
        if loop.LoopType == rg.BrepLoopType.Outer:
            outer_loop = loop
            break

    if not outer_loop:
        # Fallback: find longest loop
        max_length = 0
        for loop in loops:
            crv = loop.To3dCurve()
            if crv and crv.GetLength() > max_length:
                max_length = crv.GetLength()
                outer_loop = loop

    if outer_loop:
        trim_curve = outer_loop.To3dCurve()
        return trim_curve

    return None


def find_yz_plane_intersections(curve):
    """
    Find intersection points of curve with YZ plane (X=0).
    Entry point = most POSITIVE Y (at X=0)
    Exit point = most NEGATIVE Y (at X=0)
    Returns dict with 'entry' and 'exit' points and parameters.
    """
    if not curve:
        return None

    # Create YZ plane at X=0
    plane = rg.Plane(rg.Point3d(0, 0, 0), rg.Vector3d(1, 0, 0))

    # Find all intersection points
    intersections = rg.Intersect.Intersection.CurvePlane(curve, plane, sc.doc.ModelAbsoluteTolerance)

    if not intersections or len(intersections) == 0:
        # Fallback: find points closest to YZ plane (X=0)
        t_list = []
        for i in range(0, 360, 10):
            t = curve.Domain.ParameterAt(i / 360.0)
            t_list.append(t)

        points = [curve.PointAt(t) for t in t_list]

        # Filter to points closest to X=0
        x_threshold = 1.0  # Within 1 unit of YZ plane
        yz_points = [(pt, t) for pt, t in zip(points, t_list) if abs(pt.X) < x_threshold]

        if len(yz_points) < 2:
            # Use all points if we can't find enough near YZ plane
            yz_points = list(zip(points, t_list))

        # Sort by Y coordinate
        yz_points.sort(key=lambda p: p[0].Y)

        entry_pt, entry_t = yz_points[-1]   # Most +Y (FLIPPED)
        exit_pt, exit_t = yz_points[0]      # Most -Y (FLIPPED)

        return {
            'entry': {'point': entry_pt, 'param': entry_t},
            'exit': {'point': exit_pt, 'param': exit_t}
        }

    # Find intersection points on YZ plane (X=0)
    int_points = []
    for event in intersections:
        if event.IsPoint:
            int_points.append({
                'point': event.PointA,
                'param': event.ParameterA
            })

    if len(int_points) == 0:
        return None

    # Sort by Y coordinate
    int_points.sort(key=lambda p: p['point'].Y)

    return {
        'entry': int_points[-1],     # Most +Y (at X=0) FLIPPED
        'exit': int_points[0]        # Most -Y (at X=0) FLIPPED
    }


def reorder_curve_to_start(curve, start_param):
    """
    Reorder a periodic curve to start at the specified parameter.
    Returns a new curve that starts at start_param.
    """
    if not curve:
        return None

    # If curve is not periodic/closed, can't reorder
    if not curve.IsClosed:
        return curve

    # Change the seam to start at the specified parameter
    new_curve = curve.DuplicateCurve()

    # Use ChangeClosedCurveSeam to move the seam
    success = new_curve.ChangeClosedCurveSeam(start_param)

    if success:
        return new_curve
    else:
        return curve


def get_perpendicular_to_trim(surface, edge_curve, param):
    """
    Get vector perpendicular to trim edge, tangent to surface, pointing outward.
    Uses robust inward detection, then reverses for outward.
    """
    face = surface.Faces[0]

    # Get point and curve tangent
    pt = edge_curve.PointAt(param)
    crv_tangent = edge_curve.TangentAt(param)

    # Get surface normal
    success, u, v = face.ClosestPoint(pt)
    if not success:
        return None

    srf_normal = face.NormalAt(u, v)

    # Calculate perpendicular vector (tangent to surface, perpendicular to edge)
    perp_vec = rg.Vector3d.CrossProduct(srf_normal, crv_tangent)
    perp_vec.Unitize()

    # Robust inward detection (multiple test points)
    tol = sc.doc.ModelAbsoluteTolerance
    test_distances = [tol * 10, tol * 50, tol * 100]
    interior_count = 0
    exterior_count = 0

    for test_dist in test_distances:
        test_pt_3d = pt + (perp_vec * test_dist)
        success, test_u, test_v = face.ClosestPoint(test_pt_3d)

        if success:
            relation = face.IsPointOnFace(test_u, test_v)

            if relation == rg.PointFaceRelation.Interior:
                interior_count += 1
            elif relation == rg.PointFaceRelation.Exterior:
                exterior_count += 1

    # Additional validation: check alignment with surface center
    srf_center = face.GetBoundingBox(True).Center
    to_center = srf_center - pt
    to_center_proj = to_center - (to_center * srf_normal) * srf_normal
    to_center_proj.Unitize()

    alignment_with_center = rg.Vector3d.Multiply(perp_vec, to_center_proj)

    # Decision logic
    if exterior_count > interior_count:
        perp_vec.Reverse()
    elif exterior_count == interior_count and alignment_with_center < 0:
        perp_vec.Reverse()

    # Reverse for OUTWARD direction (belt extends outward from surfaces)
    perp_vec.Reverse()

    return perp_vec


def get_curve_normal(curve, param):
    """
    Get curve normal vector (binormal) for rotation axis.
    """
    curvature = curve.CurvatureAt(param)
    tangent = curve.TangentAt(param)

    if curvature.Length < 1e-6:
        # Curve is nearly straight, use arbitrary perpendicular
        arbitrary = rg.Vector3d(0, 0, 1)
        if abs(tangent * arbitrary) > 0.9:
            arbitrary = rg.Vector3d(0, 1, 0)
        normal = rg.Vector3d.CrossProduct(tangent, arbitrary)
        normal.Unitize()
        return normal

    # Binormal is perpendicular to both tangent and curvature
    binormal = rg.Vector3d.CrossProduct(tangent, curvature)
    binormal.Unitize()
    return binormal


def rotate_vector(vector, angle_degrees, axis):
    """
    Rotate a vector around an axis by specified angle in degrees.
    """
    angle_radians = math.radians(angle_degrees)
    rotation = rg.Transform.Rotation(angle_radians, axis, rg.Point3d.Origin)

    rotated = rg.Vector3d(vector)
    rotated.Transform(rotation)
    return rotated


def rotate_vector_yz(vector, angle_degrees):
    """
    Rotate a vector in the YZ plane (around X axis).
    This provides consistent, predictable rotation regardless of local curve geometry.

    X remains unchanged
    Y' = Y * cos(θ) - Z * sin(θ)
    Z' = Y * sin(θ) + Z * cos(θ)
    """
    angle_rad = math.radians(angle_degrees)

    # Extract components
    x = vector.X
    y = vector.Y
    z = vector.Z

    # Rotate in YZ plane (around X axis)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)

    y_new = y * cos_a - z * sin_a
    z_new = y * sin_a + z * cos_a

    return rg.Vector3d(x, y_new, z_new)


def create_cubic_bezier(P0, P1, P2, P3):
    """
    Create a cubic Bezier curve from 4 control points.
    """
    bezier = rg.BezierCurve([P0, P1, P2, P3])
    nurbs_curve = bezier.ToNurbsCurve()
    return nurbs_curve


def interpolate_value(val_start, val_end, t, bias=0.5):
    """
    Interpolate between two values with bias curve.

    bias = 0.0: maintains source value longer, sharp transition near target
    bias = 0.5: symmetric/linear transition
    bias = 1.0: releases source early, maintains target longer
    """
    if bias < 0.5:
        # Favor source
        weight = pow(t, 1.0 / (2.0 * bias + 0.01))
    elif bias > 0.5:
        # Favor target
        weight = 1.0 - pow(1.0 - t, 1.0 / (2.0 * (1.0 - bias) + 0.01))
    else:
        # Linear
        weight = t

    return val_start + (val_end - val_start) * weight


# ============================================================================
# CONTROL POINT MANAGEMENT
# ============================================================================

class ControlPointDefinition:
    """Defines a control point location and its properties."""

    def __init__(self, name, param, angle_dome, angle_bowl, mag_dome, mag_bowl):
        self.name = name
        self.param = param  # 0.0 to 1.0 around the perimeter
        self.angle_dome = angle_dome
        self.angle_bowl = angle_bowl
        self.mag_dome = mag_dome
        self.mag_bowl = mag_bowl
        self.dome_point = None
        self.bowl_point = None
        self.dome_vector = None
        self.bowl_vector = None


def build_primary_control_points(exit_param, A_position, B_position, include_A, include_B,
                                   entry_angle_dome, entry_angle_bowl, entry_mag_dome, entry_mag_bowl,
                                   A_angle_dome, A_angle_bowl, A_mag_dome, A_mag_bowl,
                                   B_angle_dome, B_angle_bowl, B_mag_dome, B_mag_bowl,
                                   exit_angle_dome, exit_angle_bowl, exit_mag_dome, exit_mag_bowl):
    """
    Build sequence of PRIMARY control points (user-specified locations only).
    Returns sorted list of ControlPointDefinition objects with params from 0.0 to 1.0.

    exit_param: Parameter on rail where it crosses YZ plane (exit point)
    """
    control_points = []

    # Entry point (param 0.0)
    control_points.append(ControlPointDefinition(
        "entry", 0.0, entry_angle_dome, entry_angle_bowl, entry_mag_dome, entry_mag_bowl
    ))

    # A point - position in first half only (0.0 to exit_param)
    # A_position is 0-1 representing position within the first half
    if include_A:
        A_param = A_position * exit_param  # Scale to first half
        control_points.append(ControlPointDefinition(
            "A", A_param, A_angle_dome, A_angle_bowl, A_mag_dome, A_mag_bowl
        ))

    # B point - position in first half only (0.0 to exit_param)
    # B_position is 0-1 representing position within the first half
    if include_B:
        B_param = B_position * exit_param  # Scale to first half
        control_points.append(ControlPointDefinition(
            "B", B_param, B_angle_dome, B_angle_bowl, B_mag_dome, B_mag_bowl
        ))

    # Exit point (use actual YZ plane intersection param)
    control_points.append(ControlPointDefinition(
        "exit", exit_param, exit_angle_dome, exit_angle_bowl, exit_mag_dome, exit_mag_bowl
    ))

    # Mirror points (second half: exit_param to 1.0)
    # Mirrors should maintain same relative position from exit as originals from entry
    if include_B:
        # B_mirror at same relative position in second half as B in first half
        # If B is at 0.66 of first half, B_mirror is at 0.66 of second half
        B_mirror_param = exit_param + (1.0 - exit_param) * B_position
        control_points.append(ControlPointDefinition(
            "B_mirror", B_mirror_param, B_angle_dome, B_angle_bowl, B_mag_dome, B_mag_bowl
        ))

    if include_A:
        # A_mirror at same relative position in second half as A in first half
        # If A is at 0.33 of first half, A_mirror is at 0.33 of second half
        A_mirror_param = exit_param + (1.0 - exit_param) * A_position
        control_points.append(ControlPointDefinition(
            "A_mirror", A_mirror_param, A_angle_dome, A_angle_bowl, A_mag_dome, A_mag_bowl
        ))

    # Sort by param to ensure correct order
    control_points.sort(key=lambda cp: cp.param)

    return control_points


def build_intermediate_control_points(cp1, cp2, num_intermediates, bias):
    """
    Build intermediate control points between two primary control points.
    Interpolates angles and magnitudes using bias curve.
    Handles wrap-around when going from last point (near 1.0) back to first (0.0).

    Returns list of ControlPointDefinition objects (does NOT include cp1 or cp2).
    """
    intermediates = []

    # Check if we're wrapping around (cp2.param < cp1.param indicates wrap from end to start)
    wrapping = cp2.param < cp1.param
    
    # When wrapping, we need to fill the gap from cp1.param to 1.0
    # For a closed loop, we split this into: cp1.param -> 1.0, and skip the 0.0 -> cp2.param segment
    # since cp2 is already at 0.0 (entry point)
    
    for i in range(1, num_intermediates + 1):
        # Parameter along the interval from cp1 to cp2
        t = float(i) / (num_intermediates + 1)

        # Interpolate param (position around perimeter)
        if wrapping:
            # When wrapping, interpolate from cp1.param towards 1.0
            # We want to fill the gap from cp1.param to 1.0 (not wrap to 0.0 yet)
            # Calculate how far we are from cp1.param towards 1.0
            distance_to_1 = 1.0 - cp1.param  # e.g., if cp1 = 0.835, distance = 0.165
            total_wrap_distance = 1.0 - cp1.param + cp2.param  # Total wrap distance (e.g., 0.165 + 0.0 = 0.165)
            
            # Param should go from cp1.param towards 1.0
            param = cp1.param + distance_to_1 * t
            
            # Clamp to 1.0 if we overshoot (shouldn't happen, but safety check)
            if param > 1.0:
                param = 1.0
            elif param < cp1.param:
                param = cp1.param
        else:
            # Normal interpolation (no wrap)
            param = cp1.param + (cp2.param - cp1.param) * t

        # Interpolate angles and magnitudes with bias
        angle_dome = interpolate_value(cp1.angle_dome, cp2.angle_dome, t, bias)
        angle_bowl = interpolate_value(cp1.angle_bowl, cp2.angle_bowl, t, bias)
        mag_dome = interpolate_value(cp1.mag_dome, cp2.mag_dome, t, bias)
        mag_bowl = interpolate_value(cp1.mag_bowl, cp2.mag_bowl, t, bias)

        # Create intermediate control point
        name = f"{cp1.name}_to_{cp2.name}_{i}"
        intermediates.append(ControlPointDefinition(
            name, param, angle_dome, angle_bowl, mag_dome, mag_bowl
        ))

    return intermediates


def build_all_control_points(primary_cps, num_intermediates, bias):
    """
    Build complete list of control points including intermediates.

    Returns sorted list of all ControlPointDefinition objects.
    Ensures closure by adding a duplicate entry point at param = 1.0 if needed.
    """
    all_cps = []

    # Add all primary control points
    all_cps.extend(primary_cps)

    # Add intermediates between each consecutive pair
    for i in range(len(primary_cps)):
        cp1 = primary_cps[i]
        cp2 = primary_cps[(i + 1) % len(primary_cps)]  # Wrap around to close the loop

        intermediates = build_intermediate_control_points(cp1, cp2, num_intermediates, bias)
        all_cps.extend(intermediates)

    # Sort by param
    all_cps.sort(key=lambda cp: cp.param)

    # CRITICAL: Ensure closure by adding a point at param = 1.0 that matches entry (param = 0.0)
    # For a periodic closed loop, we MUST have a cross-section at both 0.0 and 1.0
    # These should be identical to ensure smooth closure

    # Find entry point (param = 0.0)
    entry_cp = None
    for cp in all_cps:
        if abs(cp.param) < 1e-6:  # Find entry point (param ~ 0.0)
            entry_cp = cp
            break

    if entry_cp:
        # Check if we already have a point at exactly 1.0
        has_closure = any(abs(cp.param - 1.0) < 1e-6 for cp in all_cps)

        if not has_closure:
            # Add closure point at param = 1.0 with same properties as entry
            closure_cp = ControlPointDefinition(
                "closure", 1.0,
                entry_cp.angle_dome, entry_cp.angle_bowl,
                entry_cp.mag_dome, entry_cp.mag_bowl
            )
            all_cps.append(closure_cp)
            all_cps.sort(key=lambda cp: cp.param)

    return all_cps


# ============================================================================
# MAIN ALGORITHM
# ============================================================================

def generate_belt_surface(dome, bowl,
                          A_position, B_position,
                          entry_angle_dome, entry_angle_bowl,
                          A_angle_dome, A_angle_bowl,
                          B_angle_dome, B_angle_bowl,
                          exit_angle_dome, exit_angle_bowl,
                          entry_mag_dome, entry_mag_bowl,
                          A_mag_dome, A_mag_bowl,
                          B_mag_dome, B_mag_bowl,
                          exit_mag_dome, exit_mag_bowl,
                          include_A, include_B,
                          intermediate_sections,
                          transition_bias, rebuild_tolerance):
    """
    Main belt surface generation algorithm using Sweep 2 Rails.

    Returns: (belt_surface, warnings, debug_curves, debug_vectors)
    """
    warnings = []
    debug_curves = []
    debug_vectors = []

    # ========================================================================
    # STEP 1: EXTRACT EDGE CURVES (RAILS)
    # ========================================================================

    dome_edge = extract_trim_curve(dome)
    bowl_edge = extract_trim_curve(bowl)

    if not dome_edge or not bowl_edge:
        warnings.append("ERROR: Could not extract trim curves from surfaces")
        return (None, warnings, debug_curves, debug_vectors)

    dome_edge_length = dome_edge.GetLength()
    bowl_edge_length = bowl_edge.GetLength()

    warnings.append(f"DEBUG: Dome edge length = {dome_edge_length:.2f}")
    warnings.append(f"DEBUG: Bowl edge length = {bowl_edge_length:.2f}")
    warnings.append(f"DEBUG: Length ratio (bowl/dome) = {bowl_edge_length/dome_edge_length:.3f}")

    # ========================================================================
    # STEP 2: FIND ENTRY POINTS ON RAILS (YZ plane intersections)
    # ========================================================================

    dome_intersections = find_yz_plane_intersections(dome_edge)
    bowl_intersections = find_yz_plane_intersections(bowl_edge)

    if not dome_intersections or not bowl_intersections:
        warnings.append("ERROR: Could not find YZ plane intersections")
        return (None, warnings, debug_curves, debug_vectors)

    dome_entry_param = dome_intersections['entry']['param']
    bowl_entry_param = bowl_intersections['entry']['param']

    warnings.append(f"DEBUG: Dome entry param = {dome_entry_param:.4f}")
    warnings.append(f"DEBUG: Bowl entry param = {bowl_entry_param:.4f}")

    # ========================================================================
    # STEP 3: REORDER RAILS TO START AT ENTRY POINTS
    # ========================================================================

    dome_rail = reorder_curve_to_start(dome_edge, dome_entry_param)
    bowl_rail = reorder_curve_to_start(bowl_edge, bowl_entry_param)

    # Reparameterize rails to 0-1 domain for easier calculation
    dome_rail.Domain = rg.Interval(0.0, 1.0)
    bowl_rail.Domain = rg.Interval(0.0, 1.0)

    # After reparameterizing, find the EXIT points (second YZ plane intersection)
    # These should be at the opposite end of the curve
    dome_intersections_reordered = find_yz_plane_intersections(dome_rail)
    bowl_intersections_reordered = find_yz_plane_intersections(bowl_rail)

    if not dome_intersections_reordered or not bowl_intersections_reordered:
        warnings.append("ERROR: Could not find YZ plane exit intersections after reordering")
        return (None, warnings, debug_curves, debug_vectors)

    # After reordering, entry should be at param ~0.0, exit at param ~0.5 or wherever it crosses YZ plane
    dome_exit_param = dome_intersections_reordered['exit']['param']
    bowl_exit_param = bowl_intersections_reordered['exit']['param']

    warnings.append(f"DEBUG: Dome exit param (after reorder) = {dome_exit_param:.4f}")
    warnings.append(f"DEBUG: Bowl exit param (after reorder) = {bowl_exit_param:.4f}")

    # ========================================================================
    # STEP 3.5: ALIGN CURVE DIRECTIONS
    # ========================================================================
    # Check if curves travel in the same direction by comparing tangent vectors
    # at the start point. If they point in opposite directions, reverse one.

    dome_tangent_start = dome_rail.TangentAt(dome_rail.Domain.Min)
    bowl_tangent_start = bowl_rail.TangentAt(bowl_rail.Domain.Min)

    # Project tangents to XY plane (looking down from top)
    dome_tangent_xy = rg.Vector3d(dome_tangent_start.X, dome_tangent_start.Y, 0)
    bowl_tangent_xy = rg.Vector3d(bowl_tangent_start.X, bowl_tangent_start.Y, 0)

    dome_tangent_xy.Unitize()
    bowl_tangent_xy.Unitize()

    # Dot product: positive = same direction, negative = opposite
    dot_product = rg.Vector3d.Multiply(dome_tangent_xy, bowl_tangent_xy)

    if dot_product < 0:
        # Curves travel in opposite directions, reverse bowl rail
        bowl_rail.Reverse()
        warnings.append("DEBUG: Bowl rail reversed to match dome rail direction")

        # CRITICAL: After reversing, we need to re-find the exit point
        # because the curve direction has changed
        bowl_rail.Domain = rg.Interval(0.0, 1.0)  # Re-reparameterize
        bowl_intersections_reordered = find_yz_plane_intersections(bowl_rail)
        if bowl_intersections_reordered:
            bowl_exit_param = bowl_intersections_reordered['exit']['param']
            warnings.append(f"DEBUG: Bowl exit param (after reverse) = {bowl_exit_param:.4f}")
    else:
        warnings.append("DEBUG: Rails already travel in same direction")

    warnings.append(f"DEBUG: Rails reordered and reparameterized to [0, 1]")

    # ========================================================================
    # STEP 4: BUILD PRIMARY CONTROL POINTS
    # ========================================================================

    primary_cps = build_primary_control_points(
        dome_exit_param,  # Use actual YZ plane intersection parameter
        A_position, B_position, include_A, include_B,
        entry_angle_dome, entry_angle_bowl, entry_mag_dome, entry_mag_bowl,
        A_angle_dome, A_angle_bowl, A_mag_dome, A_mag_bowl,
        B_angle_dome, B_angle_bowl, B_mag_dome, B_mag_bowl,
        exit_angle_dome, exit_angle_bowl, exit_mag_dome, exit_mag_bowl
    )

    warnings.append(f"DEBUG: Created {len(primary_cps)} primary control points")

    # ========================================================================
    # STEP 5: BUILD ALL CONTROL POINTS (PRIMARY + INTERMEDIATES)
    # ========================================================================

    all_cps = build_all_control_points(primary_cps, intermediate_sections, transition_bias)

    warnings.append(f"DEBUG: Total control points (with intermediates) = {len(all_cps)}")

    # Debug: Show parameter range
    if all_cps:
        min_param = min(cp.param for cp in all_cps)
        max_param = max(cp.param for cp in all_cps)
        warnings.append(f"DEBUG: Control point param range: {min_param:.6f} to {max_param:.6f}")

        # Check for closure point
        closure_exists = any(abs(cp.param - 1.0) < 1e-6 for cp in all_cps)
        warnings.append(f"DEBUG: Closure point at 1.0 exists: {closure_exists}")

    # ========================================================================
    # STEP 6: CALCULATE VECTORS AT EACH CONTROL POINT
    # ========================================================================

    for cp in all_cps:
        # Get dome point at this parameter
        dome_t = dome_rail.Domain.ParameterAt(cp.param)
        cp.dome_point = dome_rail.PointAt(dome_t)

        # NEW APPROACH: Entry/Exit use fixed YZ plane intersections
        # A/B (primary points) use closest point on bowl to dome's A/B
        # Intermediate points distributed evenly also use closest point

        # SPECIAL CASES: Entry and Exit at YZ plane intersections
        if cp.name == "entry":
            # Entry at param 0.0 on both curves (YZ plane, most +Y)
            bowl_t = bowl_rail.Domain.ParameterAt(0.0)
            cp.bowl_point = bowl_rail.PointAt(bowl_t)
        elif cp.name == "exit":
            # Exit at YZ plane intersection on bowl
            bowl_t = bowl_rail.Domain.ParameterAt(bowl_exit_param)
            cp.bowl_point = bowl_rail.PointAt(bowl_t)
        elif cp.name == "closure":
            # Closure wraps back to entry (param 1.0 = param 0.0)
            bowl_t = bowl_rail.Domain.ParameterAt(1.0)
            cp.bowl_point = bowl_rail.PointAt(bowl_t)
        else:
            # All other points (A, B, mirrors, intermediates): use CLOSEST POINT
            success, bowl_t = bowl_rail.ClosestPoint(cp.dome_point)
            if not success:
                warnings.append(f"ERROR: Could not find closest bowl point for {cp.name}")
                continue
            cp.bowl_point = bowl_rail.PointAt(bowl_t)

        # Debug: verify entry/exit/closure points are in correct sectors
        if cp.name == "entry":
            warnings.append(f"DEBUG: Entry dome point X={cp.dome_point.X:.4f}, Y={cp.dome_point.Y:.4f} (X~0, Y should be positive)")
            warnings.append(f"DEBUG: Entry bowl point X={cp.bowl_point.X:.4f}, Y={cp.bowl_point.Y:.4f} (X~0, Y should be positive)")
        elif cp.name == "exit":
            warnings.append(f"DEBUG: Exit dome point X={cp.dome_point.X:.4f}, Y={cp.dome_point.Y:.4f} (X~0, Y should be negative)")
            warnings.append(f"DEBUG: Exit bowl point X={cp.bowl_point.X:.4f}, Y={cp.bowl_point.Y:.4f} (X~0, Y should be negative)")
        elif cp.name == "closure":
            warnings.append(f"DEBUG: Closure dome point X={cp.dome_point.X:.4f}, Y={cp.dome_point.Y:.4f} (should match Entry)")
            warnings.append(f"DEBUG: Closure bowl point X={cp.bowl_point.X:.4f}, Y={cp.bowl_point.Y:.4f} (should match Entry)")

        # Calculate distance between dome and bowl at this location
        distance = cp.dome_point.DistanceTo(cp.bowl_point)

        if distance < sc.doc.ModelAbsoluteTolerance:
            warnings.append(f"WARNING: Zero distance at {cp.name}")
            distance = 1.0

        # ====================================================================
        # DOME VECTOR - ROTATE AROUND EDGE CURVE AS AXLE
        # ====================================================================
        # The edge curve acts as an axle/axis at each location
        # The perpendicular vector rotates around this axle (curve tangent direction)

        dome_perpendicular = get_perpendicular_to_trim(dome, dome_rail, dome_t)

        if dome_perpendicular:
            # Get curve tangent - this is the AXLE around which we rotate
            dome_curve_tangent = dome_rail.TangentAt(dome_t)
            dome_curve_tangent.Unitize()

            # Apply angle rotation around the curve tangent (the edge curve as axle)
            dome_vector = rotate_vector(dome_perpendicular, cp.angle_dome, dome_curve_tangent)
            dome_vector.Unitize()

            # Scale by magnitude, adjusted for local distance
            # Use local distance to ensure magnitude is appropriate for this location
            cp.dome_vector = dome_vector * (cp.mag_dome * distance)
        else:
            warnings.append(f"WARNING: Could not calculate dome vector for {cp.name}")
            cp.dome_vector = rg.Vector3d(0, 0, 1) * distance * 0.3

        # ====================================================================
        # BOWL VECTOR - ROTATE AROUND EDGE CURVE AS AXLE
        # ====================================================================
        # The edge curve acts as an axle/axis at each location
        # The perpendicular vector rotates around this axle (curve tangent direction)

        bowl_perpendicular = get_perpendicular_to_trim(bowl, bowl_rail, bowl_t)

        if bowl_perpendicular:
            # Get curve tangent - this is the AXLE around which we rotate
            bowl_curve_tangent = bowl_rail.TangentAt(bowl_t)
            bowl_curve_tangent.Unitize()

            # Apply angle rotation around the curve tangent (the edge curve as axle)
            bowl_vector = rotate_vector(bowl_perpendicular, cp.angle_bowl, bowl_curve_tangent)
            bowl_vector.Unitize()

            # Scale by magnitude, adjusted for local distance
            # Use local distance to ensure magnitude is appropriate for this location
            cp.bowl_vector = bowl_vector * (cp.mag_bowl * distance)
        else:
            warnings.append(f"WARNING: Could not calculate bowl vector for {cp.name}")
            cp.bowl_vector = rg.Vector3d(0, 0, -1) * distance * 0.3

        # Debug vectors
        debug_vectors.append(rg.Line(cp.dome_point, cp.dome_point + cp.dome_vector))
        debug_vectors.append(rg.Line(cp.bowl_point, cp.bowl_point + cp.bowl_vector))

    # ========================================================================
    # STEP 7: CREATE BEZIER CROSS-SECTION CURVES
    # ========================================================================

    cross_sections = []

    for cp in all_cps:
        if cp.dome_point and cp.bowl_point and cp.dome_vector and cp.bowl_vector:
            P0 = cp.dome_point
            P1 = rg.Point3d(cp.dome_point + cp.dome_vector)
            P2 = rg.Point3d(cp.bowl_point + cp.bowl_vector)
            P3 = cp.bowl_point

            bezier = create_cubic_bezier(P0, P1, P2, P3)

            if bezier and bezier.IsValid:
                cross_sections.append(bezier)
                debug_curves.append(bezier)
            else:
                warnings.append(f"ERROR: Invalid bezier curve at {cp.name}")
                return (None, warnings, debug_curves, debug_vectors)

    warnings.append(f"DEBUG: Created {len(cross_sections)} cross-section curves")

    # Check if first and last cross-sections are duplicates (both at entry point)
    if len(cross_sections) > 1:
        first_curve = cross_sections[0]
        last_curve = cross_sections[-1]

        first_start = first_curve.PointAtStart
        last_start = last_curve.PointAtStart

        distance = first_start.DistanceTo(last_start)

        if distance < sc.doc.ModelAbsoluteTolerance * 10:
            # Remove the duplicate closure curve for sweep
            cross_sections_for_sweep = cross_sections[:-1]
            warnings.append(f"DEBUG: Removed duplicate closure curve, using {len(cross_sections_for_sweep)} sections for sweep")
        else:
            cross_sections_for_sweep = cross_sections
            warnings.append(f"DEBUG: No duplicate detected, using all {len(cross_sections_for_sweep)} sections")
    else:
        cross_sections_for_sweep = cross_sections

    # ========================================================================
    # STEP 8: SWEEP 2 RAILS
    # ========================================================================

    # Perform Sweep 2 Rails
    # Since both rails are closed curves and we want a complete loop,
    # set closed=True to tell sweep to connect the last section back to the first
    sweep_breps = rg.Brep.CreateFromSweep(
        dome_rail,           # Rail 1
        bowl_rail,           # Rail 2
        cross_sections_for_sweep,      # Cross-section curves
        True,                # closed = True (closed in sweep direction to complete the loop)
        sc.doc.ModelAbsoluteTolerance
    )

    if not sweep_breps or len(sweep_breps) == 0:
        warnings.append("ERROR: Sweep 2 Rails failed")
        warnings.append(f"DEBUG: Rail 1 IsValid = {dome_rail.IsValid}, IsClosed = {dome_rail.IsClosed}")
        warnings.append(f"DEBUG: Rail 2 IsValid = {bowl_rail.IsValid}, IsClosed = {bowl_rail.IsClosed}")
        warnings.append(f"DEBUG: Number of cross-sections used = {len(cross_sections_for_sweep)}")
        warnings.append(f"DEBUG: First section valid = {cross_sections_for_sweep[0].IsValid if cross_sections_for_sweep else 'N/A'}")
        warnings.append(f"DEBUG: Last section valid = {cross_sections_for_sweep[-1].IsValid if cross_sections_for_sweep else 'N/A'}")
        return (None, warnings, debug_curves, debug_vectors)

    # Extract surface from Brep
    brep = sweep_breps[0]

    if not brep or brep.Faces.Count == 0:
        warnings.append("ERROR: Sweep result has no faces")
        return (None, warnings, debug_curves, debug_vectors)

    belt_surface = brep.Faces[0].ToNurbsSurface()

    if not belt_surface:
        warnings.append("ERROR: Failed to extract NURBS surface from sweep")
        return (None, warnings, debug_curves, debug_vectors)

    warnings.append(f"SUCCESS: Surface created, IsValid = {belt_surface.IsValid}")

    # ========================================================================
    # STEP 9: OPTIONAL REBUILD
    # ========================================================================

    if rebuild_tolerance and rebuild_tolerance > 0:
        try:
            num_u_pts = belt_surface.Points.CountU
            num_v_pts = belt_surface.Points.CountV

            rebuilt = belt_surface.Rebuild(
                3,  # U degree
                3,  # V degree
                int(num_u_pts * 1.5),
                int(num_v_pts * 1.5)
            )

            if rebuilt:
                belt_surface = rebuilt
                warnings.append("DEBUG: Surface rebuilt successfully")
        except:
            warnings.append("WARNING: Surface rebuild failed")

    return (belt_surface, warnings, debug_curves, debug_vectors)


# ============================================================================
# GRASSHOPPER COMPONENT EXECUTION
# ============================================================================

# Set default values for optional inputs
if A_position is None: A_position = 0.33
if B_position is None: B_position = 0.66
if include_A is None: include_A = True
if include_B is None: include_B = True
if intermediate_sections is None: intermediate_sections = 3
if transition_bias is None: transition_bias = 0.5
if rebuild_tolerance is None: rebuild_tolerance = 0.01

# Set default angles to 0 if not provided
if entry_angle_dome is None: entry_angle_dome = 0.0
if entry_angle_bowl is None: entry_angle_bowl = 0.0
if A_angle_dome is None: A_angle_dome = 0.0
if A_angle_bowl is None: A_angle_bowl = 0.0
if B_angle_dome is None: B_angle_dome = 0.0
if B_angle_bowl is None: B_angle_bowl = 0.0
if exit_angle_dome is None: exit_angle_dome = 0.0
if exit_angle_bowl is None: exit_angle_bowl = 0.0

# Set default magnitudes to 0.5 if not provided
if entry_mag_dome is None: entry_mag_dome = 0.5
if entry_mag_bowl is None: entry_mag_bowl = 0.5
if A_mag_dome is None: A_mag_dome = 0.5
if A_mag_bowl is None: A_mag_bowl = 0.5
if B_mag_dome is None: B_mag_dome = 0.5
if B_mag_bowl is None: B_mag_bowl = 0.5
if exit_mag_dome is None: exit_mag_dome = 0.5
if exit_mag_bowl is None: exit_mag_bowl = 0.5

# Execute main algorithm
if dome and bowl:
    belt_surface, warnings, debug_curves, debug_vectors = generate_belt_surface(
        dome, bowl,
        A_position, B_position,
        entry_angle_dome, entry_angle_bowl,
        A_angle_dome, A_angle_bowl,
        B_angle_dome, B_angle_bowl,
        exit_angle_dome, exit_angle_bowl,
        entry_mag_dome, entry_mag_bowl,
        A_mag_dome, A_mag_bowl,
        B_mag_dome, B_mag_bowl,
        exit_mag_dome, exit_mag_bowl,
        include_A, include_B,
        intermediate_sections,
        transition_bias, rebuild_tolerance
    )
else:
    warnings = ["ERROR: dome and bowl surfaces required"]
    belt_surface = None
    debug_curves = []
    debug_vectors = []
