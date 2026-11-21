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
    syringe.hook(
        0x00730B9C,
        "DeployCommand_FirstPass_SkipNonDeployers",
        7,
        skipNonDeployers,
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

// --- Deploy on a selection is its own inverse ----------------------------

/// The game's INI reader (CCINIClass), opaque here.
const Ini = opaque {};
const thiscall: std.lang.CallingConvention = .{ .x86_thiscall = .{} };
const ReadBool = *const fn (
    ini: *Ini,
    section: [*:0]const u8,
    key: [*:0]const u8,
    fallback: u8,
) callconv(thiscall) u8;
const ReadString = *const fn (
    ini: *Ini,
    section: [*:0]const u8,
    key: [*:0]const u8,
    fallback: [*:0]const u8,
    buffer: [*]u8,
    buffer_size: u32,
) callconv(thiscall) i32;
const WhatAmI = *const fn (object: *const anyopaque) callconv(thiscall) i32;

const rules_ini_address = 0x00887048; // CCINIClass::INI_Rules
const read_bool: ReadBool = @ptrFromInt(0x005295F0); // INIClass::ReadBool
const read_string: ReadString = @ptrFromInt(0x00528A10); // INIClass::ReadString

/// ObjectClass::CurrentObjects, a DynamicVectorClass<ObjectClass *>.
const selected_items_address = 0x00A8ECBC;
const selected_count_address = 0x00A8ECC8;
/// Far above any selection the game can make; more means a corrupt vector.
const selected_objects_max = 0x10000;

/// AbstractClass::WhatAmI is the 12th entry of every object's vtable.
const what_am_i_slot = 0x2C / 4;
const abstract_flags_offset_bytes = 0x14;
const abstract_flag_techno: u32 = 0x1;
const type_id_offset_bytes = 0x24; // AbstractTypeClass::ID
/// A type ID is at most 24 characters, the length the engine keeps.
const type_id_size_max = 25;

const What = enum(i32) {
    unit = 1,
    aircraft = 2,
    building = 6,
    infantry = 15,
    _,
};

/// Where the first pass moves on to the next selected object.
const deploy_first_pass_next = 0x00730C10;

/// Whether the selection holds a techno without LowDeployPriority, worked
/// out once per command, at the first pass's first object. The game runs
/// its commands on one thread.
var selection_has_normal_priority = false;

/// Deploy on a selection (DeployCommandClass::Execute) first looks at every
/// selected deployer, infantry that can deploy and units with
/// IsSimpleDeployer: if some are deployed and some are not, the second pass
/// sends Deploy only to those that are not, so the group ends up deployed;
/// otherwise every one toggles. Two kinds of unit sit in that first look
/// without taking part, and each stops a second Deploy from undoing the
/// first:
/// - A unit whose Deploy converts it into another type (Ares
///   Convert.Deploy: the mode toggles) comes out as a fresh, undeployed
///   unit, so it always counts as not deployed. Deploy on GIs and Bulldogs
///   digs the GIs in; the next sees "GIs deployed, a Bulldog not", leaves
///   the GIs dug in and toggles the Bulldogs back.
/// - A unit Phobos leaves out of the command (LowDeployPriority, while a
///   unit without it is selected) still counts as not deployed, so the next
///   Deploy leaves the dug-in GIs alone and skips it too: nothing happens.
/// Leave both out of the first look, so it judges only units that keep a
/// deployed state and receive the command. Both settings are read from the
/// rules INI, which stays loaded for the whole game. At 0x00730B9C the
/// first pass holds the object in ESI and its index in EDI.
fn skipNonDeployers(registers: *Registers) u32 {
    const rules = global(?*Ini, rules_ini_address).* orelse return syringe.resume_original;
    const object: *const anyopaque = @ptrFromInt(registers.esi);
    const selected_count = global(i32, selected_count_address).*;
    assert(selected_count > 0);
    assert(selected_count <= selected_objects_max);
    assert(registers.edi < @as(u32, @intCast(selected_count)));
    if (registers.edi == 0) {
        selection_has_normal_priority = selectionHasNormalPriority(rules, selected_count);
    }
    const what = whatAmI(object);
    const type_id = technoTypeId(object, what) orelse return syringe.resume_original;
    // Phobos skips a low-priority unit only beside one without the flag;
    // alone, a unit with it has no such neighbour, so this needs no count.
    if (selection_has_normal_priority) {
        if (lowDeployPriority(rules, type_id)) return deploy_first_pass_next;
    }
    if (what == .unit) {
        if (convertsOnDeploy(rules, type_id)) return deploy_first_pass_next;
    }
    return syringe.resume_original;
}

fn selectionHasNormalPriority(rules: *Ini, selected_count: i32) bool {
    assert(selected_count > 0);
    assert(selected_count <= selected_objects_max);
    const items = global([*]const ?*const anyopaque, selected_items_address).*;
    for (items[0..@intCast(selected_count)]) |maybe_object| {
        const object = maybe_object orelse continue;
        if (field(u32, object, abstract_flags_offset_bytes) & abstract_flag_techno == 0) continue;
        const type_id = technoTypeId(object, whatAmI(object)) orelse continue;
        if (!lowDeployPriority(rules, type_id)) return true;
    }
    return false;
}

fn whatAmI(object: *const anyopaque) What {
    const vtable = field([*]const WhatAmI, object, 0);
    return @fromBackingInt(vtable[what_am_i_slot](object));
}

/// The ID of a selected techno's type: Unit and Aircraft keep the type at
/// 0x6C4, Infantry at 0x6C0, Building at 0x520; any other object has none.
fn technoTypeId(object: *const anyopaque, what: What) ?[*:0]const u8 {
    const type_object = switch (what) {
        .unit, .aircraft => field(?*const anyopaque, object, 0x6C4),
        .infantry => field(?*const anyopaque, object, 0x6C0),
        .building => field(?*const anyopaque, object, 0x520),
        _ => return null,
    } orelse return null;
    const id: [*:0]const u8 = @ptrCast(@as([*]const u8, @ptrCast(type_object)) +
        type_id_offset_bytes);
    assert(id[0] != 0);
    return id;
}

fn lowDeployPriority(rules: *Ini, type_id: [*:0]const u8) bool {
    return read_bool(rules, type_id, "LowDeployPriority", 0) != 0;
}

fn convertsOnDeploy(rules: *Ini, type_id: [*:0]const u8) bool {
    var value: [type_id_size_max]u8 = undefined;
    const length = read_string(rules, type_id, "Convert.Deploy", "", &value, value.len);
    assert(length >= 0);
    assert(length < value.len);
    const converts_to = value[0..@intCast(length)];
    if (converts_to.len == 0) return false;
    return !std.ascii.eqlIgnoreCase(converts_to, "none");
}
