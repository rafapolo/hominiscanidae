#!/usr/bin/env node
/**
 * extract-genres.js  —  Wrapper Node.js para extract-genres.py
 *
 * Simplesmente spawna o script Python com os mesmos argumentos,
 * herdando stdin/stdout/stderr do terminal.
 *
 * Útil para integrar com ferramentas JS (npm scripts, etc.)
 * sem precisar chamar python3 diretamente.
 *
 * USO:
 *   node scripts/extract-genres.js                          # todos os álbuns
 *   node scripts/extract-genres.js --model discogs519       # modelo 519 classes
 *   node scripts/extract-genres.js --random 3               # teste em 3 aleatórios
 *   node scripts/extract-genres.js --albums "2012 - X"      # álbuns específicos
 *
 * Equivalente a:
 *   python3 scripts/extract-genres.py [args...]
 */

"use strict";

const { spawn } = require("child_process");
const path = require("path");

// Caminho para o script Python (mesmo diretório)
const py = path.join(__dirname, "extract-genres.py");

// Spawna python3 com todos os argumentos passados para este script
const child = spawn("python3", [py, ...process.argv.slice(2)], {
  stdio: "inherit", // conecta ao terminal do usuário
  env: process.env,  // herda PATH, ARCHIVE_DIR, OUTPUT_FILE, etc.
});

child.on("exit", (code) => process.exit(code ?? 0));
