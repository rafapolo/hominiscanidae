# Plano: hominiscanidae → S3 playable archive

## Estado atual

- 10.583 posts | ~6.660 baixados em `/Volumes/EXTRA/hominiscanidae/`
- Formatos: 5.460 `.rar`/`.zip`, 870 `.mp3`, 437 `.m4a`, 29 `.flac`/`.ogg`/`.wav`
- ~3.546 dead links (permanentes), 228 bloqueados no mega

## O que vem do uqt

### Scripts reaproveitáveis (com ajuste de config)

| Script | O que faz | Mudança necessária |
|---|---|---|
| `script/generate-albums.js` | Lê MP3s de `unzips/`, gera JSON gzipado com metadados | Mudar caminho base |
| `script/sync-to-bucket.js` | Compara local vs S3, faz upload do diff com 20 workers | Mudar `LOCAL_DIR` |
| `script/dedup-albums.js` | Detecta e remove álbuns duplicados pelo fingerprint de faixas | Sem alteração |
| `script/find-untagged.js` | Lista MP3s sem ID3 tags completas | Sem alteração |
| `script/resize-cover-images.js` | Redimensiona capas e sobe para S3 | Mudar `SOURCE_DIR` |
| `script/filter-albums-by-s3.js` | Remove do JSON álbuns sem arquivos no S3 | Mudar alias/prefix |

## O que está faltando

### Script de unzip (elo faltante)

Os arquivos em `/Volumes/EXTRA/hominiscanidae/` chegam como `.rar`/`.zip` nomeados com slugs do blog. Precisa de um passo que:

1. Lê `posts.json` para mapear slug → artista/título/ano
2. Extrai cada `.rar`/`.zip` numa pasta `AAAA - Artista - Álbum/`
3. Move `.mp3`/`.m4a`/`.flac`/`.ogg`/`.wav` avulsos para pastas de álbum próprias
4. Outputa tudo em `unzips/` no formato que `generate-albums.js` espera

### Script de conversão para MP3 (elo faltante)

Após o unzip, todos os formatos não-MP3 precisam ser convertidos:

1. Varre `unzips/` recursivamente buscando `.m4a`, `.flac`, `.ogg`, `.wav`
2. Converte cada arquivo para `.mp3` via `ffmpeg` (mantendo tags ID3)
3. Remove o original após conversão bem-sucedida
4. Preserva as pastas `AAAA - Artista - Álbum/` intactas

## Pipeline completo

```
/Volumes/EXTRA/hominiscanidae/  (arquivos brutos)
        ↓  script/unzip.js  (a criar)
unzips/  (pastas AAAA - Artista - Álbum/, com mp3/m4a/flac/ogg/wav)
        ↓  script/convert-to-mp3.js  (a criar, usa ffmpeg)
unzips/  (somente .mp3)
        ↓  script/find-untagged.js  (do uqt)
        ↓  (MusicBrainz Picard / fix-tags para os sem tag)
        ↓  script/generate-albums.js  (do uqt)
js/homi-albums.json.gz
        ↓  script/resize-cover-images.js  (do uqt)
S3: hominiscanidae/*/capa-min.jpg
        ↓  script/sync-to-bucket.js  (do uqt)
S3: hominiscanidae/*/*.mp3
        ↓  script/filter-albums-by-s3.js  (do uqt)
js/homi-albums.json.gz  (só o que existe no S3, resultado final)
```

## Ordem de execução

1. Criar `script/unzip.js` — extrai arquivos, organiza em `unzips/`
2. Criar `script/convert-to-mp3.js` — converte m4a/flac/ogg/wav para mp3 via ffmpeg
3. Rodar `find-untagged.js` — identificar arquivos sem tags
4. Rodar `generate-albums.js` — gerar JSON
5. Rodar `sync-to-bucket.js` — subir para S3
6. Rodar `resize-cover-images.js` — capas no S3
7. Rodar `filter-albums-by-s3.js` — gerar `homi-albums.json.gz` final
