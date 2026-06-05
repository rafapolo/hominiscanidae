# Pendências do Acervo — Hominiscanidae

Estado atual (2026-06-05): **6931 álbuns** no player.

---

## 1. 1-faixa ainda recuperável via Bandcamp (~168 álbuns)

Álbuns resgatados do YouTube como MP3 único, mas com URL do Bandcamp no post.
Já foi feita uma rodada com `redownload_single_track.py` (105 recuperados).
Ainda há ~168 candidatos onde o match falhou (Bandcamp removeu o álbum, slug diferente, etc.).

**Como atacar:**
- Investigar manualmente os slugs mais prováveis (ex: `onorock.bandcamp.com/album/resquicios-cromaticos`)
- Adicionar suporte a `--override path:bandcamp_url` no script para forçar URL específica
- Ou aceitar como perda definitiva e converter o campo para `status=dead_link`

```bash
python3 scripts/utils/redownload_single_track.py --dry-run  # lista candidatos restantes
```

---

## 2. Slugified restantes (4 álbuns — todos intencionais)

| Artista | Título | Motivo |
|---------|--------|--------|
| Binarious | vida-morte-vida | nome artístico com hífens |
| Tá Em Shock? | Self-titled | correto: álbum sem nome |
| Thamires Tannous | Canto-correnteza | título com hífen intencional |
| Le Dégoût | Self-titled | correto: álbum sem nome |

Nenhuma ação necessária.

---

## 3. 3646 links mortos — recuperação possível

Muitos `dead_link` ainda têm o áudio no YouTube, SoundCloud ou em arquivos de terceiros.
Estratégias já usadas: `ytdlp_youtube`, `ytdlp_search`, `ytdlp_soundcloud`.

**O que falta:**
- Re-tentar `ytdlp_search` nos 3646 dead_links com termos mais refinados (artista + álbum)
- Usar Wayback Machine para links Mediafire/4shared/etc. expirados
- Bandcamp de etiquetas para álbuns não encontrados individualmente

```bash
# Reativar tentativas (editar download_all.py para incluir dead_links com ytdlp_search)
```

---

## 4. 228 álbuns bloqueados (Mega DMCA)

Status `blocked` = Mega removeu por DMCA. Não recuperável via Mega.

**Possível ação:**
- Buscar os mesmos álbuns em outras fontes (archive.org, soulseek, etc.)
- Script separado: `scripts/download/recover_blocked.py` (não existe ainda)

---

## 5. ID3 tags nos arquivos rescatados do YouTube

Álbuns resgatados via `ytdlp_youtube` têm tags genéricas ou incorretas (título = nome do vídeo do YouTube, artista vazio, etc.).

**O que fazer:**
```bash
# Re-embute os metadados corretos do homi-albums.json.gz via mutagen/eyeD3
python3 scripts/utils/fix_id3_tags.py  # NÃO EXISTE — criar
```

Isso melhora a exibição nos players de áudio e também melhora o resultado do generate-albums (que lê ID3).

---

## 6. Coberturas (folder.jpg) ausentes

Muitos álbuns em `unzips/` não têm `folder.jpg`. O player exibe placeholder.

```bash
# Verificar quantos estão sem capa:
find /Volumes/EXTRA/hominiscanidae/unzips -maxdepth 1 -mindepth 1 -type d \
  '!' -name '.*' | while read d; do [ ! -f "$d/folder.jpg" ] && echo "$d"; done | wc -l
```

**Ação:** rodar `download_cover()` para os álbuns sem capa, usando a URL do Bandcamp do post.

---

## 7. Álbuns novos no blog (manutenção periódica)

O blog continua ativo. Novos posts não estão no acervo.

```bash
python3 scripts/scrape/scrape_posts.py --sitemap   # detecta posts novos
python3 -u scripts/download/download_all.py        # baixa os novos
```

---

## 8. Deduplicação de pastas

Algumas pastas têm variantes (`lola-deli-caravan-2016` e `loladeli-caravan-2016`).
O generate-albums inclui ambas, criando duplicatas no player.

```bash
# Identificar duplicatas por artista+título+ano no JSON:
python3 -c "
import gzip, json
from collections import defaultdict
with gzip.open('data/homi-albums.json.gz') as f:
    albums = json.load(f)['albums']
key = lambda a: (a['artist'].lower(), a['title'].lower(), a['year'])
seen = defaultdict(list)
for a in albums:
    seen[key(a)].append(a['path'])
for k, paths in seen.items():
    if len(paths) > 1:
        print(k, '->', paths)
"
```

---

## Resumo de prioridade

| # | Tarefa | Impacto | Esforço |
|---|--------|---------|---------|
| 5 | Fix ID3 tags (ytdlp rescues) | alto — melhora qualidade geral | médio |
| 6 | Capas ausentes | médio — visual do player | baixo |
| 3 | Recuperar dead_links | alto — +3646 álbuns potenciais | alto |
| 8 | Deduplicação de pastas | baixo — artefato cosmético | baixo |
| 1 | 168 1-faixa via Bandcamp manual | baixo — poucos álbuns | alto |
| 4 | 228 blocked DMCA | baixo — improvável recuperação | muito alto |
