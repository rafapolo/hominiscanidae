#!/usr/bin/env node
/**
 * Sample random tracks from homi-albums.json.gz and HEAD-request each one.
 * Usage: bun test-playback-sample.mjs [--n 200] [--acervo homi|uqt]
 * Exit code 0 = all ok, 1 = failures found.
 */
import { readFileSync } from 'fs';
import zlib from 'zlib';

const args = process.argv.slice(2);
const flag  = (f, def) => { const i = args.indexOf(f); return i >= 0 ? args[i + 1] : def; };
const N         = parseInt(flag('--n', '200'));
const ACERVO    = flag('--acervo', 'homi');
const CONCURRENCY = 1;  // proxy rate limit: 30 req cap, 0.5 tokens/s — stay serial
const DELAY_MS    = 2200; // 2.2s > 1/0.5 = 2s refill per token

const PATHS = {
  homi: '/Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz',
  uqt:  '/Users/polux/Projetos/uqt/data/uqt-albums.json.gz',
};

const db = JSON.parse(zlib.gunzipSync(readFileSync(PATHS[ACERVO])));
const base = db.meta.base_url;

// Collect all tracks
const allTracks = [];
for (const album of db.albums) {
  for (const track of album.tracks ?? []) {
    allTracks.push({ album, track });
  }
}

// Random sample without replacement
function sample(arr, n) {
  const copy = [...arr];
  const result = [];
  for (let i = 0; i < Math.min(n, copy.length); i++) {
    const idx = Math.floor(Math.random() * (copy.length - i)) + i;
    [copy[i], copy[idx]] = [copy[idx], copy[i]];
    result.push(copy[i]);
  }
  return result;
}

const selected = sample(allTracks, N);
console.log(`Testing ${selected.length} random tracks from ${ACERVO} (base: ${base})\n`);

async function checkTrack({ album, track }) {
  const url = `${base}/${encodeURI(album.path)}/${encodeURI(track.file)}`;
  try {
    const r = await fetch(url, { method: 'HEAD', signal: AbortSignal.timeout(10000) });
    return { ok: r.ok || r.status === 206, status: r.status, url };
  } catch (e) {
    return { ok: false, status: 'ERR', url, err: e.message };
  }
}

// Run with concurrency limit
let pass = 0, fail = 0;
const failures = [];

for (let i = 0; i < selected.length; i++) {
  const r = await checkTrack(selected[i]);
  if (r.ok) {
    pass++;
  } else {
    fail++;
    failures.push(r);
    console.error(`  FAIL ${r.status} ${r.url}`);
  }
  if ((i + 1) % 10 === 0) process.stdout.write(`\r  ${i + 1}/${selected.length} checked...`);
  await new Promise(res => setTimeout(res, DELAY_MS));
}

console.log(`\n\nResults: ${pass} ok / ${fail} failed / ${selected.length} total`);
console.log(`Pass rate: ${((pass / selected.length) * 100).toFixed(1)}%`);

if (failures.length) {
  console.log(`\nFirst 10 failures:`);
  failures.slice(0, 10).forEach(f => console.log(`  [${f.status}] ${f.url}`));
  process.exit(1);
}
