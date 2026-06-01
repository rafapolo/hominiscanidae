#!/usr/bin/env python3
"""
=============================================================================
extract_all.py  —  Extração completa de todas as features de áudio com Essentia
=============================================================================

O QUE ESTE SCRIPT EXTRAI (4 pipelines):

  ─── Pipeline 1: MusicExtractor (170+ descritores) ──────────────────────
    Usa o MusicExtractor do Essentia, que analisa o áudio inteiro e produz:

    LOW-LEVEL (espectro, loudness, energia):
      * average_loudness          — loudness média (adimensional, 0-1)
      * barkbands                 — 27 bandas críticas (simulam o ouvido humano)
        .mean, .var, .median, .min, .max, .stdev
        .dmean, .dvar, .dmean2, .dvar2  — derivadas 1ª e 2ª no tempo
        .crest, .flatness_db, .kurtosis, .skewness, .spread
      * erbbands                  — 40 bandas ERB (equivalent rectangular bandwidth)
        (mesmas estatísticas que barkbands)
      * melbands                  — 40 bandas Mel
        (mesmas estatísticas)
      * melbands128               — 128 bandas Mel (alta resolução)
        (mesmas estatísticas, arrays grandes — salvos como placeholder)
      * mfcc                      — 13 MFCCs (Mel-frequency cepstral coefficients)
        .mean, .cov, .icov        — médias + matrizes covariância/inversa
      * gfcc                      — 13 GFCCs (Gammatone cepstral coefficients)
        .mean, .cov, .icov
      * spectral_centroid         — "centro de massa" do espectro (Hz)
      * spectral_complexity       — picos espectrais por frame
      * spectral_contrast_coeffs  — 6 coeficientes de contraste espectral
      * spectral_contrast_valleys — 6 vales de contraste espectral
      * spectral_decrease         — declínio espectral (inclinação)
      * spectral_energy           — energia espectral total
      * spectral_energyband_low/middle_low/middle_high/high — energia em 4 bandas
      * spectral_entropy          — entropia do espectro (desordem)
      * spectral_flux             — variação espectral entre frames
      * spectral_kurtosis         — curtose espectral
      * spectral_rms              — RMS (root mean square)
      * spectral_rolloff          — frequência abaixo da qual está X% da energia
      * spectral_skewness         — assimetria espectral
      * spectral_spread           — espalhamento espectral (variância)
      * spectral_strongpeak       — pico mais forte do espectro
      * zerocrossingrate          — taxa de cruzamentos por zero
      * hfc                       — high frequency content
      * dissonance                — dissonância perceptual
      * dynamic_complexity        — complexidade dinâmica
      * pitch_salience            — saliência de pitch (0-1)
      * silence_rate_20dB/30dB/60dB — taxa de silêncio em diferentes thresholds
      * loudness_ebu128           — loudness EBU R128 (integrated, momentary, short_term)
      * loudness_ebu128.loudness_range — faixa dinâmica (LU)

    RHYTHM (ritmo, BPM, beats):
      * bpm                       — batidas por minuto
      * bpm_histogram             — histograma de BPM (250 bins)
      * bpm_histogram_first_peak_bpm / _second_peak_bpm  — picos do histograma
      * bpm_histogram_first_peak_weight / _second_peak_weight
      * beats_count               — número total de beats detectados
      * beats_position            — posição temporal de cada beat (array)
      * beats_loudness            — loudness de cada beat
      * beats_loudness_band_ratio — razão de loudness por banda de frequência (6 bandas)
      * onset_rate                — taxa de onset (ataques) por segundo
      * danceability              — dançabilidade (combina BPM, variabilidade, etc.)

    TONAL (harmonia, tonalidade, acordes):
      * key_krumhansl             — key via perfil Krumhansl (ex: "F", "major")
      * key_temperley             — key via perfil Temperley
      * key_edma                  — key via EDMA (enhanced direct method)
      * chords_key / chords_scale — tonalidade geral detectada
      * chords_changes_rate       — taxa de mudança de acordes
      * chords_number_rate        — taxa de acordes "estranhos" (não-diatônicos)
      * chords_strength           — força da detecção de acordes
      * chords_histogram          — histograma de 24 acordes (12 maiores + 12 menores)
      * hpcp                      — harmonic pitch class profile (36 bins)
        .mean, .var, .median, .min, .max, .stdev
        .dmean, .dvar, .dmean2, .dvar2
        .crest, .entropy
      * thpcp                     — tuned HPCP (afinado)
      * tuning_frequency          — frequência de afinação detectada (Hz)
      * tuning_diatonic_strength  — força da afinação diatônica
      * tuning_equal_tempered_deviation — desvio do temperamento igual
      * tuning_nontempered_energy_ratio  — razão de energia não-temperada

    METADATA (tags ID3):
      * metadata.tags.artist, .album, .title, .date, .tracknumber, etc.
      * metadata.audio_properties.codec, bit_rate, sample_rate, length
      * metadata.audio_properties.md5_encoded, replay_gain, lossless

  ─── Pipeline 2: Embeddings Discogs-EffNet ──────────────────────────────
    Carrega o áudio em mono 16kHz e passa pelo modelo Discogs-EffNet.
    Produz um embedding de 1280 dimensões por frame (sumarizado como vetor).
    Útil para:
      * Busca por similaridade (cosine distance entre embeddings)
      * Alimentar classificadores customizados
      * Agrupamento (clustering) de faixas

  ─── Pipeline 3: 12 Classificadores TensorFlow ──────────────────────────
    Cada classificador pega o embedding do EffNet e aplica uma camada
    fully-connected treinada em datasets específicos:

    * genre_discogs400        → 400 gêneros/estilos do Discogs
    * mtg_jamendo_moodtheme   → moods/themes do MTG Jamendo
    * mtg_jamendo_instrument  → instrumentos do MTG Jamendo
    * voice_instrumental      → classificação voz vs instrumental
    * danceability            → dançabilidade (0-1)
    * tonal_atonal            → tonal vs atonal
    * mood_acoustic           → acústico vs não-acústico
    * mood_aggressive         → agressivo vs não-agressivo
    * mood_electronic         → eletrônico vs não-eletrônico
    * mood_happy              → feliz vs não-feliz
    * mood_sad                → triste vs não-triste
    * mood_relaxed            → relaxado vs não-relaxado
    * mood_party              → festa vs não-festa
    * arousal_valence_deam    → arousal (excitação) + valence (valência emocional)
                              no dataset DEAM (2 valores: 0-9 cada)

  ─── Pipeline 4: classifiers extras (não incluídos aqui) ────────────────
    O Essentia tem dezenas de modelos pré-treinados adicionais em:
      https://essentia.upf.edu/models/
    Incluindo: gênero Dortmund, gênero Discogs519, instrumentação, era,
    emoção, etc. Esses estão implementados separadamente em:
      scripts/extract-genres.py

=============================================================================
USO:
  python3 scripts/extract_all.py <arquivo.mp3> [output.json]

  Se output não for especificado, salva como extract_all.json

DEPENDÊNCIAS:
  pip3 install essentia-tensorflow numpy

MODELOS:
  Os modelos TensorFlow (.pb) são baixados automaticamente pelo Essentia
  para ~/.essentia/models/ na primeira execução.
  ~120 MB no total.

=============================================================================
"""

import json
import os
import sys

import numpy as np

import essentia.standard as es
from essentia import Pool

# ── Caminho dos modelos TensorFlow baixados pelo Essentia ────────────────
# O Essentia faz o download automático para este diretório.
# Modelos disponíveis: https://essentia.upf.edu/models/
MODELS = os.path.expanduser("~/.essentia/models")

# ── Argumentos da linha de comando ───────────────────────────────────────
# Primeiro argumento: caminho do arquivo MP3
# Segundo argumento (opcional): caminho do JSON de saída
MP3 = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "extract_all.json"


def convert(v):
    """
    Converte tipos numpy/tensor para tipos JSON serializáveis.

    Regras:
    - Arrays 1D com até 50 elementos → lista de floats
    - Arrays maiores → string "<array shape=(X, Y)>" para não poluir o JSON
    - Matrizes 2D (cov, icov) → placeholder
    - Floats numpy → Python float arredondado para 6 casas
    - Inteiros numpy → Python int
    - Bytes → string UTF-8
    - Listas de strings → mantidas como estão
    - Listas numéricas com até 50 elementos → lista de floats
    - Listas maiores → placeholder com tamanho
    """
    if isinstance(v, np.ndarray):
        if v.ndim == 1 and v.shape[0] <= 50:
            return [round(float(x), 6) for x in v]
        return f"<array shape={v.shape}>"
    if isinstance(v, (np.floating, float)):
        return round(float(v), 6)
    if isinstance(v, (np.integer, int)):
        return int(v)
    if isinstance(v, str):
        return v
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, list):
        if not v:
            return v
        if isinstance(v[0], str):
            return v
        if len(v) <= 50:
            try:
                return [round(float(x), 6) for x in v]
            except Exception:
                return v
        return f"<list len={len(v)}>"
    return str(v)


result = {}

# ══════════════════════════════════════════════════════════════════════════
# PIPELINE 1: MusicExtractor — 170+ descritores de baixo nível,
#             rítmicos e tonais
# ══════════════════════════════════════════════════════════════════════════
#
# O MusicExtractor é o extrator completo do Essentia.
# Ele:
#   1. Carrega o áudio (estéreo, sample rate original)
#   2. Aplica janelamento (frame size = 2048, hop = 1024)
#   3. Extrai TODOS os descritores de uma vez
#   4. Retorna um Pool com centenas de chaves
#
# Algoritmos usados internamente:
#   - FFT espectral (frame por frame)
#   - Bark scale (27 bandas críticas) — simula a cóclea humana
#   - ERB scale (40 bandas) — mais precisa que Bark
#   - Mel scale — padrão em áudio-ML
#   - Detecção de pitch via YIN
#   - Detecção de beats via beat tracking algorithm (Böck et al.)
#   - Key detection via Krumhansl, Temperley, EDMA
#   - Chord detection via HPCP + HMM
#   - Loudness EBU R128 (ITU-R BS.1770)
# ══════════════════════════════════════════════════════════════════════════
print("[1/4] MusicExtractor (170 descriptors)...")
try:
    extractor = es.MusicExtractor()
    features, _ = extractor(MP3)
    for d in sorted(features.descriptorNames()):
        try:
            result[d] = convert(features[d])
        except Exception:
            pass
except Exception as e:
    result["_error_MusicExtractor"] = str(e)

# ══════════════════════════════════════════════════════════════════════════
# PIPELINE 2: Carregamento do áudio em mono 16 kHz
# ══════════════════════════════════════════════════════════════════════════
#
# Os modelos TensorFlow do Essentia (Discogs-EffNet, MusiCNN, MAEST)
# exigem áudio mono com sample rate de 16000 Hz.
#
# O MonoLoader aplica:
#   - Downmix estéreo → mono
#   - Resampling para 16000 Hz (qualidade 4 = Sinc interpolation)
# ══════════════════════════════════════════════════════════════════════════
print("[2/4] Loading audio...")
loader = es.MonoLoader(filename=MP3, sampleRate=16000, resampleQuality=4)
audio = loader()
# audio.shape = (N,) onde N = duração_segundos * 16000

# ══════════════════════════════════════════════════════════════════════════
# PIPELINE 3: Embeddings Discogs-EffNet
# ══════════════════════════════════════════════════════════════════════════
#
# Discogs-EffNet é uma EfficientNet-B0 treinada no dataset Discogs
# (12 milhões de capas de discos) para reconhecimento de gênero musical.
#
# A rede foi adaptada para áudio: ela opera em espectrogramas Mel
# extraídos do áudio de entrada. A saída "PartitionedCall:1" é o
# embedding de 1280 dimensões (antes da classificação final).
#
# Esse embedding pode ser usado para:
#   - Similaridade entre faixas (distância cosseno)
#   - Alimentar classificadores customizados
#   - Indexação em vector database
#
# Shape da saída: (time_frames, 1280)
# O número de time_frames depende da duração do áudio.
# ══════════════════════════════════════════════════════════════════════════
print("[3/4] TF embeddings...")

effnet_pb = os.path.join(MODELS, "discogs-effnet-bs64-1.pb")
if os.path.isfile(effnet_pb) and os.path.getsize(effnet_pb) > 1000:
    try:
        effnet = es.TensorflowPredictEffnetDiscogs(
            graphFilename=effnet_pb,
            output="PartitionedCall:1"  # camada de embedding (1280-d)
        )
        embeddings = effnet(audio)
        result["embedding.discogs_effnet"] = (
            convert(embeddings[:3].flatten())
            + f" <full shape={embeddings.shape}>"
        )
    except Exception as e:
        result["_error_embedding_discogs_effnet"] = str(e)

# ══════════════════════════════════════════════════════════════════════════
# PIPELINE 4: 14 Classificadores TensorFlow
# ══════════════════════════════════════════════════════════════════════════
#
# Cada classificador é uma "cabeça" de classificação treinada em cima
# do embedding do Discogs-EffNet. São redes fully-connected finas
# (1-2 camadas) que mapeiam embedding → classes.
#
# A função classify() abaixo:
#   1. Carrega o modelo .pb + metadados .json
#   2. Aplica TensorflowPredict2D (classificação)
#   3. Faz média temporal das predições
#   4. Retorna top-K classes com scores
#
# Modelos disponíveis oficialmente (essentia.upf.edu/models/):
#
#   GÊNERO:
#     genre_discogs400          — 400 estilos/gêneros do Discogs
#     genre_dortmund            — 9 gêneros (Dortmund)
#     genre_discogs519          — 519 gêneros finos do Discogs
#
#   MOOD/TEMA:
#     mtg_jamendo_moodtheme     — 56 moods/temas (MTG Jamendo)
#     mtg_jamendo_instrument    — 41 instrumentos (MTG Jamendo)
#
#   BINÁRIOS:
#     voice_instrumental        — voz vs instrumental
#     danceability              — dançabilidade (0 = baixa, 1 = alta)
#     tonal_atonal              — tonal vs atonal
#     mood_acoustic             — acústico vs não
#     mood_aggressive           — agressivo vs não
#     mood_electronic           — eletrônico vs não
#     mood_happy                — feliz vs não
#     mood_sad                  — triste vs não
#     mood_relaxed              — relaxado vs não
#     mood_party                — festa vs não
#
#   EMOCIONAL 2D:
#     arousal_valence_deam      — arousal (excitação 0-9) + valence (valência 0-9)
#
# ══════════════════════════════════════════════════════════════════════════
print("[4/4] TF classifiers...")


def classify(pb_name, model_key, metadata_key, threshold=0.1, top_k=10):
    """
    Executa um classificador TensorFlow pré-treinado do Essentia.

    Parâmetros:
      pb_name       — nome do arquivo .pb em ~/.essentia/models/
      model_key     — chave no JSON de saída (ex: "classifier.genre_discogs400")
      metadata_key  — nome do dataset (usado para log apenas)
      threshold     — score mínimo para incluir no resultado
      top_k         — número de classes no top-K

    Fluxo:
      1. Carrega metadados do .json (nomes das classes, nomes dos nós)
      2. Carrega o grafo TF com TensorflowPredict2D
      3. Aplica no embedding já extraído
      4. Faz média temporal → scores por classe
      5. Filtra por threshold e ordena
      6. Salva top classes + todas as classes acima do threshold

    Formatos de saída no JSON:
      classifier.<modelo>.top   — dict {classe: score} das top-K
      classifier.<modelo>.all   — dict completo ou lista parcial
      classifier.<modelo>.shape — (time_frames, n_classes)
    """
    pb = os.path.join(MODELS, pb_name)
    json_path = os.path.join(MODELS, pb_name.replace(".pb", ".json"))
    if not os.path.isfile(pb) or os.path.getsize(pb) < 1000:
        return
    try:
        # Carrega metadados do modelo (nomes das classes + nós TF)
        classes = []
        inp_name = "model/Placeholder"
        out_name = "model/Sigmoid"
        if os.path.isfile(json_path):
            with open(json_path) as f:
                meta = json.load(f)
            classes = meta.get("classes", []) or meta.get("labels", [])
            if isinstance(classes, dict):
                classes = list(classes.values())
            schema = meta.get("schema", {})
            inputs = schema.get("inputs", [])
            outputs = schema.get("outputs", [])
            if inputs:
                inp_name = inputs[0]["name"]
            if outputs:
                out_name = outputs[0]["name"]

        model = es.TensorflowPredict2D(
            graphFilename=pb,
            input=inp_name,
            output=out_name
        )
        preds = model(embeddings)  # (time_frames, n_classes)

        # Média temporal: cada classe vira um score único
        avg = np.mean(preds, axis=0)

        if model_key not in result:
            result[model_key] = {}

        # Top-K classes
        top_idx = np.argsort(avg)[::-1][:top_k]
        top = {}
        for i in top_idx:
            score = round(float(avg[i]), 4)
            if score >= threshold:
                name = classes[i] if i < len(classes) else f"class_{i}"
                top[name] = score

        top_sorted = dict(sorted(top.items(), key=lambda x: -x[1]))
        result[model_key]["top"] = top_sorted

        # Todas as classes acima do threshold
        if classes:
            all_scores = {}
            for i, s in enumerate(avg):
                score = round(float(s), 4)
                if score >= threshold:
                    name = classes[i] if i < len(classes) else f"class_{i}"
                    all_scores[name] = score
            result[model_key]["all"] = (
                dict(sorted(all_scores.items(), key=lambda x: -x[1]))
                if all_scores else []
            )
        else:
            result[model_key]["all"] = [round(float(x), 4) for x in avg[:10]]

        result[model_key]["shape"] = list(preds.shape)
        result[model_key]["time_frames"] = preds.shape[0]

    except Exception as e:
        result[f"_error_{model_key}"] = str(e)


# ── Classificador de gênero (Discogs, 400 classes) ───────────────────────
# Dataset: Discogs (12M+ registros)
# Classes: 400 estilos organizados em 17 supergêneros
#   Ex: "Electronic---House", "Rock---Punk", "Latin---MPB"
# Threshold baixo (0.01) porque o modelo tende a distribuir o score
# entre vários gêneros similares.
classify(
    "genre_discogs400-discogs-effnet-1.pb",
    "classifier.genre_discogs400",
    "genre_discogs400",
    threshold=0.01,
)

# ── Classificador de mood/tema (MTG Jamendo, 56 classes) ─────────────────
# Dataset: MTG Jamendo (18k faixas licenciadas)
# Classes: 56 moods/temas
#   Ex: "happy", "sad", "romantic", "energetic", "calm", "dark",
#       "dreamy", "suspense", "hopeful", etc.
classify(
    "mtg_jamendo_moodtheme-discogs-effnet-1.pb",
    "classifier.mood_theme",
    "mtg_jamendo_moodtheme",
    threshold=0.05,
)

# ── Classificador de instrumentos (MTG Jamendo, 41 classes) ──────────────
# Dataset: MTG Jamendo
# Classes: 41 instrumentos/características
#   Ex: "voice", "guitar", "drums", "piano", "bass", "strings",
#       "electronic", "synthesizer", "wind", "percussion", etc.
classify(
    "mtg_jamendo_instrument-discogs-effnet-1.pb",
    "classifier.instrument",
    "mtg_jamendo_instrument",
    threshold=0.05,
)

# ── Classificador voz vs instrumental ────────────────────────────────────
# Classes: "voice", "instrumental"
# Score alto em "voice" = faixa cantada
# Score alto em "instrumental" = faixa instrumental
classify(
    "voice_instrumental-discogs-effnet-1.pb",
    "classifier.voice_instrumental",
    "voice_instrumental",
    threshold=0.01,
)

# ── Classificador de dançabilidade ───────────────────────────────────────
# Classes: "danceable", "not_danceable"
# Score em "danceable" correlaciona com BPM alto, ritmo regular,
# e batida marcada.
classify(
    "danceability-discogs-effnet-1.pb",
    "classifier.danceability",
    "danceability",
    threshold=0.01,
)

# ── Classificador tonal vs atonal ───────────────────────────────────────
# Classes: "tonal", "atonal"
# Música tonal = tem centro tonal claro (maioria pop, rock, etc.)
# Música atonal = sem centro tonal (música erudita contemporânea,
#   free jazz, noise, etc.)
classify(
    "tonal_atonal-discogs-effnet-1.pb",
    "classifier.tonal_atonal",
    "tonal_atonal",
    threshold=0.01,
)

# ── 7 classificadores binários de mood ───────────────────────────────────
# Cada um é um modelo binário (0-1) treinado no MTG Jamendo.
# Threshold baixo (0.01) porque a saída é sigmoide (0-1 contínuo).
# Valores próximos de 1 = presença forte do mood.
# Valores próximos de 0 = ausência.
classify(
    "mood_acoustic-discogs-effnet-1.pb",
    "classifier.mood_acoustic",
    "mood_acoustic",
    threshold=0.01,
)
classify(
    "mood_aggressive-discogs-effnet-1.pb",
    "classifier.mood_aggressive",
    "mood_aggressive",
    threshold=0.01,
)
classify(
    "mood_electronic-discogs-effnet-1.pb",
    "classifier.mood_electronic",
    "mood_electronic",
    threshold=0.01,
)
classify(
    "mood_happy-discogs-effnet-1.pb",
    "classifier.mood_happy",
    "mood_happy",
    threshold=0.01,
)
classify(
    "mood_sad-discogs-effnet-1.pb",
    "classifier.mood_sad",
    "mood_sad",
    threshold=0.01,
)
classify(
    "mood_relaxed-discogs-effnet-1.pb",
    "classifier.mood_relaxed",
    "mood_relaxed",
    threshold=0.01,
)
classify(
    "mood_party-discogs-effnet-1.pb",
    "classifier.mood_party",
    "mood_party",
    threshold=0.01,
)

# ── Regressor arousal/valence (DEAM) ─────────────────────────────────────
# Dataset: DEAM (Dynamics of Emotion in Audio Music, 1802 faixas)
# Saída: 2 valores contínuos
#   arousal: excitação (0 = calmo, 9 = excitado/agitado)
#   valence: valência emocional (0 = negativo/triste, 9 = positivo/feliz)
#
# Interpretação dos quadrantes:
#   high arousal + high valence  → animado, feliz, eufórico
#   high arousal + low valence   → tenso, irritado, assustador
#   low arousal + low valence    → triste, melancólico, deprimido
#   low arousal + high valence   → calmo, relaxado, sereno
pb = os.path.join(MODELS, "arousal_valence_deam-discogs-effnet-1.pb")
if os.path.isfile(pb) and os.path.getsize(pb) > 1000:
    try:
        model = es.TensorflowPredict2D(graphFilename=pb)
        preds = model(embeddings)
        avg = np.mean(preds, axis=0)
        result["classifier.arousal_valence"] = {
            "arousal": round(float(avg[0]), 4) if len(avg) > 0 else None,
            "valence": round(float(avg[1]), 4) if len(avg) > 1 else None,
        }
    except Exception as e:
        result["_error_arousal_valence"] = str(e)

# ══════════════════════════════════════════════════════════════════════════
# SALVAR RESULTADO EM JSON
# ══════════════════════════════════════════════════════════════════════════
# O JSON gerado contém centenas de chaves que podem ser usadas para:
#   - Indexação em vector database (embedding)
#   - Busca textual (gêneros, moods, instrumentos)
#   - Filtros por BPM, key, tonalidade
#   - Machine learning (features como entrada)
#   - Visualização (histogramas de acordes, perfil espectral)
with open(OUT, "w") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"\nSaved to {OUT}")

# ══════════════════════════════════════════════════════════════════════════
# SUMÁRIO LEGÍVEL
# ══════════════════════════════════════════════════════════════════════════
# Exibe um resumo organizado por grupo, mostrando os valores mais
# relevantes de cada categoria.


def show_group(prefix, label):
    items = {
        k: v for k, v in result.items()
        if k.startswith(prefix) and not k.startswith("_")
    }
    if items:
        print(f"\n── {label} ──")
        for k, v in sorted(items.items()):
            short = k[len(prefix) + 1:] if len(prefix) > 0 else k
            if isinstance(v, dict):
                if "top" in v and v["top"]:
                    print(f"  {short}: {v['top']}")
                elif "shape" in v:
                    print(f"  {short}: shape={v['shape']}")
                else:
                    print(f"  {short}: {json.dumps(v, ensure_ascii=False)[:120]}")
            elif isinstance(v, str) and v.startswith("<array"):
                print(f"  {short}: {v}")
            elif isinstance(v, list) and len(v) > 5:
                print(f"  {short}: [{v[0]}, {v[1]}, ...] (len={len(v)})")
            else:
                print(f"  {short}: {v}")


show_group("metadata", "METADATA (ID3 tags)")
show_group("tonal", "TONAL (key, chords, tuning)")
show_group("lowlevel", "LOW-LEVEL (spectral, loudness, mfcc)")
show_group("rhythm", "RHYTHM (bpm, danceability, beats)")
show_group("embedding", "EMBEDDINGS")
show_group("classifier", "CLASSIFIERS (DL models)")

errors = {k: v for k, v in result.items() if k.startswith("_error")}
if errors:
    print(f"\n⚠ ERRORS: {len(errors)}")
    for k, v in errors.items():
        print(f"  {k}: {v}")
