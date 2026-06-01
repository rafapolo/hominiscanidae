#!/usr/bin/env node
'use strict';
/**
 * Copy HC ghost albums from wrong S3 prefix ({path}/) to correct (indie/{path}/).
 * sync-bandcamp-hc.py uploaded without the 'indie/' prefix.
 */
const { S3Client, ListObjectsV2Command, CopyObjectCommand } = require('@aws-sdk/client-s3');
const fs = require('fs'), path = require('path'), zlib = require('zlib');

function loadEnv() {
  for (const line of fs.readFileSync(path.resolve(__dirname, '../.env'), 'utf8').split('\n')) {
    const m = line.match(/^\s*([\w]+)\s*=\s*"?([^"]*)"?\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
  }
}
loadEnv();

const BUCKET = process.env.S3_BUCKET;
const s3 = new S3Client({
  endpoint: 'https://hel1.your-objectstorage.com', region: 'hel1',
  credentials: { accessKeyId: process.env.AWS_ACCESS_KEY_ID, secretAccessKey: process.env.AWS_SECRET_ACCESS_KEY },
  forcePathStyle: true,
});

const db = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.resolve(__dirname, '../data/homi-albums.json.gz'))));
const ghosts = db.albums.filter(a => a.has_cover === true).map(a => a.path);

async function listPrefix(prefix) {
  const keys = []; let token;
  do {
    const res = await s3.send(new ListObjectsV2Command({ Bucket: BUCKET, Prefix: prefix, ContinuationToken: token, MaxKeys: 1000 }));
    for (const o of res.Contents || []) keys.push(o.Key);
    token = res.IsTruncated ? res.NextContinuationToken : undefined;
  } while (token);
  return keys;
}

async function runPool(tasks, concurrency, fn) {
  let i = 0;
  async function worker() { while (i < tasks.length) { const t = tasks[i++]; await fn(t); } }
  await Promise.all(Array.from({ length: Math.min(concurrency, tasks.length) }, worker));
}

async function main() {
  console.log(`\n  Fixing S3 prefix for ${ghosts.length} ghost HC albums\n`);

  // Collect all keys that need copying
  const toCopy = [];
  for (const albumPath of ghosts) {
    const wrongPrefix = albumPath + '/';
    const keys = await listPrefix(wrongPrefix);
    for (const key of keys) {
      if (!key.startsWith('indie/')) {
        toCopy.push({ src: key, dst: 'indie/' + key });
      }
    }
  }

  console.log(`  Found ${toCopy.length} objects to copy\n`);
  if (toCopy.length === 0) { console.log('  Nothing to do.'); return; }

  let copied = 0, errors = 0;

  await runPool(toCopy, 16, async ({ src, dst }) => {
    try {
      await s3.send(new CopyObjectCommand({
        Bucket: BUCKET,
        CopySource: encodeURIComponent(BUCKET + '/' + src),
        Key: dst,
      }));
      copied++;
      if (copied % 50 === 0 || copied === toCopy.length) {
        process.stdout.write(`\r  Copied ${copied}/${toCopy.length}  errors=${errors}   `);
      }
    } catch (e) {
      errors++;
      console.error(`\n  ERR copying ${src}: ${e.message}`);
    }
  });

  process.stdout.write('\n');
  console.log(`\n  Done — copied=${copied}  errors=${errors}\n`);
}

main().catch(e => { console.error('\n  Fatal:', e.message); process.exit(1); });
