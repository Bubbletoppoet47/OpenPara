"""Orca's extrusion roles, in the order of Orca's enum (libslic3r/ExtrusionEntity.hpp, ExtrusionRole), with the names Orca writes after ;TYPE: in
G-code (ExtrusionEntity::role_to_string).  A role is stored as its number (uint8); these are the names for people and for the tests.
The numbers are the engine's, so a new Orca release that changes the enum needs this list changed with it (the engine tests compare them)."""

ROLES = (
    "Undefined",             # 0  erNone
    "Inner wall",            # 1  erPerimeter
    "Outer wall",            # 2  erExternalPerimeter
    "Overhang wall",         # 3  erOverhangPerimeter
    "Sparse infill",         # 4  erInternalInfill
    "Internal solid infill", # 5  erSolidInfill
    "Top surface",           # 6  erTopSolidInfill
    "Bottom surface",        # 7  erBottomSurface
    "Ironing",               # 8  erIroning
    "Bridge",                # 9  erBridgeInfill
    "Internal Bridge",       # 10 erInternalBridgeInfill
    "Gap infill",            # 11 erGapFill
    "Skirt",                 # 12 erSkirt
    "Brim",                  # 13 erBrim
    "Support",               # 14 erSupportMaterial
    "Support interface",     # 15 erSupportMaterialInterface
    "Support transition",    # 16 erSupportTransition
    "Prime tower",           # 17 erWipeTower
    "Custom",                # 18 erCustom
    "Multiple",              # 19 erMixed
)
ROLE_ID = {name: i for i, name in enumerate(ROLES)}


def role_name(i):
    """The name of role number i (as Orca writes it in G-code)."""
    return ROLES[int(i)]


def role_id(name):
    """The number of a role name; KeyError with the list of names when it is not one."""
    try:
        return ROLE_ID[name]
    except KeyError:
        raise KeyError("%r is not an Orca extrusion role; the roles are: %s" % (name, ", ".join(ROLES))) from None
