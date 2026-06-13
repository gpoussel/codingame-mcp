# Design — Outils d'écriture pour le serveur MCP CodinGame

Date : 2026-06-13

## Objectif

Doter le serveur MCP (aujourd'hui lecture seule) de capacités d'**écriture**
vers CodinGame, activables par un flag. Trois opérations :

1. **Tester du code** (test-run) — exécuter les cas de test visibles d'un
   puzzle, récupérer les résultats. Réversible, sans impact sur le score.
2. **Soumettre une solution** — soumission officielle qui valide le puzzle et
   impacte score/classement. Quasi-irréversible côté CodinGame.
3. **Sauvegarder du code** (draft) — enregistrer le code dans l'IDE du puzzle
   sans tester ni soumettre.

## Activation (flag)

Variable d'environnement booléenne `CODINGAME_ENABLE_WRITES` (vrai pour
`1`/`true`/`yes`, insensible à la casse). Si absente/fausse, les `@mcp.tool`
d'écriture **ne sont pas enregistrés** → totalement invisibles côté client MCP
(pas un tool qui renvoie « writes disabled »).

## Phase de découverte (jetable, non livrée)

CodinGame n'a pas d'API publique ; on reconstitue les endpoints d'écriture en
observant le navigateur. Script `scripts/capture_codingame.py` (hors package) :

1. Lance Chromium **visible** (`headless=False`).
2. Injecte le cookie `rememberMe` depuis `CODINGAME_REMEMBER_ME` (connexion
   automatique ; option de login manuel si préféré).
3. Listener réseau : enregistre chaque `POST .../services/...` (URL, corps de
   requête = tableau d'args positionnels, corps de réponse) dans `captured.jsonl`.
4. Ouvre `https://www.codingame.com/training/easy/jump-the-queue`.
5. Reste ouvert pendant qu'on écrit une solution triviale et qu'on déclenche
   *Save/Draft*, *Play testcases*, puis *Submit*.
6. À la fermeture, lecture de `captured.jsonl` → déduction des `(Service, func)`
   et du nombre/forme des arguments.

Produit la **connaissance** des endpoints, pas du code livré.

## Architecture livrée (pattern 4 couches inchangé)

- **`config.py`** — `ENV_ENABLE_WRITES = "CODINGAME_ENABLE_WRITES"` et
  `writes_enabled() -> bool`.
- **`endpoints.py`** — 3 nouveaux tuples nommés (noms exacts issus de la
  capture), section dédiée, arg count vérifié en commentaire.
- **`models.py`** — modèles pydantic `extra="allow"` pour les **réponses**
  (résultats par cas de test, comparaison attendu/obtenu, score). Les requêtes
  restent des listes d'args positionnels.
- **`client.py`** — méthodes typées `run_tests(pretty_id, language, code,
  test_indexes=None)`, `submit(pretty_id, language, code)`,
  `save_code(pretty_id, language, code)`. Elles ouvrent une session via
  `generateSessionFromPuzzlePrettyId` (existant) pour le `handle`, puis appellent
  l'endpoint d'écriture. Le client expose **toujours** tout ; le flag ne le
  concerne pas (client = pleine fidélité).
- **`server.py`** — tools `run_puzzle_tests`, `submit_puzzle_solution`,
  `save_puzzle_code` enregistrés **conditionnellement** (`if writes_enabled():`).
  Le shaping de présentation (résumé lisible des résultats) vit ici.

## Tests (live, philosophie « invariants structurels »)

- **`run_tests`** — testable en live : soumettre une solution correcte connue à
  `jump-the-queue`, asserter la **présence/forme** des champs (succès,
  comparaison, résultats par cas), pas les valeurs.
- **`save_code`** — testable en live (sans impact score) : asserter le succès /
  la forme de la réponse.
- **`submit`** — **pas de soumission réelle automatique**. Test marqué `skip`
  explicite par défaut, activable via une env var dédiée (ex.
  `CODINGAME_ALLOW_SUBMIT_TEST`). Assertion structurelle quand activé.
- **Flag** — test pur (sans réseau) : les tools d'écriture sont absents quand
  `CODINGAME_ENABLE_WRITES` est off, présents quand on.
- Tous les tests d'écriture sont **skippés** sans cookie, comme la suite
  existante.
