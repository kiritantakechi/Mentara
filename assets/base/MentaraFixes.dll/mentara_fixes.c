/*
 * Engine fixes for Mental Omega that need only Ares, no Phobos.
 *
 * `just assets` builds this into overlays/base/MentaraFixes.dll, which
 * Syringe injects alongside Ares, so the base and Phobos profiles both
 * carry every fix. Where Phobos ships the same fix, the hook mirrors
 * it at the same address, so loading both is harmless.
 */
#include "syringe.h"

/* SessionClass::Instance.GameMode; GameMode::Campaign is 0. */
#define SESSION_GAME_MODE (*(volatile const int *)0x00A8B238)
#define GAME_MODE_CAMPAIGN 0

/*
 * ScenarioClass::ReadMap reads the multiplayer [Header] block (map
 * bounds and up to eight Waypoint start points) without resetting it
 * first; only the random-map path is meant to use this reader. The
 * CnCNet spawner sends every -SPAWN game through it, and campaign
 * maps have no [Header], so the start-point loop runs for whatever
 * count the uninitialized field holds. That is harmless while the
 * memory happens to be zero; under Wine it held leftover UTF-16 text
 * (a count near 7.3 million) and the loop ran off the object.
 * Campaigns have no start points, so skip the block, exactly as
 * Phobos's ScenarioClass_ReadMap_SkipHeaderInCampaign does.
 */
DEFINE_HOOK(0x00689EB0, ScenarioReadMap_SkipCampaignHeader, 6)
{
    (void)R;
    return SESSION_GAME_MODE == GAME_MODE_CAMPAIGN ? 0x00689FC0 : 0;
}

/*
 * Multiplayer start positions, first pass (a virtual shared by every
 * MPGameModeClass): each house with a preset start index reads
 * startWaypoints[index] and marks slot index of the 16-entry "taken"
 * table at ScenarioClass+0x1180. The index is not checked against the
 * map. The CnCNet client writes 90 for a spectator's spawn location,
 * so every game with a spectator reads 360 bytes into the waypoint
 * vector's 40-byte buffer and writes past the taken table into
 * ScenarioClass. Whether the read faults depends on the heap layout:
 * LAN and online spectator games crashed here (0x005D6C21, ESI = 90).
 *
 * Skip any index that is not one of the map's start waypoints. Such a
 * house was never found in the taken table anyway, so the second pass
 * already places it (an observer gets YR's observer cell) exactly as
 * before; only the out-of-bounds read and write go away.
 *
 * At 0x005D6C1D: ESI is the house's start index (-2, random, is
 * skipped just before), and the stack holds the start waypoints as a
 * DynamicVectorClass<CellStruct> at ESP+0x08, whose Count is at +0x10.
 */
#define PRESET_START_NEXT_HOUSE 0x005D6C36
#define START_WAYPOINT_COUNT(esp) (*(const int *)((esp) + 0x08 + 0x10))

DEFINE_HOOK(0x005D6C1D, MPGameMode_PresetStarts_SkipMissingWaypoint, 7)
{
    const int start = (int)R->ESI;
    return start >= 0 && start < START_WAYPOINT_COUNT(R->ESP)
        ? 0
        : PRESET_START_NEXT_HOUSE;
}
