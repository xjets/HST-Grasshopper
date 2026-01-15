"""
Grasshopper Python component for generating MatCap and grid texture file paths.

Inputs:
    selMatCap (int): Material capture selection number
    tex_fill (int): Index for fill type (0, 1, 2, 3, 4, 5)
    tex_space (int): Index for space type (0, 1, 2)
    tex_gutter (int): Index for gutter width type (0, 1, 2)
    tex_radius (int): Index for corner radius type (0, 1, 2, 3)
    base_path (str): Base path for matcap textures
    grid_path (str): Base path for grid textures
    pattern_path (str): Base path for pattern textures

Output:
    path_to_texture (str): Complete file path to the selected texture
"""

# Hard-coded arrays for fill, space, and gutter types
fillArray = ["tra", "whi", "c1", "c2", "c3", "c4", "c5"]
spaceArray = ["tra", "whi", "bla"]
gutterArray = ["w1", "w2", "w3", "w4", "w5"]
radiusArray = ["r1", "r2", "r3", "r4"]


# Validate inputs
if selMatCap is None:
    path_to_texture = ""
elif selMatCap <= 32:
    # MatCap range: 1-32
    # Format: base_path + "matcap" + (100 + selMatCap) + ".png"
    # Example: selMatCap=5 -> "matcap105.png"
    matcap_number = 100 + selMatCap
    path_to_texture = base_path + "matcap" + str(matcap_number).zfill(3) + ".png"

elif selMatCap >= 33 and selMatCap <= 48:
    # Grid range: 33-48
    # Format: grid_(number)_(gutterArray)_(radiusArray)_(fillArray)_(spaceArray).png
    # Example: selMatCap=35, tex_gutter=2, tex_radius=1, tex_fill=0, tex_space=0 -> "grid_04_w3_r2_tra_tra.png"
    grid_number = selMatCap - 31

    # Validate indices
    gutter_idx = max(0, min(4, tex_gutter if tex_gutter is not None else 0))
    radius_idx = max(0, min(3, tex_radius if tex_radius is not None else 0))
    fill_idx = max(0, min(6, tex_fill if tex_fill is not None else 0))
    space_idx = max(0, min(2, tex_space if tex_space is not None else 0))

    gutter_str = gutterArray[gutter_idx]
    radius_str = radiusArray[radius_idx]
    fill_str = fillArray[fill_idx]
    space_str = spaceArray[space_idx]

    path_to_texture = grid_path + "grid_" + str(grid_number).zfill(2) + "_" + gutter_str + "_" + radius_str + "_" + fill_str + "_" + space_str + ".png"

elif selMatCap >= 49:
    # Pattern range: 49+
    # Format: pattern_path + "matcap" + (100 + (selMatCap - 48)) + ".png"
    # Example: selMatCap=49 -> "matcap101.png"
    # Example: selMatCap=50 -> "matcap102.png"
    pattern_number = 100 + (selMatCap - 48)
    path_to_texture = pattern_path + "matcap" + str(pattern_number).zfill(3) + ".png"

else:
    # Out of range - return empty
    path_to_texture = ""
