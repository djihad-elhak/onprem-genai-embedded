# onprem-genai-embedded

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

## Ce que fait la plateforme

| Couche | Composant | État |
|---|---|---|
| **Dimensionnement** | `oge sizing` — mémoire GPU (poids + cache KV + état des couches à attention linéaire), débit (modèle roofline, trafic des experts MoE), planification de capacité par équipe ; chaque valeur constructeur est sourcée, toute valeur inconnue est refusée plutôt que devinée | ✅ calibration Kaggle (en cours) |
| **Service des modèles** | Profils llama.cpp (CPU / CUDA) et vLLM en Docker Compose, clés d'API, ports liés à localhost ; générateur de charge `oge bench` (TTFT, TPOT, percentiles de débit) avec profils de trafic d'assistant de code | ✅ pile · ⏳ mesures 2×T4 |
| **Connaissances** | Ingestion Tree-sitter du code, des tests unitaires, des tableaux d'exigences et des documents de conception dans un graphe typé (en mémoire ou **Neo4j**) ; recherche hybride BM25 + dense + graphe | ✅ |
| **MCP** | Serveur de connaissances (SDK MCP v2, stdio ou HTTP) : `search`, `get_symbol`, `get_callers/callees`, `get_requirement`, `trace_requirement`, `coverage_gaps`, `module_overview` | ✅ |
| **Assistants** | Configurations Continue, Aider et MCP générique pointant vers la plateforme | ✅ |
| **Air gap** | Surcouche Compose sur réseau Docker interne + test de fumée qui **échoue si une seule connexion sortante aboutit** | ✅ (CI) |
| **Évaluation des modèles** | `oge eval` — 27 tâches C embarqué écrites pour le projet (génération, génération de tests unitaires, refactorisation, documentation) notées par exécution : compilation stricte, tests cachés, ASan/UBSan, couverture gcov, test de mutation, complexité, complétude Doxygen ; la suite se valide elle-même | ✅ suite · ⏳ passes modèles |
| **Agent** | `oge agent` — agent LangGraph qui comble les trous de traçabilité de F´ : contexte récupéré via MCP, test unitaire balisé par l'exigence, compilation et exécution, réparation à partir des erreurs du compilateur et des tests, commit sur une branche de revue ; le modèle n'écrit que du code de test, tout le reste est déterministe et contrôlé par une politique | ✅ de bout en bout sur F´ (modèle scripté) · ⏳ passes modèles |
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
| **BM25 contraint par le graphe (hybride)** | **0,569 [0,513 ; 0,626]** | **0,665** | **0,330** | **0,781** |
| + dense (Qwen3-Embedding-0.6B), + reclassement LLM | ⏳ `kaggle/01_benchmark` | | | |

Aucun signal ne suffit seul : le graphe sait *où* chercher (les exigences sont allouées à des composants), le
texte sait *quel* test. Source : [`docs/results/traceability_lexical.json`](docs/results/traceability_lexical.json).

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
