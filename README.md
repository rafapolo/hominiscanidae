# Hominiscanidae

Arquivo digital do blog **Hominiscanidae** — um dos principais repositórios de música independente brasileira, ativo por mais de uma década com **10.583 posts**. Rock, metal, folk, eletrônico, experimental, indie, samba, MPB e muito mais — totalmente grátis e organizado para explorar.

> **Este repositório é uma instância do [tocador](https://github.com/rafapolo/tocador)**. O código do player, proxy e scripts vivem lá; aqui ficam apenas os dados e a configuração de deploy desta coleção.

## Catálogo

- **6.937 álbuns**, **4.991 artistas**, **9.424 horas**
- ~66 anos de música independente (1960–2026)
- 10.583 posts arquivados do blog; ~3.646 links mortos (permanentes)

## Pipeline

```bash
# 1. Scrape do blog (posts.json + posts/*.md)
python3 scripts/scrape/scrape_posts.py --sitemap

# 2. Download de todos os arquivos
python3 -u scripts/download/download_all.py

# 3. Descompactar e normalizar nomes de pasta
bun script/unzip.js
bun script/normalize-folders.js

# 4. Gerar catálogo a partir dos MP3s
cd script/generate-albums
./target/release/generate-albums /Volumes/EXTRA/hominiscanidae/unzips \
  ../../data/homi-albums.json.gz \
  --title "Hominiscanidae" \
  --subtitle "Música Independente Brasileira" \
  --hours "9424" \
  --base-url "https://uqt.xn--2dk.xyz/indie"

# 5. Sincronizar áudio para o bucket S3
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips bun tocador/script/sync-to-bucket.js

# 6. Redimensionar e fazer upload das capas (200px)
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips bun tocador/script/resize-cover-images.js

# 7. Classificar gêneros com ML (discogs400)
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips \
OUTPUT_FILE=data/genres.json \
python3 tocador/script/extract-genres.py --model discogs400
```

## Scripts locais

| Script | O que faz |
|---|---|
| `scripts/scrape/scrape_posts.py` | Scrape do blog: constrói/atualiza `posts.json` e `posts/*.md` |
| `scripts/download/download_all.py` | Download de todos os arquivos (64 workers, multi-serviço) |
| `script/unzip.js` | Descompacta `.rar`/`.zip` em `unzips/` |
| `script/normalize-folders.py` | Normaliza nomes de pasta para `AAAA - Artista - Álbum` |
| `script/generate-albums/` | Binário Rust: gera `data/homi-albums.json.gz` com metadados ID3 |

## Scrape

```bash
# Re-escanear sitemap (novos posts)
python3 scripts/scrape/scrape_posts.py --sitemap

# Re-scrape de uma label específica
python3 scripts/scrape/scrape_posts.py --label "https://www.hominiscanidae.org/search/label/NOME"

# Verificar posts vazios
find posts/ -empty
```

## Download

```bash
# Download normal
python3 -u scripts/download/download_all.py > /dev/null 2>&1 &

# Reabilitar mega: remover a linha "return skip-mega" no dispatcher (~linha 520)
```

## Licença e direitos

Mantido para fins educacionais e de preservação cultural. Os direitos pertencem aos respectivos artistas e detentores.

Se você é titular de direitos e deseja que algum conteúdo seja removido, abra uma [issue](https://github.com/rafapolo/hominiscanidae/issues).

---

[Visite o acervo →](https://rafapolo.github.io/hominiscanidae/)
