# onprem-genai-embedded

[![CI](https://github.com/djihad-elhak/onprem-genai-embedded/actions/workflows/ci.yml/badge.svg)](https://github.com/djihad-elhak/onprem-genai-embedded/actions/workflows/ci.yml) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue) ![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green)

**Implémentation de référence d'une plateforme d'IA générative sur site (on-premise) pour équipes logiciel
embarqué / aéronautique — dimensionnée, mesurée et vérifiée en mode déconnecté (air gap), avec un graphe de
connaissances code + exigences + tests exposé aux assistants via MCP.**

[English](README.md) · [Architecture](docs/ARCHITECTURE.md) · [Décisions de conception](docs/DESIGN_DECISIONS.md) ·
[Agent](docs/AGENT.md) · [Suite d'évaluation](docs/EVALSUITE.md) ·
[Productivité et passage à l'échelle](docs/STRATEGY.fr.md) · [Résultats](docs/results/README.md)

Base de code cible : **NASA F´ (F Prime) v4.4.1** — framework logiciel de vol open source du JPL (embarqué sur
l'hélicoptère martien Ingenuity), Apache-2.0, ≈ 207 000 lignes de C++. Récupéré à un commit figé, jamais copié
dans le dépôt.

---

## Le voir tourner

![L'agent comble un trou de traçabilité](docs/assets/demo-agent.gif)

**L'agent comble un trou de traçabilité dans F´.** Le contexte arrive via MCP ; la réponse est ensuite contrôlée
par la politique, compilée avec `fprime-util`, exécutée 3 fois avec la suite complète, commitée sur une branche
de revue et notée sur 4 mutants. Tout est réel sauf le modèle : sa réponse est **rejouée** depuis la sortie réelle
de Qwen3-Coder-30B-A3B lors de la passe 3, la machine d'enregistrement n'ayant pas de GPU
([comment les démos sont faites](demo/README.md)).

| Boucle de réparation (erreur scriptée) | Graphe de connaissances via MCP | Suite d'évaluation |
|---|---|---|
| ![réparation](docs/assets/demo-repair.gif) | ![mcp](docs/assets/demo-mcp.gif) | ![évaluation](docs/assets/demo-eval.gif) |
| Une macro du harnais mal orthographiée fait échouer la compilation ; l'erreur et une suggestion repartent vers le modèle, qui corrige. | Ce qu'un assistant obtient du serveur MCP : une exigence, les trous d'un composant, des tests candidats, du code et la documentation. | Les 27 tâches C se valident elles-mêmes ; les deux modèles mesurés sur Kaggle, notés par exécution. |

## Ce que fait la plateforme

| Couche | Composant | État |
|---|---|---|
| **Dimensionnement** | `oge sizing` — mémoire GPU (poids + cache KV + état des couches à attention linéaire), débit (modèle roofline, trafic des experts MoE), planification de capacité par équipe ; chaque valeur constructeur est sourcée, toute valeur inconnue est refusée plutôt que devinée | ✅ calibré sur 2× T4, validé par des tests de charge |
| **Service des modèles** | Profils llama.cpp (CPU / CUDA) et vLLM en Docker Compose, clés d'API, ports liés à localhost ; générateur de charge `oge bench` (TTFT, TPOT, percentiles de débit) avec profils de trafic d'assistant de code | ✅ pile · balayages 2×T4 (3 déploiements) |
| **Connaissances** | Ingestion Tree-sitter du code, des tests unitaires, des tableaux d'exigences et des documents de conception dans un graphe typé (en mémoire ou **Neo4j**) ; recherche hybride BM25 + dense + graphe | ✅ |
| **MCP** | Serveur de connaissances (SDK MCP v2, stdio ou HTTP) : `search`, `get_symbol`, `get_callers/callees`, `get_requirement`, `trace_requirement`, `coverage_gaps`, `module_overview` | ✅ |
| **Assistants** | Configurations Continue, Aider et MCP générique pointant vers la plateforme | ✅ |
| **Air gap** | Surcouche Compose sur réseau Docker interne + test de fumée qui **échoue si une seule connexion sortante aboutit** | ✅ (CI) |
| **Évaluation des modèles** | `oge eval` — 27 tâches C embarqué écrites pour le projet (génération, génération de tests unitaires, refactorisation, documentation) notées par exécution : compilation stricte, tests cachés, ASan/UBSan, couverture gcov, test de mutation, complexité, complétude Doxygen ; la suite se valide elle-même | ✅ 2 modèles mesurés |
| **Agent** | `oge agent` — agent LangGraph qui comble les trous de traçabilité de F´ : contexte récupéré via MCP, test unitaire balisé par l'exigence, compilation et exécution, réparation à partir des erreurs du compilateur et des tests, commit sur une branche de revue ; le modèle n'écrit que du code de test, tout le reste est déterministe et contrôlé par une politique | ✅ 18/28 trous comblés par modèle (v2) |
| **CI** | Jenkins LTS avec le plugin officiel MCP Server (compte de service à privilèges minimaux, JCasC) ; l'agent déclenche le pipeline de tests unitaires F´ et lit le verdict via MCP | ✅ (CI) |

## Résultats

### Ce qui tourne sur 2× Tesla T4 (sonde, poids 4 bits)

| Modèle | Moteur | Décodage jetons/s, 1 flux | Préremplissage jetons/s | Total jetons/s, 4 flux | VRAM par GPU (Gio) | Test C |
|---|---|---|---|---|---|---|
| Qwen3-Coder-30B-A3B (MoE, 3,3 B actifs) | llama.cpp Q4_K_M | 81,9 | 1 445 | 151 | 9,9 / 9,3 | ✗ ¹ |
| Qwen3-Coder-30B-A3B | vLLM 0.32 AWQ | **101,0** | 283 | **245** | 13,4 / 13,4 ² | ✓ |
| Qwen3.6-35B-A3B (MoE, attention hybride) | llama.cpp Q4_K_M | 60,9 | 1 326 | 107 | 10,8 / 10,3 | ✓ |
| Devstral-Small-2-24B (dense) | llama.cpp Q4_K_M | 15,9 | 649 | 28 | 8,4 / 8,1 | ✓ |
| Qwen3.8-27B (dense, attention hybride) | llama.cpp Q4_K_M | 13,9 | 550 | 29 | 7,6 / 8,6 | ✓ |
| Qwen3.8-27B | vLLM 0.32 GPTQ (mode eager seulement) | 4,6 | 206 | 16 | 12,0 / 12,0 ² | ✓ |

Sur des GPU Turing limités par la bande passante, les modèles MoE à ≈ 3 B de paramètres actifs décodent 4 à 6 fois
plus vite que les modèles denses de 24–27 B. vLLM gagne en décodage et en concurrence sur le MoE, mais son
préremplissage AWQ en SM 7.5 (pas de noyaux Marlin) est 5 fois plus lent que llama.cpp — décisif pour des prompts
d'agent de 9 000 jetons. Qwen3.8 ne se charge pas dans vLLM en AWQ avec parallélisme tensoriel 2 (forme des poids
quantifiés non alignée sur le découpage) et sature la mémoire avec les CUDA graphs en GPTQ.
¹ Le modèle a utilisé `size_t` sans `#include <stddef.h>` ; ² vLLM pré-alloue 90 % de la mémoire GPU.
Source : [`docs/results/probe/run2-2026-10-28.md`](docs/results/probe/run2-2026-10-28.md).

### Recouvrement de la traçabilité exigence → test (F´)

Vérité terrain : les 481 balises `REQUIREMENT("ID")` posées par les développeurs F´ dans les tests unitaires,
reliant **151 exigences** aux tests qui les vérifient. Balises et identifiants sont masqués ; chaque méthode
classe **les 3 261 cas de test** de la base pour chaque exigence. Moyenne sur les exigences, IC 95 % bootstrap.

| Méthode | MAP | MRR | Rappel@1 | Rappel@10 |
|---|---|---|---|---|
| Graphe seul (module de l'exigence, appels) | 0,249 [0,220 ; 0,278] | 0,291 | 0,073 | 0,550 |
| BM25 sur le code (tokenisation des identifiants) | 0,488 [0,427 ; 0,548] | 0,591 | 0,297 | 0,677 |
| Dense (Qwen3-Embedding-0.6B) | 0,479 [0,428 ; 0,531] | 0,586 | 0,261 | 0,713 |
| BM25 contraint par le graphe | 0,569 [0,513 ; 0,626] | 0,665 | 0,330 | 0,781 |
| Dense contraint par le graphe | 0,573 [0,521 ; 0,619] | 0,680 | 0,303 | 0,817 |
| **Fusion BM25 + dense (RRF) contrainte par le graphe** | **0,609 [0,553 ; 0,660]** | **0,713** | **0,350** | **0,821** |
| + reclassement LLM des 10 premiers (Qwen3-Coder) | 0,584 [0,535 ; 0,633] | 0,670 | 0,297 | 0,822 |

Aucun signal ne suffit seul : le graphe sait *où* chercher (les exigences sont allouées à des composants), le
texte sait *quel* test, et les recherches lexicale et dense échouent sur des exigences différentes. Le
reclassement LLM point par point a *dégradé* la précision en tête de liste et coûte 10 appels par exigence : il
n'est pas activé par défaut. Sources : [`traceability_lexical.json`](docs/results/traceability_lexical.json),
[`bench/run2-2026-10-28`](docs/results/bench/run2-2026-10-28/README.md).

### Modèles de code sur du C embarqué (`oge eval`, 27 tâches notées par exécution)

| Modèle (Q4_K_M, llama.cpp, 2× T4) | Génération | Tests unitaires | Refactorisation | Documentation | Tâches réussies | Latence médiane |
|---|---|---|---|---|---|---|
| **Qwen3-Coder-30B-A3B** | **9 / 12** | 0 / 6 | 2 / 5 | **4 / 4** | **15 / 27** | **21 s** |
| Devstral-Small-2-24B | 5 / 12 | 1 / 6 | 2 / 5 | 2 / 4 | 10 / 27 | 85 s |

Qwen3-Coder réussit plus de tâches (7 contre 2 discordantes ; test exact de McNemar p = 0,18 — une tendance à
cette taille d'échantillon) avec une latence quatre fois plus faible. Chaque échec a été re-noté à partir des
sorties conservées ; les motifs comptent plus que les totaux : **8 programmes de test générés sur 12 échouent
sur l'implémentation correcte**, parce que le modèle calcule les valeurs attendues de tête (sommes de contrôle,
bornes de saturation) — les tests valides tuent 16 fautes injectées sur 19 ; les conventions au niveau du bit
(COBS, Hamming(7,4), code convolutif) mettent les deux modèles en échec ; les refactorisations réduisent toujours
la complexité, mais 4 sur 10 changent le comportement. Le code et les tests générés exigent des portes fondées
sur l'exécution, pas seulement une relecture.

### Agent de génération de tests sur F´ (28 trous de traçabilité)

| Modèle | Vérifiées, v1 → v2 | Première réponse compilée, v1 → v2 | Mutants tués par les tests vérifiés (v2) | Temps médian / exigence |
|---|---|---|---|---|
| Qwen3-Coder-30B-A3B | 11 → **18 / 28** | 52 % → 81 % | 42 / 64 | 43 s |
| Devstral-Small-2-24B | 8 → **18 / 28** | 15 % → 67 % | 35 / 67 | 94 s |

La v1 a échoué sur 121 tentatives ; leur classement (`failure_causes`) a montré que **54 % venaient d'une
confusion que l'agent lui-même entretenait** : appeler `doDispatch()` sur des composants passifs, encouragé par
une suggestion « vouliez-vous dire » proposant une méthode absente de F´ v4. Huit autres venaient d'un bogue du
patcheur. La v2 indique la nature du composant et l'appel de dispatch exact, corrige le bogue, conserve le bloc
qu'une réponse de réparation omet et montre le source des assertions F´ déclenchées. Sur les mêmes 28 exigences
et les mêmes modèles, les tests vérifiés passent de 11 à 18 et de 8 à 18 (test exact de McNemar p = 0,016 et
0,013) ; ces causes d'échec tombent à zéro. Restent la connaissance de l'API F´ par les modèles (valeurs d'énumérés
et chemins d'inclusion inventés) et les préconditions des composants. Une pré-revue par IA des 36 tests vérifiés
en juge 30 pertinents et 6 partiellement pertinents (à confirmer par un ingénieur sur les fiches de revue).
Source : [`bench/run3-2026-10-28`](docs/results/bench/run3-2026-10-28/README.md).

### Service sur 2× T4 (nouveaux prompts à chaque niveau de concurrence)

| Déploiement | Chat, 1 utilisateur | Chat, 4 utilisateurs | Chat, 16 utilisateurs | Étape d'agent (prompt de 9 k jetons), 4 flux | Complétion en ligne, 4 flux |
|---|---|---|---|---|---|
| Qwen3-Coder · llama.cpp (4 emplacements) | 74 jetons/s · premier jeton 2,3 s | 23 jetons/s/util. · 5,7 s | 20 jetons/s/util. · **71 s** (file d'attente) | **0,31 req/s** · 4,1 s | premier jeton 2,6 s |
| Qwen3-Coder · vLLM (TP 2) | 71 jetons/s · 2,4 s | 27 jetons/s/util. · 6,8 s | 7 jetons/s/util. · 7,0 s | 0,13 req/s · 19,1 s | **premier jeton 1,5 s** |
| Devstral · llama.cpp | 15 jetons/s · 5,0 s | 6 jetons/s/util. · 11,2 s | 6 jetons/s/util. · 226 s | 0,14 req/s · 7,5 s | premier jeton 4,4 s |

Un serveur 2× T4 sert environ quatre utilisateurs de chat simultanés à 20 jetons/s chacun. Sur Turing, vLLM est
le meilleur moteur pour le trafic interactif et llama.cpp pour les étapes d'agent à long contexte (le traitement
des prompts de vLLM n'y dispose ni de FlashAttention 2 ni des noyaux Marlin) : le choix dépend du mélange de
charge et doit être remesuré sur le GPU cible.

### Dimensionnement : calibré sur ces passes

Ajusté sur la sonde, séparément pour les modèles denses et MoE (décodage à 77 % contre 59 % de la bande passante
crête sous llama.cpp), le modèle de dimensionnement prédit le décodage à ±11 % près pour un modèle tenu à l'écart
et à 4 % près sur la passe indépendante 3. Il prédit aussi la capacité en chat d'un serveur 2× T4 llama.cpp à 7 %
près du test de charge (0,187 contre 0,174 requête/s). Tableaux par équipe de 25 à 400 ingénieurs, du L4 au H200,
avec l'hypothèse sur laquelle ils reposent : [`docs/results/sizing`](docs/results/sizing/README.md) et
[STRATÉGIE](docs/STRATEGY.fr.md).

### Audit de traçabilité de F´ (automatique, depuis le graphe)

- **288 exigences** dont le document de conception prévoit une vérification par test n'ont **aucune balise de
  test explicite** — pas forcément non testées (le balisage n'est pas systématique dans F´), mais sans preuve
  traçable ; chacune est accompagnée de tests candidats à examiner.
- **12 identifiants d'exigences cités par des tests ne sont définis nulle part** (ex. `ISF-HTH-001…007` dans les
  tests de `Svc/Health`, alors que le document de conception définit `HTH-001…007`).
- **12 identifiants sont cités par les tests d'un autre composant** (ex. `PDB-*` de `Svc/PolyDb` dans les tests
  de `Svc/PrmDb`) — probablement des copier-coller.

### Graphe de connaissances

1 250 fichiers · 206 656 lignes · 5 499 fonctions · 3 261 cas de test · 560 exigences (83 documents de
conception) · 21 681 appels résolus (y compris les conventions de génération de code F´) — construit en ≈ 3 s
sur le CPU d'un portable.

## Démarrage rapide

```bash
git clone https://github.com/djihad-elhak/onprem-genai-embedded.git && cd onprem-genai-embedded
uv sync --all-extras && scripts/fetch_fprime.sh
uv run oge knowledge ingest                  # graphe de connaissances
uv run oge knowledge trace-eval              # reproduit le tableau ci-dessus
uv run oge mcp serve                         # serveur MCP (stdio) pour l'IDE
uv run oge sizing plan qwen3.8-27b --scenario chat_agents --engineers 100

cp deploy/.env.example deploy/.env && scripts/download_models.sh
docker compose -f deploy/compose.yaml --profile cpu up -d                    # plateforme complète
docker compose -f deploy/compose.yaml -f deploy/compose.offline.yaml \
  --profile cpu --profile smoke up --abort-on-container-exit --exit-code-from smoke   # preuve air gap
```

```bash
uv run oge eval validate                     # la suite d'évaluation se vérifie elle-même
scripts/setup_fprime_ut.sh                   # build des tests unitaires F´ (googletest, outils, cache)
uv run oge agent run --scripted tests/data/scripted_agent_answers.json -r SVC-COMSTUB-003   # démo hors GPU
docker compose -f deploy/compose.ci.yaml up -d --build                        # Jenkins + plugin MCP
```

Les mesures GPU s'exécutent en notebooks batch sur Kaggle (2× Tesla T4) : `kaggle/00_probe_t4x2` et
`kaggle/01_benchmark`.

## Ingénierie

Python ≥ 3.11, `uv`, ruff, pyright, pytest (tests unitaires, tests de contrat communs aux stockages mémoire et
Neo4j, test d'intégration MCP sur HTTP réel, agent de bout en bout sur F´ réel) ; CI GitHub Actions : qualité →
intégration F´ + Neo4j + agent → test de déploiement déconnecté → Jenkins via MCP. Aucune API de modèle externe
n'est appelée à l'exécution.

## Licence

Apache-2.0. F´ © Caltech/JPL, Apache-2.0, récupéré à la construction (voir [NOTICE](NOTICE)).
