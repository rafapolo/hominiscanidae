# Hominiscanidae

Arquivo digital do blog **Hominiscanidae** — um dos principais repositórios de música independente brasileira, ativo por mais de uma década com **10.828 posts**. Rock, metal, folk, eletrônico, experimental, indie, samba, MPB e muito mais — totalmente grátis e organizado para explorar.

> **Este repositório é uma instância do [tocador](https://github.com/rafapolo/tocador)**. O código do player, proxy e scripts vivem lá; aqui ficam apenas os dados e a configuração de deploy desta coleção.

## Catálogo

- **6.707 álbuns**, **~5.000 artistas**, ~10.460 horas
- ~66 anos de música independente (1960–2026)
- 10.828 posts arquivados do blog; ~2.930 links mortos (permanentes)

## Como o acervo é montado

```mermaid
flowchart TD
    A([hominiscanidae.org]) -->|sitemap.xml| B[scrape_posts.py\n--sitemap]
    B --> C[(posts.json\nposts/*.md)]

    C -->|só posts novos| D[download_all.py\n64 workers]
    D --> E[/staging local\nHOMI_DEST=~/homi-staging/]

    E -->|.rar / .zip| F[unzip.py\nunar · unrar]
    E -->|.wav / .flac| W[flac_to_mp3.py\nffmpeg -q:a 2]
    F --> G[staging/unzips/\nálbuns novos]
    W --> G

    G -->|áudio| I[sync-to-bucket.js\nsó o que falta no S3]
    G --> N[generate-albums\ncatálogo parcial]
    N --> M[merge-acervo.js\nrejeita duplicatas,\nantigos intactos]
    M --> O[(data/homi-albums.json.gz)]
    O --> J[resize-cover-images.js\n200px → S3]

    G -->|BPM, tom, moods, gênero| K[analyze-tracks.py\nEssentia · no tocador]
    K --> L[(tocador/data/\nhomi-features · homi-genres)]

    O -->|GitHub Pages| P([tocador player\n+ páginas por álbum])
    L --> P
    I -->|cdn.tocador.cc| P
    J -->|cdn.tocador.cc| P
```

Os posts do blog são raspados, os arquivos baixados e descompactados, e tudo é publicado
num catálogo servido direto pelo player do tocador.

Desde outubro de 2026 o acervo não fica mais num disco externo: o áudio existe só no
bucket S3. Cada rodada baixa apenas os posts novos para uma pasta de staging (`HOMI_DEST`,
lida por `download_all.py`, `unzip.py` e `flac_to_mp3.py`), sobe áudio e capas e acrescenta
os álbuns ao catálogo publicado com o `merge-acervo.js` do tocador, que recusa duplicatas e
só grava se nenhum álbum antigo mudar. O catálogo publicado passa a ser a fonte da verdade:
não há mais como regenerá-lo inteiro a partir do áudio. O passo a passo está no `CLAUDE.md`
do tocador (*Adding albums without the music volume*). As páginas por álbum e os sitemaps
são gerados no deploy do tocador.

## Licença e direitos

Mantido para fins educacionais e de preservação cultural. Os direitos pertencem aos respectivos artistas e detentores.

Se você é titular de direitos e deseja que algum conteúdo seja removido, abra uma [issue](https://github.com/rafapolo/hominiscanidae/issues).

---

[Visite o acervo →](https://rafapolo.github.io/hominiscanidae/)
