# Hominiscanidae

Arquivo digital do blog **Hominiscanidae** — um dos principais repositórios de música independente brasileira, ativo por mais de uma década com **10.583 posts**. **9.424 horas** de música — rock, metal, folk, eletrônico, experimental, indie, samba, MPB e muito mais — totalmente grátis e organizado para explorar.

> **Este repositório é uma instância do [tocador](https://github.com/rafapolo/tocador)** — a plataforma de player de arquivo. O código do player, proxy e scripts vivem lá; aqui ficam apenas os dados e a configuração de deploy desta coleção específica.

## Números

### Catálogo publicado
- **6.937 álbuns** indexados
- **33.309 faixas** indexadas
- **4.991 artistas**
- **~66 anos** de música independente (1960–2026)
- **9.424 horas** de música

### Scrape completo
- **10.583 posts** arquivados do blog
- **6.937 downloads** concluídos (65,5%) — 370+ GB
- ~3.646 links mortos (permanentes)

## Como o acervo foi gerado

### Pipeline de dados

```bash
# 1. Scrape do blog (posts.json + posts/*.md)
python3 scripts/scrape/scrape_posts.py --sitemap

# 2. Download de todos os arquivos
python3 -u scripts/download/download_all.py

# 3. Descompactar e normalizar nomes de pasta
node script/unzip.js
node script/normalize-folders.js   # ou python3 script/normalize-folders.py

# 4. Gerar catálogo de álbuns a partir dos MP3s
cd script/generate-albums
./target/release/generate-albums /Volumes/EXTRA/hominiscanidae/unzips \
  ../../js/homi-albums.json.gz \
  --title "Hominiscanidae" \
  --subtitle "Música Independente Brasileira" \
  --hours "9424" \
  --base-url "https://uqt.xn--2dk.xyz/indie"

# 5. Sincronizar áudio para o bucket S3
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips node tocador/script/sync-to-bucket.js

# 6. Redimensionar e fazer upload das capas (200px)
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips node tocador/script/resize-cover-images.js

# 7. Classificar gêneros com ML (Essentia + TensorFlow)
ARCHIVE_DIR=/Volumes/EXTRA/hominiscanidae/unzips \
OUTPUT_FILE=/path/to/genres.json \
python3 tocador/script/extract-genres.py --model discogs400
```

### Arquitetura
- **Player**: HTML5 + CSS3 + JavaScript vanilla — código em [`tocador/`](https://github.com/rafapolo/tocador), servido pelo GitHub Pages
- **Dados**: `js/homi-albums.json.gz` — catálogo gzipado (~860 KB), carregado assincronamente e descomprimido via `DecompressionStream` nativa do browser
- **Gêneros**: `genres.json` — classificação por faixa via ML (Essentia + discogs400, 400 estilos)
- **Capas e áudio**: Servidos pelo proxy em `https://uqt.xn--2dk.xyz/indie/…`
- **Proxy**: Node.js + S3 SDK — acessa o armazenamento privado; os arquivos nunca expostos diretamente
- **Deployment**: GitHub Pages (player) + Haloy + Docker (proxy)

## Scripts

| Script | O que faz |
|---|---|
| `scripts/scrape/scrape_posts.py` | Scrape do blog: constrói/atualiza `posts.json` e `posts/*.md` |
| `scripts/download/download_all.py` | Download de todos os arquivos (64 workers, multi-serviço) |
| `script/unzip.js` | Descompacta `.rar`/`.zip` em `unzips/` |
| `script/normalize-folders.py` | Normaliza nomes de pasta para `AAAA - Artista - Álbum` |
| `script/generate-albums/` | Binário Rust: gera `js/homi-albums.json.gz` com metadados ID3 |
| `script/sync-to-bucket.js` | Sincroniza MP3s locais com o bucket S3 |
| `script/resize-cover-images.js` | Redimensiona capas e faz upload para S3 |
| `tocador/script/extract-genres.py` | Classificação de gênero por ML |

## Scrape

```bash
# Re-escanear sitemap (novos posts):
python3 scripts/scrape/scrape_posts.py --sitemap

# Re-scrape de uma label/série específica:
python3 scripts/scrape/scrape_posts.py --label "https://www.hominiscanidae.org/search/label/NOME"

# Verificar arquivos .md vazios:
find posts/ -empty
```

## Download

```bash
# Download normal (sem mega se quota esgotada):
python3 -u scripts/download/download_all.py > /dev/null 2>&1 &

# Reabilitar mega: remover a linha "return skip-mega" no dispatcher (~linha 520)
```

## Licença e direitos

Este acervo é mantido exclusivamente para fins educacionais e de preservação cultural. Os direitos sobre as gravações pertencem aos seus respectivos artistas e detentores. Nenhum conteúdo é disponibilizado para fins comerciais.

Se você é titular de direitos e deseja que algum conteúdo seja removido, abra uma [issue](https://github.com/rafapolo/hominiscanidae/issues).

---

**Feito com amor para preservar a música independente brasileira**

[Visite o acervo →](https://rafapolo.github.io/hominiscanidae/)
