---
sources:
  - src/onprem_genai/sizing/
  - src/onprem_genai/evalsuite/
  - src/onprem_genai/agent/
  - deploy/
---

# Mesurer la productivité et passer à l'échelle

[English](STRATEGY.md)

Ce document transforme la plateforme en processus de décision : quoi mesurer avant le déploiement, comment
conduire un pilote capable de montrer un effet réel, et comment passer d'un serveur GPU à un département, avec
les contrôles qu'exige un site d'ingénierie déconnecté. Les valeurs marquées ⏳ proviennent du benchmark Kaggle
(`kaggle/01_benchmark`) et de la calibration du dimensionnement ; rien n'est extrapolé à partir de chiffres
constructeurs.

## 1. Trois niveaux de preuve

| Niveau | Question | Instrument dans ce dépôt | Quand |
|---|---|---|---|
| **Capacité** | Une combinaison modèle / moteur / matériel sait-elle faire le travail, assez vite ? | `oge eval` (27 tâches C embarqué notées par exécution), benchmark de l'agent (28 trous de traçabilité F´, détection de fautes), benchmark de traçabilité (MAP / rappel avec IC), benchmark de service (TTFT, TPOT, débit selon la concurrence), `oge sizing` | Avant tout déploiement, puis à chaque changement de modèle ou de moteur |
| **Usage** | L'outil est-il utilisé, et tient-il son niveau de service ? | Métriques serveur (`--metrics` de llama.cpp, endpoint Prometheus de vLLM) : requêtes, jetons, attente, percentiles de latence ; appels d'outils MCP ; exécutions de l'agent et issue de leur revue | En continu, agrégé par équipe |
| **Résultat** | Change-t-il la livraison et la qualité ? | Protocole de pilote ci-dessous | Pilote, puis chaque trimestre |

Les mesures de capacité sont des *bornes supérieures de la valeur* : un modèle qui réussit 60 % des tâches de
génération de tests unitaires ne rendra pas les ingénieurs 60 % plus rapides. Seul le niveau « résultat » répond à
la question de la productivité, et il exige un protocole.

## 2. Indicateurs de productivité

Un indicateur isolé est trompeur ou contournable (lignes de code, nombre de suggestions acceptées). Le pilote suit
un ensemble équilibré, selon le cadre SPACE (Forsgren et al., 2021 : Satisfaction, Performance, Activité,
Communication, Efficacité) et des indicateurs de livraison de type DORA, adaptés au logiciel embarqué / de vol :

| Dimension | Indicateur | Source |
|---|---|---|
| Performance (qualité) | défauts trouvés en intégration ou plus tard par changement ; remarques de revue par changement ; couverture et score de mutation des tests du code modifié | outil de suivi, outil de revue, CI (gcov, mutants comme dans `oge eval`) |
| Performance (traçabilité) | part des exigences ayant un test balisé qui passe ; trous comblés par mois | graphe de connaissances (`oge knowledge gaps`) |
| Efficacité | délai du premier commit à la fusion ; délai avant première revue ; temps passé sur tests unitaires et documentation (enquête) | Git, outil de revue, enquête |
| Activité | sessions assistées par ingénieur, exécutions de l'agent, tests de l'agent acceptés | métriques de la plateforme |
| Satisfaction | enquête (utilité perçue, confiance, charge cognitive), taux de renoncement | enquête trimestrielle |
| Communication | longueur des discussions de revue, cycles de reprise | outil de revue |

Les indicateurs sont publiés **par équipe et en agrégé uniquement**, jamais par ingénieur.

## 3. Protocole de pilote

**Plan.** 8 à 12 semaines, 2 à 4 équipes volontaires, déploiement échelonné (*stepped wedge*) : toutes les équipes
commencent par 4 semaines de référence sans assistant, puis l'activent à des dates décalées. Chaque équipe est son
propre témoin, et le décalage sépare l'effet de l'outil des effets de calendrier (jalons de livraison, congés).

**Étude de tâches (au sein du pilote).** Un ensemble de tâches représentatives tirées du backlog des équipes (écrire
les tests unitaires d'une exigence, refactoriser une fonction selon le standard de codage, documenter un module,
corriger un résultat d'analyse statique), chacune réalisée une fois avec et une fois sans assistant par des
ingénieurs différents (plan croisé, ordre tiré au sort). Le temps est mesuré ; les productions sont notées **à
l'aveugle** par des relecteurs avec les mêmes critères objectifs que `oge eval` (tests passants, couverture,
mutants tués, complexité, complétude de la documentation).

**Garde-fous.** Tout incident de sécurité, toute sortie de données confidentielles du site, ou toute dégradation de
la qualité (taux de défauts, remarques de revue) au-delà d'un seuil convenu suspend le pilote.

**Personnes et droit.** L'assistant est un outil pour les ingénieurs, pas un outil de surveillance : données
agrégées uniquement, durée de conservation documentée, information RGPD des participants, et le CSE est associé
avant l'introduction, l'introduction de nouvelles technologies affectant les conditions de travail nécessitant sa
consultation.

**Décision.** Passage à la phase 2 si (a) les indicateurs de qualité ne se dégradent pas, (b) au moins un
indicateur d'efficacité s'améliore au-delà de la variation hebdomadaire de la période de référence, (c) la
satisfaction est positive et le renoncement faible, et (d) le niveau de service (TTFT, jetons/s par utilisateur) a
tenu au pic de charge du pilote. Un petit pilote donne des intervalles larges : le rapport les publie et
n'interprète pas les écarts qui y sont contenus.

## 4. Trajectoire de passage à l'échelle

| Phase | Utilisateurs | Plateforme | Condition de passage |
|---|---|---|---|
| 0 · Référence (ce dépôt) | — | CPU portable + GPU de test ; air gap vérifié en CI | benchmarks de capacité ✅ (⏳ passes modèles) |
| 1 · Pilote | 20–40 | un serveur GPU : un modèle de code + embeddings + serveur MCP de connaissances ; intégration Jenkins par MCP ; configurations IDE | décision du pilote (§3) |
| 2 · Département | 100–400 | répliques vLLM derrière une passerelle (clés d'API par équipe, quotas, routage), graphe Neo4j partagé, un serveur MCP par famille de dépôts, registre de modèles | SLO tenu au pic mesuré ; porte d'évaluation en place |
| 3 · Multi-sites / modèles plus grands | 400+ | modèles MoE plus grands (classe DeepSeek-V4-Flash) sur GPU à grande mémoire, répliques régionales | coût par ingénieur actif dans le budget |

Le matériel de chaque phase vient de `oge sizing plan <modèle> --scenario <chat|chat_agents|full> --engineers N`,
avec des rendements calibrés sur des mesures (`--calibration`). Les hypothèses de charge sont explicites
(`src/onprem_genai/sizing/data/workloads.yaml` : 60 % de l'équipe active au pic, 20 jetons/s par flux, marge 1,25,
débits de requêtes par classe) et sont remplacées par la télémétrie du pilote dès qu'elle existe. ⏳ Les tableaux
calibrés (25 / 100 / 400 ingénieurs × scénarios × types de GPU) sont générés après le benchmark.

Pourquoi calibrer : lors du premier passage de la sonde, un modèle dense de 27 B en GPTQ 4 bits sous vLLM (mode
*eager*) décodait à 4,8 jetons/s sur 2× T4, alors qu'un MoE de 30 B avec 3,3 B de paramètres actifs (AWQ)
atteignait 98,8 jetons/s sur les mêmes GPU (`docs/results/probe/run1-2026-10-28.md`). Le moteur, le chemin de
noyaux et l'architecture changent le débit d'un ordre de grandeur ; un modèle de dimensionnement qui les ignore
fait acheter le mauvais matériel.

## 5. Gouvernance des modèles

- **Admission** : modèles à poids ouverts sous licence permissive (Apache-2.0 / MIT), téléchargés depuis le dépôt
  officiel sur une machine connectée, avec empreintes (`scripts/download_models.sh` écrit `SHA256SUMS`),
  transférés puis vérifiés sur site.
- **Porte d'évaluation** : un nouveau modèle, une quantification, une version de moteur ou un gabarit de prompt
  n'est promu que si `oge eval` et le benchmark de l'agent ne régressent pas au-delà de leurs intervalles de
  confiance, et si le benchmark de service tient le SLO. L'empreinte de la suite lie les résultats aux versions
  exactes des tâches et des prompts.
- **Épinglage et retour arrière** : images des moteurs épinglées par condensat, fichiers de modèles par empreinte,
  configuration dans Git ; la version précédente reste déployable.
- **Frontières du contexte** : les serveurs MCP de connaissances sont limités à une famille de dépôts et en héritent
  les droits d'accès ; aucun secret ni document classifié dans les sources indexées.

## 6. Sécurité sur un site déconnecté

- Aucune connexion sortante à l'exécution, vérifié par un test qui échoue sinon (sonde de sortie sur réseau Docker
  interne).
- Services liés au réseau interne ou à localhost ; clés d'API sur les serveurs LLM ; clés par équipe à la passerelle.
- Autorité bornée des agents : l'agent de génération de tests n'écrit que des fichiers de test sur une branche de
  revue ; son compte Jenkins peut lire les jobs et lancer des builds, rien d'autre ; chaque commit de l'agent porte
  une mention d'usage d'IA.
- Traçabilité : qui a utilisé quel modèle, quand, avec quels outils MCP — conservé pendant une durée définie ; le
  contenu des prompts n'est journalisé que là où la classification des données le permet.

## 7. Risques

| Risque | Parade |
|---|---|
| Code ou tests plausibles mais faux | portes fondées sur l'exécution (build, tests, mutants), CI, revue humaine obligatoire |
| Dépendance excessive, perte de compétences des juniors | assistant d'abord positionné sur tests, documentation et exploration ; formation à la revue ; suivi par enquête |
| Contamination de licence du code généré | modèles à licence permissive uniquement ; contrôle de similarité sur les gros blocs générés si nécessaire |
| Renouvellement rapide des modèles | porte d'évaluation + épinglage : une mise à jour devient un changement mesuré et routinier |
| Délais d'approvisionnement matériel | dimensionnement calibré avec marge explicite ; les modèles MoE réduisent la bande passante nécessaire par utilisateur |
