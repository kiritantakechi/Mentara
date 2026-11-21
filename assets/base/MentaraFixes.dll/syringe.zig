//! Syringe's hook ABI, as Syringe 0.7 and SyringeEx read it.
//!
//! Syringe injects every DLL in the game directory that carries a
//! `.syhks00` section. Each entry of that section names an exported
//! function to call when execution reaches the entry's address. The jump
//! Syringe writes there overwrites some bytes; they are replayed when the
//! hook returns `resume_original`, and any other return value is the
//! address to continue at.

const std = @import("std");
const assert = std.debug.assert;

/// The register snapshot a hook receives: origin and flags, then the
/// general registers in `pushad` order. A hook may change them.
pub const Registers = extern struct {
    origin: u32,
    flags: u32,
    edi: u32,
    esi: u32,
    ebp: u32,
    esp: u32,
    ebx: u32,
    edx: u32,
    ecx: u32,
    eax: u32,
};

/// The return value that replays the overwritten bytes and goes on.
pub const resume_original: u32 = 0;

/// A hook: given the registers, returns `resume_original` or the address
/// to continue at.
pub const Body = fn (registers: *Registers) u32;

const section_name = ".syhks00";

/// Syringe declares its table entry 16-byte aligned and walks the section
/// with that stride, so a packed 12-byte entry misreads every entry after
/// the first.
const Entry = extern struct {
    address: u32,
    overwritten_size: u32,
    name: [*:0]const u8,
    padding: u32 = 0,
};

const entry_stride = 16;

comptime {
    assert(@sizeOf(Entry) == entry_stride);
}

/// Syringe jumps to a hook with `jmp rel32`, which takes 5 bytes.
const overwritten_size_min = 5;

/// Exports `body` as `name` and the `.syhks00` entry that has Syringe call
/// it when execution reaches `address`, replacing `overwritten_size` bytes
/// that end on an instruction boundary.
pub fn hook(
    comptime address: u32,
    comptime name: [:0]const u8,
    comptime overwritten_size: u32,
    comptime body: Body,
) void {
    comptime assert(address != 0);
    comptime assert(overwritten_size >= overwritten_size_min);
    comptime assert(name.len > 0);
    const Hook = struct {
        fn call(registers: *Registers) callconv(.c) u32 {
            return body(registers);
        }

        const entry: Entry align(entry_stride) = .{
            .address = address,
            .overwritten_size = overwritten_size,
            .name = name.ptr,
        };
    };
    @export(&Hook.call, .{ .name = name });
    @export(&Hook.entry, .{ .name = "syringe_entry_" ++ name, .section = section_name });
}
