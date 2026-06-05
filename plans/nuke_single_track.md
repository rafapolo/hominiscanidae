# Cleanup Plan: Single-Track Albums & Non-Music Genres

## 1. Non-Music Genre Albums — NUKE (62 albums)

These were classified by the discogs400 ML model as non-music content.
**Action: delete from unzips/, S3, genres, regenerate index.**

```bash
python3 plans/_nuke_by_genre.py  # script to write (see below)
```

### Albums to nuke by subcategory

| Subcategory | Count |
|---|---|
| Audiobook | 21 |
| Radioplay | 15 |
| Comedy | 12 |
| Promotional | 3 |
| Poetry | 3 |
| Dialogue | 2 |
| Monolog | 1 |
| Interview | 1 |
| Speech | 1 |
| Religious | 1 |
| Education | 1 |
| Political | 1 |
| **Total** | **62** |

Keep: `Non-Music---Field Recording`, `Non-Music---Spoken Word`, `Non-Music---Sound Art`
(borderline music — Field Recording and Sound Art are legitimate genres in experimental/ambient)

### Full list

```
2002 - granola-granola-2002                                      [Radioplay]
2010 - egregora-tao-ep-2010                                      [Audiobook]
2010 - videotroma-interludio-sci-fi-ep-2010                      [Radioplay]
2011 - the-concept-reconstruction-2011                           [Comedy]
2012 - Fogo Amigo - Casa Cordas E Alguns Geradores               [Comedy]
2012 - Thrills Chase - Introducing Thrills (And The Chase)       [Audiobook]
2012 - harafh-harafh-ep-2012                                     [Audiobook]
2012 - holodomor-holodomor-2012                                  [Promotional]
2012 - porcaria-demo-2012                                        [Audiobook]
2012 - victim-sexually-reactive-child-2012                       [Dialogue]
2013 - Picnic No Front - E daí se o mundo acabou?                [Radioplay]
2013 - camarilo-camarilo-ep-2013                                 [Poetry]
2013 - chacal-ep-2013                                            [Audiobook]
2013 - pools-of-happiness-price-of-dreams-2013                   [Audiobook]
2013 - quatro-paredes-ep-1-2013                                  [Speech]
2013 - standing-point-work-consume-die-2013                      [Radioplay]
2013 - victim-lar-2013                                           [Audiobook]
2014 - Comando Circulo Avesso - História Invisível               [Radioplay]
2014 - VERMES DO LIMBO - VERMES DO LIMBO K7                      [Audiobook]
2014 - adeus-pai-2014                                            [Audiobook]
2014 - capella-death-is-privilege-2014                           [Interview]
2014 - lord-emon-respira-2014                                    [Promotional]
2014 - persiano-persiano-2014                                    [Radioplay]
2015 - cassio-figueiredo-diario-2015                             [Audiobook]
2015 - dianamita-aos-meus-inimigos-ep-2015                       [Dialogue]
2015 - dotoilage-racehouse-ep-2015                               [Radioplay]
2015 - isso-isso-ep-2015                                         [Audiobook]
2015 - krokodil-krokodil-2015                                    [Promotional]
2015 - xand-onirico-2015                                         [Radioplay]
2016 - Krokodil - PRINCÍPIOS DO AUTOCONHECIMENTO OBSTRUÍDO       [Audiobook]
2016 - Muepetmo - You Can't Make Sense Out of It                 [Audiobook]
2016 - caio-neiva-coisas-de-casa-2016                            [Education]
2016 - constantina-mexido-2016                                   [Radioplay]
2016 - dead-parrot-dead-parrot-ep-2016                           [Comedy]
2016 - mundo-movedico-culpado-2016                               [Audiobook]
2016 - tomodachi-ghost-world-2016                                [Audiobook]
2017 - Strr - Color Up                                           [Comedy]
2017 - ank-ank-ep-2017                                           [Radioplay]
2017 - dogma-3-mulambo-2017                                      [Audiobook]
2017 - gato-feio-gato-feio-2017                                  [Monolog]
2017 - linguini-cobranca-2017                                    [Comedy]
2017 - pedro-oliveira-roda-viva-ep-2017                          [Audiobook]
2017 - varandas-dismissive-tape-2017                             [Comedy]
2018 - Vaulted Ceiling Leakage - Our Lives Are One Another's     [Radioplay]
2018 - arados-arados-ii-2018                                     [Radioplay]
2018 - labirintite-labirintite-ep-2018                           [Audiobook]
2018 - miazzo-evil-noise-2-2018                                  [Political]
2018 - moon-pics-motion-2018                                     [Comedy]
2018 - objeto-amarelo-lugar-perto-em-volta-2018                  [Poetry]
2018 - oral-oral-ep-2018                                         [Radioplay]
2018 - quieto-suma-2018                                          [Audiobook]
2019 - 2019 - Aquiles Guimaraes Vida Dos Nossos                  [Religious]
2019 - Ferias Da Desgraca Episodio 01                            [Comedy]
2019 - Ferias Da Desgraca Episodio 02 Joao                       [Comedy]
2019 - Ferias Da Desgraca Episodio 02 Natal Rn                   [Comedy]
2019 - desgraca-good-times-2019                                  [Comedy]
2019 - totto-prenuncio-2019                                      [Radioplay]
2020 - Karnak - Nikodemus                                        [Radioplay]
2021 - Juliano Holanda - Por Onde As Casas Andam Em Silêncio     [Poetry]
2021 - Luca Argel - Samba de Guerrilha                           [Audiobook]
2021 - prefeitura-do-rio-prefeitura-2021                         [Audiobook]
2025 - Olivêra - Finja Que Não Me Conhece                        [Comedy]
```

---

## 2. Single-Track Albums Missing Artist (118 albums)

All have `YYYY - Title` folder names — artist not parseable from folder.
Year is always present. Title comes from the folder name (capitalized slug).

### Fix strategy

1. **Try ID3 tags directly** on the MP3 — `mutagen` to read `TPE1`/`TPE2`
2. **Fall back to posts/*.md** — post title is usually `Artist - Album`
3. **Remaining** — leave as-is (title + year is enough for the player)

```bash
python3 plans/_fix_single_artist.py  # script to write
```

### Why these have no artist in the folder name

These were downloaded as single MP3 files (not ZIPs), named by the blog post slug.
The generate-albums binary reads ID3 `TPE1` for artist — if the MP3 was shared
without tags, nothing is there.

### Full list (118 albums)

```
2009 - Bootleg Cidadao Instigado Uhuuu Ao Vivo
2010 - Supra Vida Secular Ritmada Eloquencia
2011 - Gryner Jardim Sementes Musicais Para Um
2012 - ahellofaday
2012 - Bufalo Centavo Fraturas Tinha Vontade
2012 - Jair Naves Ao Vivo Estudio Show Livre
2012 - Ricto Mafia
2012 - Santa Rosas Family Tree I Like To Smell
2012 - Umbilichaos Entrails Ii
2013 - Aldan Voce Ja Roubou Hoje
2013 - Caim Celebracoes Insurgentes
2013 - Catarro Pena De Morte
2013 - Champu Demo Ep
2013 - Coyote Indigo Horning
2013 - Droid On Elemental
2013 - Eu Voce E Manga Musica Desenhada Ep
2013 - Gustavo Jobim Leandro Theo Free
2013 - Intensos Animais Imperceptíveis.zip
2013 - Mahmed Dominio Das Aguas E Dos Ceus
2013 - Obasquiat Experimentos Com Arco Ep
2013 - Ordinaria Hit E Rodrigo Montoya
2013 - Os Trouxas Relembrando Os Trouxas Uma
2013 - Projeto Caixa Preta Mundo Cao
2013 - Ricardo Eletrico Ricardo Eletrico Ep
2013 - Ricardo Herz Trio Aqui E O Meu La
2013 - Stream.zip
2013 - Treli Feli Repifarmacopeia Split De
2013 - Victor Cardoso Contraste
2014 - Castelan Recycle
2014 - Cattleys Gardener Cinza
2014 - Chapa Mamba St
2014 - Clem Snide Ao Vivo No Mercury Lounge
2014 - Cloud Whale Sleeplessummer
2014 - Coletanea Diarios Emocionais Vl 2
2014 - Coletanea Fall From Stars
2014 - Coletanea Gran Noise Family
2014 - Diaz Nuances Bizarras Sobre Condicoes
2014 - Droid On Metadistonia
2014 - Evil Matchers Pre Release Ep
2014 - Farmacopeia Suicidio
2014 - Img1111 In Girus Imus Nocte Et
2014 - Jpe Baleia Groove
2014 - Kapitalistik Deth St
2014 - Muvi Ao Vivo Live In Acapulco
2014 - Primeiro Ato
2014 - Pumu Ainda Nao Esta Claro
2014 - Ratos De Porao Seculo Sinistro
2014 - Suíte Super Luxo
2014 - Vida De Cacador Ep
2015 - Abstrações de Você
2015 - Ceticencias Deus Sabe
2015 - Ceus De Abril Ultimo Adeus
2015 - Cidadao Instigado Fortaleza
2015 - D Selvagi Bandamono Ep
2015 - Fabio Cardelli Palavra Dos Olhos
2015 - Formafluida Fim Da Infancia Pt 1
2015 - Hugo Medeiros Henrique Vaz Marcelo
2015 - Inputoutput Eu Contenho Todos Os Meus
2015 - Les Adieux Cadaverico
2015 - Moliere Vida E Muito Curta Pro Cafe Da
2015 - Nosso Querido Figueiredo Nos Tambem Nao
2015 - Paulo Dantas Cidade Arquipelago
2015 - Plumarino Random Access Ep
2015 - Pork Suicidal 21615 Ep
2015 - Ruido De Maquina Curiosa Heranca
2015 - Sunn O Ao Vivo Em Londres
2015 - Zeca Viana Estancia
2015 - Zenicola Miazzo Spit
2016 - Chant Of Goddess Demo
2016 - Farol Cego Do Desespero Eu Fiz
2016 - Garfo Espamos
2016 - Her Os Azuis Que Escorrem Dos Predios
2016 - Luisa E Os Alquimistas Cobra Coral
2016 - Max Henrique Traco
2016 - Munoz Smokestack
2016 - O Mar Cobrindo O Sol Nao O Suficiente
2016 - Phantom Pain
2016 - Pormenores Coisas Nao Ditas
2016 - Puta B​.​O​.​C​.​A. Santa
2016 - Verjaut Geographic Misanthropy
2017 - Arayui Cerca Trova
2017 - Clan Dos Mortos Cicatriz 2
2017 - Herzegovina 5am
2017 - In Venus Ruina
2017 - Jonatas Onofre Aparicion
2017 - Muep Etmo Circumstances Dilimite Ones
2017 - Sila Crvs Aoa
2017 - That Gum U Like Black Lodge
2018 - Camaral E Bruno T 10082018
2018 - Cubus Flores Mortais Ep
2018 - Nao Nao Eu Remix
2018 - Wagner Almeida Crescimentodesistencia
2019 - Dramon Equilibrio Utopia
2019 - Echoing Nightmare When I Grew Two
2019 - Ferias Da Desgraca Episodio 01
2019 - Ferias Da Desgraca Episodio 02 Joao
2019 - Ferias Da Desgraca Episodio 02 Natal Rn
2019 - Quantico Romance Azul Na Escuridao Ep
2019 - Quartabe Licao 2 Dorival
2019 - Realidade Encoberta Nao Vivamos Mais
2019 - Sila Crvs Aoa Bardo Ep
2020 - Ana Frango Eletrico Ao Vivo No
2020 - Cadu Tenorio Isekai
2020 - Chicocorrea Sequencers 001
2020 - Combinado Ep
2020 - Ferias Da Desgraca Episodio 04 Recife Pe
2020 - Ferias Da Desgraca Episodio 05 Maceio Al
2020 - Ferias Da Desgraca Episodio 06 Sao
2020 - Giovani Cidreira Mahal Pita Manomago
2020 - Institution Ruptura Do Visivel
2020 - Luquimia Degradacao
2020 - Ninguem Balanco Oculto Vol I
2021 - Dramon Aspero
2021 - Grupo Porco Karaoke De Bebado
2021 - Rakta Deafkids Sessoes Selo Sesc
2022 - Gringos Da Semana Mais Um Passeio Pelo
2022 - Hc Entrevista Dante Augusto Rn Fala
2022 - Kalamaha No Samsara
```

---

## 3. Overlap: Non-Music singles (nuke priority)

Some of the 118 missing-artist singles are also in the Non-Music list.
Nuke step 1 first — remaining 118 will be fewer.

---

## Execution order

```bash
# Step 1 — nuke non-music albums (local + S3 + genres + index)
# Run manually album by album or write _nuke_by_genre.py

# Step 2 — fix artist on remaining single-track albums
# Try mutagen ID3 read, fall back to posts/*.md title parsing

# Step 3 — regenerate + merge genres + commit
python3 scripts/utils/merge_genres.py
cd /Users/polux/Projetos/tocador/script/generate-albums && \
  ./target/release/generate-albums /Volumes/EXTRA/hominiscanidae/unzips \
    /Users/polux/Projetos/hominiscanidae/data/homi-albums.json.gz \
    --title "Hominiscanidae" --subtitle "Música Independente Brasileira" \
    --base-url "https://cdn.tocador.cc/indie" --sitemap-url "https://tocador.cc"
```
