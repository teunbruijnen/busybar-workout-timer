// Writes the app's menu icons into src/appmeta, for the build to package.
import { writeFileSync } from "node:fs";
import { deflateSync } from "node:zlib";

const FOLDER = new URL("../src/appmeta/", import.meta.url);

function chunk(tag, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(tag), data]);
  const crc = Buffer.alloc(4);
  let c = ~0;
  for (const byte of body) {
    c ^= byte;
    for (let i = 0; i < 8; i++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
  }
  crc.writeUInt32BE(~c >>> 0);
  return Buffer.concat([length, body, crc]);
}

/** `pixels` maps a character to its bytes; colorType 6 is RGBA, 0 is grey. */
function png(name, rows, pixels, colorType) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(rows[0].length, 0);
  header.writeUInt32BE(rows.length, 4);
  header[8] = 8;
  header[9] = colorType;
  const raw = rows.flatMap((row) => [0, ...[...row].flatMap((ch) => pixels[ch])]);
  writeFileSync(
    new URL(name, FOLDER),
    Buffer.concat([
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
      chunk("IHDR", header),
      chunk("IDAT", deflateSync(Buffer.from(raw))),
      chunk("IEND", Buffer.alloc(0)),
    ]),
  );
}

png(
  "icon_front_8x8.png",
  ["...##...", "..####..", ".#.ww.#.", "#..ww..#", "#..www.#", "#......#", ".#....#.", "..####.."],
  { ".": [0, 0, 0, 0], "#": [0, 255, 64, 255], w: [255, 255, 255, 255] },
  6,
);
png(
  "icon_back_11x11.png",
  [
    "....###....",
    ".....#.....",
    "...#####...",
    "..#.....#..",
    ".#...#...#.",
    ".#...#...#.",
    ".#...##..#.",
    ".#.......#.",
    "..#.....#..",
    "...#####...",
    "...........",
  ],
  { ".": [0], "#": [255] },
  0,
);
