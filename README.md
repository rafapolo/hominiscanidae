# Hominiscanidae

Arquivo digital do blog **Hominiscanidae** — um dos principais repositórios de música independente brasileira, ativo por mais de uma década com **10.609 posts**. Rock, metal, folk, eletrônico, experimental, indie, samba, MPB e muito mais — totalmente grátis e organizado para explorar.

> **Este repositório é uma instância do [tocador](https://github.com/rafapolo/tocador)**. O código do player, proxy e scripts vivem lá; aqui ficam apenas os dados e a configuração de deploy desta coleção.

## Catálogo

- **7.628 álbuns**, **~5.000 artistas**
- ~66 anos de música independente (1960–2026)
- 10.609 posts arquivados do blog; ~2.671 links mortos (permanentes)

## Como o acervo é montado

```mermaid
flowchart TD
    A([hominiscanidae.org]) -->|sitemap.xml| B[scrape_posts.py\n--sitemap]
    B --> C[(posts.json\nposts/*.md)]

    C -->|download links| D[download_all.py\n64 workers]
    D --> E[/Volumes/EXTRA/\nhominiscanidae/]

    C -->|Google Drive folder| GD[gdown --folder\nwav → ffmpeg → mp3]
    GD --> G

    E -->|.rar / .zip| F[unzip.py\nunar charset-safe]
    F --> G[unzips/]

    E -->|.wav / .flac| W[flac_to_mp3.py\nffmpeg -q:a 2]
    W --> G

    G -->|missing capa-min.jpg| H[fetch_all_missing.py\nBandcamp · Blogger CDN]
    C -->|og:image URLs| H
    H --> G

    G -->|áudio| I[sync-to-bucket.js\nS3 — 20 workers]
    G -->|capa-min.jpg| J[resize-cover-images.js\n200px → S3]

    G -->|30s center clip| K[extract-genres.py\ndiscogs400 TF model]
    K --> L[(data/genres.json)]

    L --> M[merge_genres.py]
    I --> N[generate-albums\nRust · ID3 · rayon]
    G --> N
    M --> N
    N --> O[(data/homi-albums.json.gz\n+ sitemap.xml)]

    O -->|GitHub raw URL| P([tocador player])
    I -->|CDN| P
    J -->|CDN| P
```

Os posts do blog são raspados, os arquivos baixados e descompactados, capas e gêneros
são inferidos automaticamente, e tudo é publicado num catálogo servido direto pelo
player do tocador.

## Licença e direitos

Mantido para fins educacionais e de preservação cultural. Os direitos pertencem aos respectivos artistas e detentores.

Se você é titular de direitos e deseja que algum conteúdo seja removido, abra uma [issue](https://github.com/rafapolo/hominiscanidae/issues).

---

[Visite o acervo →](https://rafapolo.github.io/hominiscanidae/)
