# Design — Outils d'écriture pour le serveur MCP CodinGame

Date : 2026-06-13

## Objectif

Doter le serveur MCP (aujourd'hui lecture seule) de capacités d'**écriture**
vers CodinGame, activables par un flag. Deux opérations :

1. **Tester du code** (test-run) — exécuter les cas de test visibles d'un
   puzzle, récupérer les résultats. Réversible, sans impact sur le score.
2. **Soumettre une solution** — soumission officielle qui valide le puzzle et
   impacte score/classement. Quasi-irréversible côté CodinGame.

> _Sauvegarde de draft abandonnée (YAGNI)_ : la découverte a montré que `play`
> et `submit` envoient le code et le **persistent déjà** comme réponse de session
> (`startTestSession` renvoie le dernier `answer.code`). Un `save_code` séparé
> serait redondant.

## Activation (flag)

Variable d'environnement booléenne `CODINGAME_ENABLE_WRITES` (vrai pour
`1`/`true`/`yes`, insensible à la casse). Si absente/fausse, les `@mcp.tool`
d'écriture **ne sont pas enregistrés** → totalement invisibles côté client MCP
(pas un tool qui renvoie « writes disabled »).

## Phase de découverte (jetable, non livrée)

CodinGame n'a pas d'API publique ; on reconstitue les endpoints en observant le
navigateur. `scripts/capture_codingame.py` lance un Chromium visible, injecte le
cookie `rememberMe` (lu depuis `scripts/.remember_me`, gitignoré, jamais exposé
à l'assistant) et logge chaque `POST .../services/...` dans `captured.jsonl`.

**Limite rencontrée :** l'anti-debug de CodinGame (`debugger;` en boucle) fige
l'IDE sous contrôle CDP. `Debugger.setSkipAllPauses` débloque le thread
principal mais pas les *web workers* (Monaco), donc l'IDE ne s'initialise pas.
La capture des 3 flux d'écriture s'est donc faite **manuellement** (DevTools du
navigateur normal, points d'arrêt désactivés via Ctrl+F8, copie des Payload /
Response). Le script reste utile pour les pages hors-IDE.

## Endpoints découverts (vérifiés en live, juin 2026)

| Op | Endpoint | Args | Réponse |
|----|----------|------|---------|
| test-run | `TestSession/play` | `[handle, {code, programmingLanguageId, multipleLanguages: {testIndex}}]` | `{output, comparison: {success}}` — **un cas par appel** |
| submit | `TestSession/submit` | `[handle, {code, programmingLanguageId}, null]` | `submissionId` (entier) |
| résultat | `Report/findReportBySubmission` | `[submissionId]` | poll : `{validatorShareable: false}` tant que le grading tourne, puis rapport complet (`score`, `validators[]`, `bestScore`, …) |

Le `handle` provient de `generateSessionFromPuzzlePrettyId` (déjà en place).
`play` n'exécute **qu'un** `testIndex` à la fois → boucler sur les indices des
`testCases` (eux-mêmes lus dans `startTestSession`).

## Architecture livrée (pattern 4 couches inchangé)

- **`config.py`** — `ENV_ENABLE_WRITES = "CODINGAME_ENABLE_WRITES"` et
  `writes_enabled() -> bool`.
- **`endpoints.py`** — `TEST_SESSION_PLAY`, `TEST_SESSION_SUBMIT`,
  `REPORT_BY_SUBMISSION`, section dédiée, arg count vérifié en commentaire.
- **`models.py`** — modèles pydantic `extra="allow"` pour les **réponses** :
  `TestPlayResult` (`output`, `comparison`, + champs d'échec tolérés),
  `SubmitReport` (`score`, `validators[]`, `bestScore`, …),
  `ValidatorResult` (`name`, `success`, `difficulty`). Requêtes = listes d'args.
- **`client.py`** — méthodes typées :
  - `run_tests(pretty_id, language, code, test_indexes=None)` — ouvre une
    session, lit les `testCases`, appelle `play` par index (concurrentes via
    `asyncio.gather`), renvoie un résultat par cas.
  - `submit(pretty_id, language, code, *, poll=True)` — `submit` puis **poll**
    `findReportBySubmission` jusqu'à présence de `score` (timeout borné),
    renvoie le rapport complet.
  - Le client expose **toujours** tout ; le flag ne le concerne pas (client =
    pleine fidélité).
- **`server.py`** — tools `run_puzzle_tests` et `submit_puzzle_solution`
  enregistrés **conditionnellement** (`if writes_enabled():`). Le shaping de
  présentation (résumé lisible : X/Y réussis, score) vit ici.

## Tests (live, philosophie « invariants structurels »)

- **`run_tests`** — testable en live : soumettre une solution correcte connue à
  `jump-the-queue`, asserter la **présence/forme** des champs (`output`,
  `comparison.success`, un résultat par cas), pas les valeurs.
- **`submit`** — **pas de soumission réelle automatique**. Test marqué `skip`
  explicite par défaut, activable via une env var dédiée
  (`CODINGAME_ALLOW_SUBMIT_TEST`). Quand activé : asserte la forme du rapport
  (`score`, `validators[]` avec `success`/`name`).
- **Flag** — test pur (sans réseau) : les tools d'écriture sont absents quand
  `CODINGAME_ENABLE_WRITES` est off, présents quand on.
- **endpoints** — asserter l'arg count des nouveaux endpoints, comme la suite
  existante.
- Tous les tests réseau sont **skippés** sans cookie, comme la suite existante.
