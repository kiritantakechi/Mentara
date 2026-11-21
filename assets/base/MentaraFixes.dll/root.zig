//! Engine fixes for Mental Omega that need only Ares, no Phobos.
//!
//! `just assets` builds this into overlays/base/MentaraFixes.dll, which
//! Syringe injects alongside Ares, so the base and Phobos profiles both
//! carry every fix. Where Phobos ships the same fix, the hook mirrors it at
//! the same address, so loading both is harmless.

const std = @import("std");
const assert = std.debug.assert;

const syringe = @import("syringe.zig");
const Registers = syringe.Registers;

/// A failed safety check traps, so the game stops in the hook that found
/// the bad state, and its crash log names it, instead of running on.
pub const panic = std.debug.no_panic;

comptime {
    syringe.hook(0x00689EB0, "ScenarioReadMap_SkipCampaignHeader", 6, skipCampaignHeader);
    syringe.hook(
        0x005D6C1D,
        "MPGameMode_PresetStarts_SkipMissingWaypoint",
        7,
        skipMissingStartWaypoint,
    );
}

// --- The game's memory ---------------------------------------------------

/// A value the game keeps at a fixed address.
fn global(comptime T: type, comptime address: u32) *const volatile T {
    return @ptrFromInt(address);
}

/// A field `offset_bytes` into a game object.
fn field(comptime T: type, object: *const anyopaque, comptime offset_bytes: u32) T {
    const bytes: [*]const u8 = @ptrCast(object);
    const pointer: *align(1) const T = @ptrCast(bytes + offset_bytes);
    return pointer.*;
}

/// SessionClass::Instance.GameMode; GameMode::Campaign is 0.
const session_game_mode_address = 0x00A8B238;
const game_mode_campaign = 0;

// --- Campaigns read no multiplayer header --------------------------------

/// The end of ScenarioClass::ReadMap's multiplayer [Header] block.
const read_map_header_end = 0x00689FC0;

/// ScenarioClass::ReadMap reads the multiplayer [Header] block (map bounds
/// and up to eight Waypoint start points) without resetting it first; only
/// the random-map path is meant to use this reader. The CnCNet spawner
/// sends every -SPAWN game through it, and campaign maps have no [Header],
/// so the start-point loop runs for whatever count the uninitialized field
/// holds. That is harmless while the memory happens to be zero; under Wine
/// it held leftover UTF-16 text (a count near 7.3 million) and the loop ran
/// off the object. Campaigns have no start points, so skip the block,
/// exactly as Phobos's ScenarioClass_ReadMap_SkipHeaderInCampaign does.
fn skipCampaignHeader(registers: *Registers) u32 {
    _ = registers;
    const game_mode = global(i32, session_game_mode_address).*;
    if (game_mode == game_mode_campaign) return read_map_header_end;
    return syringe.resume_original;
}

// --- Spectators have no start waypoint -----------------------------------

/// Where the first placement pass moves on to the next house.
const preset_start_next_house = 0x005D6C36;
/// The start waypoints sit on the stack as a DynamicVectorClass<CellStruct>
/// at ESP+0x08, whose Count is at +0x10.
const start_waypoint_count_offset_bytes = 0x08 + 0x10;
/// A map names at most eight start waypoints (Waypoint1-8 in [Header]).
const start_waypoints_max = 8;

/// Multiplayer start positions, first pass (a virtual shared by every
/// MPGameModeClass): each house with a preset start index reads
/// startWaypoints[index] and marks slot index of the 16-entry "taken" table
/// at ScenarioClass+0x1180. The index is not checked against the map. The
/// CnCNet client writes 90 for a spectator's spawn location, so every game
/// with a spectator reads 360 bytes into the waypoint vector's 40-byte
/// buffer and writes past the taken table into ScenarioClass. Whether the
/// read faults depends on the heap layout: LAN and online spectator games
/// crashed here (0x005D6C21, ESI = 90).
///
/// Skip any index that is not one of the map's start waypoints. Such a
/// house was never found in the taken table anyway, so the second pass
/// already places it (an observer gets YR's observer cell) exactly as
/// before; only the out-of-bounds read and write go away. At 0x005D6C1D,
/// ESI is the house's start index (-2, random, is skipped just before).
fn skipMissingStartWaypoint(registers: *Registers) u32 {
    const start: i32 = @bitCast(registers.esi);
    const waypoints = @as(*const i32, @ptrFromInt(registers.esp +
        start_waypoint_count_offset_bytes)).*;
    assert(waypoints >= 0);
    assert(waypoints <= start_waypoints_max);
    if (start < 0) return preset_start_next_house;
    if (start >= waypoints) return preset_start_next_house;
    return syringe.resume_original;
}
