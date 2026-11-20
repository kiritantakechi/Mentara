/*
 * Engine fixes for Mental Omega that need only Ares, no Phobos.
 *
 * `just hooks` builds this into overlays/base/MentaraFixes.dll, which
 * Syringe injects alongside Ares. Each hook mirrors the fix Phobos
 * ships at the same address, so the base and Phobos profiles behave
 * alike, and loading both is harmless.
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
