# Scripts do Hominiscanidae

Scripts para scrape, download e manutenção do acervo. Todos lêem `posts.json` e `posts/` relativos à raiz do projeto — rode a partir de qualquer diretório.

---

## Estrutura

```
scripts/
  scrape/     — scrape do blog e capas
  download/   — download dos arquivos de áudio
  covers/     — busca de capas para as pastas locais
  utils/      — utilitários de manutenção
```

---

## scrape/

### `scrape_posts.py` — Scrape do blog

Constrói e atualiza `posts.json` + `posts/<slug>.md` a partir do blog.

```bash
# Varrer sitemap completo (novos posts):
python3 scripts/scrape/scrape_posts.py --sitemap

# Re-scrape de uma label/série específica:
python3 scripts/scrape/scrape_posts.py --label "https://www.hominiscanidae.org/search/label/NOME"
```

O modo `--label` funciona offline: localiza os posts da série pelos slugs e conteúdo já em disco, depois re-faz o fetch apenas dos `.md` ausentes ou vazios.

### `scrape_covers.py` — Scrape de capas dos posts

Baixa as imagens de capa a partir dos links nos posts, redimensiona para 500×500 com título em overlay e salva em `/Volumes/EXTRA/hominiscanidae/covers/<slug>.jpg`.

```bash
python3 scripts/scrape/scrape_covers.py
```

---

## download/

### `download_all.py` — Downloader principal

Multi-serviço (Mega, MediaFire, Google Drive, Dropbox, Bandcamp, Archive.org, direct zip…), 64 workers paralelos. Lê `posts.json`, fileia os `not_downloaded` e registra resultados.

```bash
# Rodar em background, saída descartada:
python3 -u scripts/download/download_all.py > /dev/null 2>&1 &

# Com log visível:
python3 -u scripts/download/download_all.py
```

**Cycle de status:** `not_downloaded` → `downloaded` / `dead_link` / `blocked` / `failed`  
`failed` é resetado para `not_downloaded` a cada reinício.

**Mega:** desabilitar quando quota esgotada — remova a linha `return skip-mega` no dispatcher (~linha 517). Quota reseta ~6h após o último uso.

### `retry_bandcamp.py` — Retry de links Bandcamp

Para posts com status `dead_link` cujo download era Bandcamp: localiza a URL do artista nos `.md` locais e tenta baixar via `yt-dlp`.

```bash
python3 scripts/download/retry_bandcamp.py
```

### `retry_misc.py` — Retry de links variados

Tenta reprocessar links `bit.ly`, zips diretos, plugins WordPress e similares que falharam anteriormente.

```bash
python3 scripts/download/retry_misc.py
```

---

## covers/

Scripts para buscar capas nas pastas locais que têm áudio mas não têm `capa.jpg`.

### `fetch_covers.py` — Capas via Blogger CDN (passagem 1)

Extrai URLs de imagem do Blogger embutidas nos `posts/*.md` e baixa diretamente para a pasta do álbum em `unzips/`.

```bash
python3 scripts/covers/fetch_covers.py
```

### `fetch_covers2.py` — Capas via múltiplas fontes (passagem 2)

Segunda passagem para as pastas ainda sem capa. Tenta em ordem: Blogger CDN (formato antigo e novo), página do álbum no Bandcamp (`og:image`), URLs diretas do `bcbits.com`.

```bash
python3 scripts/covers/fetch_covers2.py
```

---

## utils/

### `fetch_sizes.py` — Tamanhos de arquivo

Faz HEAD nas URLs de download de `posts.json` para preencher `file_size` nos posts ainda sem essa informação. Normaliza URLs do Dropbox e Google Drive para forçar o `Content-Length`.

```bash
python3 scripts/utils/fetch_sizes.py
```

### `fix_unzip_names.py` — Normalização de nomes de pasta

Renomeia as pastas em `unzips/` para o formato `AAAA - Artista - Álbum`. Extrai ano do nome do arquivo de download ou da URL do post; extrai artista/álbum do link de download, Bandcamp ou slug.

```bash
# Dry-run (apenas mostra o que seria renomeado):
python3 scripts/utils/fix_unzip_names.py

# Aplicar renomeações:
python3 scripts/utils/fix_unzip_names.py --apply

# Mostrar apenas casos incertos:
python3 scripts/utils/fix_unzip_names.py --uncertain
```

---

## Manutenção periódica

```bash
# 1. Pegar novos posts
python3 scripts/scrape/scrape_posts.py --sitemap

# 2. Verificar .md vazios
find posts/ -empty

# 3. Baixar tudo
python3 -u scripts/download/download_all.py > /dev/null 2>&1 &

# 4. Normalizar nomes das pastas descompactadas
python3 scripts/utils/fix_unzip_names.py --apply

# 5. Buscar capas faltantes
python3 scripts/covers/fetch_covers.py
python3 scripts/covers/fetch_covers2.py
```
