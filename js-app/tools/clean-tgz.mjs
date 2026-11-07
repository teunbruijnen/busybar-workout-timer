// Blanks the build machine's user and group in dist/<id>.tgz: the release file is public.
import { readFileSync, writeFileSync } from "node:fs";
import { gunzipSync, gzipSync } from "node:zlib";

const BLOCK = 512;
const { id } = JSON.parse(readFileSync(new URL("../src/appmeta/manifest.json", import.meta.url), "utf8"));
const file = new URL(`../dist/${id}.tgz`, import.meta.url);
const tar = gunzipSync(readFileSync(file));

for (let at = 0; at < tar.length && tar[at] !== 0; ) {
  if (tar.toString("latin1", at + 257, at + 262) !== "ustar") throw new Error("not a tar header at " + at);
  // Extended headers could hold the user, or a Mac's file attributes, out of this script's reach.
  const name = tar.toString("latin1", at, at + 100).replace(/\0.*$/s, "");
  if ("xgLK".includes(String.fromCharCode(tar[at + 156])) || /(^|\/)\._/.test(name)) {
    throw new Error("extended header or Mac metadata in the package: " + name);
  }
  tar.write("0000000\0", at + 108, "latin1"); // uid
  tar.write("0000000\0", at + 116, "latin1"); // gid
  tar.fill(0, at + 265, at + 329); // user and group names
  tar.fill(" ", at + 148, at + 156); // the checksum counts its own field as spaces
  let sum = 0;
  for (let i = at; i < at + BLOCK; i++) sum += tar[i];
  tar.write(sum.toString(8).padStart(6, "0") + "\0 ", at + 148, "latin1");
  const size = parseInt(tar.toString("latin1", at + 124, at + 136), 8);
  at += BLOCK + Math.ceil(size / BLOCK) * BLOCK;
}
writeFileSync(file, gzipSync(tar, { level: 9 }));
