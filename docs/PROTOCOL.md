# ROG MAXIMUS Z890 EXTREME LCD – USB protocol

Reverse-engineered from USB captures of Armoury Crate 6.5.14.0 on Windows, then verified on Linux
against panel firmware **0107** (`ALDR4-S7R7-0107`) with a camera pointed at the screen.
Not affiliated with ASUS. Other firmware versions may differ.

## Device

| | |
|---|---|
| USB ID | `0b05:1bd4` "Motherboard LCD Panel" |
| Interface 0 | vendor class, **bulk OUT 0x02** (file data), bulk IN 0x82 (unused) |
| Interface 1 | HID, 64-byte interrupt endpoints 0x01 / 0x81, 65-byte reports incl. report ID |
| Screen | 720 × 1280, portrait, ~64 MB flash for user files |

All commands are HID output reports `EC <cmd> <args…>` zero-padded to 65 bytes. The panel answers
with an input report `EC <cmd> <data…>`; a bare `EC <cmd>` is an ACK. Some read commands answer with
a different id (`EC 82`→`EC 02`, `EC DC`→`EC 5C`, `EC F1`→`EC 71`). Asynchronous status reports use
report ID `EE`. No keep-alive is needed.

## Commands

| Command | Reply | Meaning |
|---|---|---|
| `EC 82` | `EC 02 00 "ALDR4-S7R7-0107"` | firmware string |
| `EC DC` | `EC 5C 00 <16 B>` | read power block |
| `EC 5C 01 <16 B>` | `EC 5C` | write power block |
| `EC 51 <type> <store> <index>` | `EC 51` or `EC 51 02` | choose what is shown (`02` = rejected) |
| `EC 51` | `EC 51 [..]` | read selection (rarely used) |
| `EC 52 00 <rows-1> 00 <theme-1>` | `EC 52` | hardware-monitor layout |
| `EC 53 <slot> <label 18 B> <value>` | `EC 53` | hardware-monitor text for one slot |
| `EC 71 01 01`, then `EC F1` | `EE 12`, `EC 71 …` | storage info |
| `EC 72 01 <ftype> <slot>` | `EC 72` | select user file (ftype `01` JPEG, `00` GIF) |
| `EC 73 01` | `EE 13 00 01` | begin upload |
| `EC 7F 02 <size, little endian>` | `EC 7F 00 00 10` | announce size |
| bulk 0x02, 4096-byte chunks | `EE 14 00 00 <n>` each | file data (last chunk zero-padded) |
| `EC 73 FF` | `EE 13 00 FF` | commit upload |
| `EC 73 03` | `EE 13 00 03` | delete selected file |
| `EC 70 5A 01`, `EC 70 A5 01` | | erase all user files |

### Display selection (`EC 51`)

| type | store | index | Shows |
|---|---|---|---|
| `14` | `00` | 0–3 | built-in animations: 0 = neon ROG, 1 = starfield ROG. 2 and 3 are also accepted but look the same as 0 and 1 (Armoury Crate only uses 0 and 1) |
| `11` | `00` | 0–5 | built-in still wallpapers |
| `11` | `01` | 0–7 | uploaded JPEG slots (an empty slot shows black; the command is accepted either way) |
| `21` | – | – | hardware monitor (after `EC 52`) |
| `23` | – | – | built-in temperature-warning screen (⚠ on a starfield) |
| `20` | – | – | blank screen |

`14 01 xx` (uploaded animation) is **always rejected** with `02`, even for GIFs encoded exactly as
Armoury Crate encodes them (full frames, no transparency, per-frame palettes). Uploaded GIFs are stored
but cannot be shown on the main screen with this firmware – which matches Armoury Crate only allowing
JPEG for custom images.

**Transitions:** every image change blanks the screen for ~200 ms and fades the new picture in over
~350 ms. More than ~3 changes per second produce streaks and then a black screen until the changes
stop, so "flip-book" animation by switching slots is not possible; slideshows are.

### Power block (`EC DC` / `EC 5C`)

16 bytes after the rw flag (offset 0 = `00` read / `01` write):

```
off  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
     rw 00 00 B0 00 00 00 B1 [ T  S  I] 00 00 B5 [ T  S  I]
```

* B0 = B1 = brightness % (10–100). B5 = brightness used while asleep, or `01` = sleep display off.
* Offsets 8–10 and 14–16 each look like a display reference (`type store index`, as in `EC 51`).
  Armoury Crate always writes `14 00 <w>` to both (built-in animation *w* = the "sleep wallpaper").
  Display off zeroes 8, 10, 14, 16; sleep display off zeroes 14 and 16.
* Temperature-warning settings never reach the panel – Armoury Crate implements them on the PC.

### Hardware monitor (`EC 52` / `EC 53`)

<p>
  <img src="images/lcd-hwmon-theme1.jpg" alt="Theme 1, three rows" height="320">
  <img src="images/lcd-hwmon-gauge.jpg" alt="Theme 4, five values" height="320">
</p>

Theme 1 with three rows (slot 1 top, slot 0 middle, slot 2 bottom) and theme 4 with five values
(slot 0 in the gauge).

* Themes 1–3 support 1–3 rows, theme 4 (gauge) 1–5.
* `EC 53`: byte 2 = slot, bytes 3–20 = label (UTF-8, NUL-padded, max 17 chars), from byte 21 the value
  (UTF-8). The panel just draws text; the PC sends new values every few seconds.
* Slot 0 is always the large main value. Themes 1–3: 2 rows = slot 0 top, slot 1 bottom; 3 rows = slot 1
  top, slot 0 middle, slot 2 bottom. Theme 4: slot 0 centre gauge, 1 top-left, 2 bottom-right,
  3 bottom-left, 4 top-right. Theme 4 shows a unit on its own line if the value contains `\n`.
* Unit glyphs: `U+2103 ℃` → °C, `U+218A ↊` → V, `U+218C ↌` → RPM, `U+3393 ㎓` → GHz.

### Storage info

`EC 71 00 01 <u32 total KB> <u32 free KB> …`; byte 11 of the reply data is a bitmap of used GIF slots,
byte 16 a bitmap of used JPEG slots (8 slots).

### Upload sequence (JPEG)

```
EC 71 01 01 → EC 71, EE 12      EC F1 → EC 71 …storage…
EC 72 01 01 <slot> → EC 72
EC 73 01 → EC 73, EE 13 00 01
EC 7F 02 <size LE> → EC 7F 00 00 10
bulk 4096 B × n → EE 14 00 00 <n> after each
EC 73 FF → EC 73, EE 13 00 FF
```
Data is the plain JPEG file. Uploads run at roughly 30–40 KB/s (flash writes).
