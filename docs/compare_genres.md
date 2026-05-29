# Comparação de modelos de gênero: discogs400 vs discogs519

10 faixas aleatórias do acervo hominiscanidae.

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

## Observações

- **Concordam no gênero pai**: 7/10 faixas
- **Match exato**: 2/10 (Johnny Hooker - Ska; ZAVA - Alternative Rock)
- **discogs519 mais preciso para música BR**: Laura Macedo → MPB em vez de Tropical House
- **discogs519 captura melhor a textura**: Kovtun → Post-Metal vs Experimental; Fresno → Indie Pop vs Alternative Rock
- **discogs400 é ~3× mais rápido** (pipeline effnet vs MAEST)

## Benchmark de performance

Medido no acervo hominiscanidae (Apple Silicon, processo único).

| Métrica       | discogs400                        | discogs519      | razão |
|---------------|-----------------------------------|-----------------|-------|
| Amostra       | 17.007 faixas (run completo)      | 50 faixas       |       |
| Média         | 1,32 s/faixa                      | 3,93 s/faixa    | 3,0×  |
| Mediana       | 1,20 s/faixa                      | 3,90 s/faixa    | 3,3×  |
| p95           | 4,70 s/faixa                      | 4,13 s/faixa    |       |
| Mín           | 0,40 s/faixa                      | 3,78 s/faixa    |       |
| Máx           | 29,70 s/faixa                     | 4,56 s/faixa    |       |
| Total estimado (6.961 álbuns, ~23k faixas) | ~8,5h | ~25h  | 3×    |

O discogs400 tem maior variância (cauda longa em álbuns grandes); o discogs519 é praticamente constante em ~3,9s independente do conteúdo — o pipeline MAEST recorta todo áudio em 30s.
