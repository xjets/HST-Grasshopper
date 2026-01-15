# Symmetrical surface creation by averaging original and mirrored surfaces
# November 2025, Claude
#
# Purpose: Takes a roughly symmetric NURBS surface and creates a perfectly
# symmetric version by averaging the original surface with its YZ-plane mirror.
#
# Inputs:
#   S - NURBS surface (roughly symmetric across YZ plane) - set to "Item" access
#
# Output:
#   a - Symmetrical NURBS surface (average of original and mirrored)

import Rhino.Geometry as rg

# Verify input exists and is valid
if S:
    # Get the NURBS surface (convert if needed)
    if isinstance(S, rg.Brep):
        # If it's a Brep, extract the first face as NURBS surface
        if S.Faces.Count > 0:
            nurbs_surface = S.Faces[0].ToNurbsSurface()
        else:
            nurbs_surface = None
    elif isinstance(S, rg.NurbsSurface):
        nurbs_surface = S
    else:
        nurbs_surface = None

    if nurbs_surface:
        # Get control point grid dimensions
        u_count = nurbs_surface.Points.CountU
        v_count = nurbs_surface.Points.CountV

        # Mirror transform across YZ plane (X=0)
        mirror_plane = rg.Plane.WorldYZ
        mirror_transform = rg.Transform.Mirror(mirror_plane)

        # Create mirrored surface
        mirrored_surface = nurbs_surface.Duplicate()
        mirrored_surface.Transform(mirror_transform)

        # Determine which direction to flip by comparing first-to-last distances
        # The direction that spans the surface (larger distance) should be flipped

        # Get corner control points
        cp_u0v0 = nurbs_surface.Points.GetControlPoint(0, 0).Location
        cp_u1v0 = nurbs_surface.Points.GetControlPoint(u_count - 1, 0).Location
        cp_u0v1 = nurbs_surface.Points.GetControlPoint(0, v_count - 1).Location

        # Calculate distances
        u_span = cp_u0v0.DistanceTo(cp_u1v0)
        v_span = cp_u0v0.DistanceTo(cp_u0v1)

        # Flip the direction with the smaller span (reversed logic)
        flip_u = u_span < v_span

        # Create new surface by averaging control points
        averaged_surface = nurbs_surface.Duplicate()

        # Average each control point between original and mirrored
        for u in range(u_count):
            for v in range(v_count):
                # Get control point from original surface
                cp_original = nurbs_surface.Points.GetControlPoint(u, v)

                # Get corresponding control point from mirrored surface
                # Flip the appropriate index based on which direction spans the surface
                if flip_u:
                    u_idx = (u_count - 1) - u
                    v_idx = v
                else:
                    u_idx = u
                    v_idx = (v_count - 1) - v

                cp_mirrored = mirrored_surface.Points.GetControlPoint(u_idx, v_idx)

                # Average the locations
                avg_x = (cp_original.Location.X + cp_mirrored.Location.X) / 2.0
                avg_y = (cp_original.Location.Y + cp_mirrored.Location.Y) / 2.0
                avg_z = (cp_original.Location.Z + cp_mirrored.Location.Z) / 2.0

                # Average the weight
                avg_weight = (cp_original.Weight + cp_mirrored.Weight) / 2.0

                # Set the averaged control point
                new_cp = rg.ControlPoint(rg.Point3d(avg_x, avg_y, avg_z), avg_weight)
                averaged_surface.Points.SetControlPoint(u, v, new_cp)

        # Output the symmetrical surface
        a = averaged_surface
    else:
        a = None  # Failed to extract NURBS surface
else:
    a = None  # Handle missing input
