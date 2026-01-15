# Surface orientation checker and flipper
# November 2025, Claude
#
# Purpose: Takes a surface and evaluates the normal at UV center (0.5, 0.5).
# Outputs the surface oriented up (normal facing +Z) and down (normal facing -Z).
#
# Inputs:
#   S - Surface (Brep or NurbsSurface) - set to "Item" access
#
# Outputs:
#   upSurf - Surface with middle normal facing positive Z
#   downSurf - Surface with middle normal facing negative Z (flipped)

import Rhino.Geometry as rg

# Verify input exists and is valid
if S:
    # Get the surface (convert if needed)
    if isinstance(S, rg.Brep):
        # If it's a Brep, extract the first face
        if S.Faces.Count > 0:
            surface = S.Faces[0]
        else:
            surface = None
    elif isinstance(S, rg.NurbsSurface):
        surface = S
    else:
        surface = None

    if surface:
        # Evaluate normal at UV center (0.5, 0.5)
        # Get the domain of the surface
        u_domain = surface.Domain(0)
        v_domain = surface.Domain(1)

        # Calculate middle UV coordinates
        u_mid = u_domain.Mid
        v_mid = v_domain.Mid

        # Evaluate the normal at the middle point
        normal = surface.NormalAt(u_mid, v_mid)

        # Check if normal is facing more up (+Z) or down (-Z)
        # Compare Z component of normal vector
        facing_up = normal.Z > 0

        # Create outputs based on orientation
        if facing_up:
            # Surface already faces up
            if isinstance(S, rg.Brep):
                upSurf = S
                downSurf = S.DuplicateBrep()
                downSurf.Flip()
            else:
                upSurf = S
                downSurf = S.Duplicate()
                downSurf.Reverse(0)  # Flip surface by reversing U direction
        else:
            # Surface faces down, needs to be flipped for upSurf
            if isinstance(S, rg.Brep):
                downSurf = S
                upSurf = S.DuplicateBrep()
                upSurf.Flip()
            else:
                downSurf = S
                upSurf = S.Duplicate()
                upSurf.Reverse(0)  # Flip surface by reversing U direction

        # Debug output
        print("Middle UV: ({}, {})".format(u_mid, v_mid))
        print("Normal at center: {}".format(normal))
        print("Normal.Z: {}".format(normal.Z))
        print("Facing up: {}".format(facing_up))
    else:
        upSurf = None
        downSurf = None
else:
    upSurf = None
    downSurf = None
