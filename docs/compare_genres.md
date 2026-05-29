# Genre model comparison: discogs400 vs discogs519

10 random tracks from the hominiscanidae archive.

| Ano  | Álbum                                        | Faixa                                              | discogs400                  | discogs519                  |
|------|----------------------------------------------|----------------------------------------------------|-----------------------------|-----------------------------|
| 2023 | Rodrigo Zin - Invasor                        | 09 - Rodrigo Zin - Camomila.mp3                    | Hip Hop---Cloud Rap         | Hip Hop---Trap              |
| 2022 | Corona Nimbus - Obsidian Dome                | 05 - Corona Nimbus - Seeds of the U...             | Rock---Alternative Rock     | Rock---Stoner Rock          |
| 2015 | Johnny Hooker - Eu Vou Fazer uma Macumba     | 01 Eu Vou Fazer uma Macumba Pra Te...              | Reggae---Ska                | Reggae---Ska                |
| 2024 | Laura Macedo - INTENSA                       | 05 - toda vez que eu...                            | Electronic---Tropical House | Latin---MPB                 |
| 2013 | eu - 1989 Disco 2                            | 04. cop.mp3                                        | Rock---Experimental         | Rock---Post-Punk            |
| 2020 | WALL - EHLO                                  | 02 Pampampam.mp3                                   | Hip Hop---Horrorcore        | Hip Hop---Gangsta           |
| 2026 | Olga Costa - Chandler                        | 02 Olga Costa - Lady Boy (Mix Robson Feoli).mp3    | Rock---Indie Rock           | Rock---Country Rock         |
| 2013 | ZAVA - ZAVA                                  | zava-zava-2013.mp3                                 | Rock---Alternative Rock     | Rock---Alternative Rock     |
| 2018 | Kovtun, Umbilichaos - Belong to Nothing      | 03 Belong to Nothing No. 2 - the Lost Paradise.mp3 | Electronic---Experimental   | Rock---Post-Metal           |
| 2024 | Fresno - Eu Nunca Fui Embora                 | 12 - Fresno, Filipe Catto - Diga Parte Final.mp3   | Rock---Alternative Rock     | Pop---Indie Pop             |

## Observations

- **Agree on parent genre**: 7/10 tracks
- **Exact match**: 2/10 (Johnny Hooker - Ska; ZAVA - Alternative Rock)
- **discogs519 more specific for BR music**: Laura Macedo → MPB instead of Tropical House
- **discogs519 captures texture better**: Kovtun → Post-Metal vs Experimental; Fresno → Indie Pop vs Alternative Rock
- **discogs400 is ~3× faster** (effnet vs MAEST pipeline)

## Performance benchmark

Measured on the hominiscanidae archive (Apple Silicon, single process).

| Métrica      | discogs400              | discogs519             | ratio    |
|--------------|-------------------------|------------------------|----------|
| Sample       | 17,007 tracks (full run)| 50 tracks              |          |
| Média        | 1.32 s/track            | 3.93 s/track           | 3.0×     |
| Mediana      | 1.20 s/track            | 3.90 s/track           | 3.3×     |
| p95          | 4.70 s/track            | 4.13 s/track           |          |
| Mín          | 0.40 s/track            | 3.78 s/track           |          |
| Máx          | 29.70 s/track           | 4.56 s/track           |          |
| Total (6961 álbuns, ~23k tracks est.) | ~8.5h | ~25h          | 3×       |

discogs400 has higher variance (long tail from large albums); discogs519 is nearly constant at ~3.9s regardless of content — the MAEST pipeline clips all audio to 30s.
