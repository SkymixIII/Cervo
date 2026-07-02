# Revue de code adversariale — Incrément 1 (backend/moteur)

> Auteur : CounterPower. Portée : `backend/` (~1900 LOC) + `scripts/untrunc-docker.sh`, confronté à `docs/reviews/master-arbitration-02.md` (5 non-négociables), `docs/architecture/03-backend-architecture.md`, `docs/spike/spike-01-untrunc.md`.
> Méthode : lecture intégrale du code (pas seulement `docs/impl/increment-01.md`), exécution réelle de `tests/test_cancel.py` et `tests/e2e.py`, **et un test de concurrence écrit pour cette revue** (2 jobs simultanés sur la même clé de cache) + **une preuve reproductible d'un bug de verrou mort** via appel direct de `cache.get_or_repair` avec une ligne `repair_locks` `in_progress` orpheline.
> Posture : le rapport Builder n'est pas pris pour argent comptant — chaque non-négociable est vérifié dans le code et, quand c'était possible à moindre coût, par exécution.

---

## Résumé exécutif

Le travail est **solide sur 4 des 5 non-négociables**, avec des preuves qui tiennent la route (j'ai reproduit `test_cancel.py`, `tests/e2e.py` 19/19, et un test de concurrence supplémentaire confirmant que 2 jobs simultanés sur la même clé de cache ne déclenchent qu'**un seul** repair réel). Aucune injection shell : tous les appels `subprocess` utilisent des listes `argv`, jamais `shell=True`.

Mais le non-négociable **(b) — verrou "repair en cours"** a un **vrai trou** que ni le rapport Builder ni `tests/e2e.py` ne couvrent : le mécanisme d'attache fonctionne pour le cas "concurrence normale", mais **si le process owner meurt sans passer par le bloc `except` Python (SIGKILL, OOM-kill, crash dur du worker `ProcessPoolExecutor`)**, le verrou reste `in_progress` **pour toujours** — aucun timeout, aucune détection de staleness, aucun nettoyage au redémarrage. J'ai reproduit ce scénario de façon déterministe (ci-dessous) : un job "attaché" à une clé dont l'owner est mort reste bloqué indéfiniment. Sur cette base locale mono-utilisateur avec des rushs de plusieurs Go et untrunc/ffmpeg gourmands en RAM (le Spike 01 parle de ~1,2 GB traité, un vrai rush 4K est 30-80 Go), un OOM-kill du worker n'est pas un cas exotique. C'est exactement le scénario "verrou mort/oublié" que la mission demandait de traquer.

Deux bugs réels supplémentaires accompagnent ce trou : `owner_job_id` vaut littéralement la chaîne `"?"` dans 100 % des cas (jamais le vrai `job_id`), et le cache de **tranche** (2ᵉ niveau, `slice.py`) n'a **aucun verrou** contrairement au cache de repair — deux requêtes simultanées sur la même tranche peuvent écrire sur le même fichier temporaire.

## Verdict

# 🟡 GO CONDITIONNEL pour démarrer le frontend, PAS pour figer le backend

Le pipeline fonctionne, est testé, et le cœur du modèle de coût/cache (BLOQ-3) est correctement implémenté pour le cas nominal. Le frontend peut démarrer **en parallèle** de la correction du BLOQ-b-1 ci-dessous, car il ne dépend pas de ce fix. Mais **BLOQ-b-1 doit être corrigé avant que l'incrément 1 soit considéré "terminé"** — sans ça, un crash worker (plausible sur gros rush) peut geler silencieusement et définitivement toute réparation ultérieure de la même clé de cache, sans qu'aucun mécanisme ne permette de s'en remettre autrement qu'une intervention manuelle en base.

---

## 1. Statut vérifié des 5 non-négociables

| # | Exigence | Statut | Preuve |
|---|----------|--------|--------|
| **a** | Écriture atomique de l'artefact | ✅ **CONFORME** | Lecture de `cache.py::get_or_repair` : `do_repair` écrit dans `work_root/.tmp/<uuid>/`, `validate_decodable` (ffprobe) puis `os.replace` (même filesystem `work_root` → atomique POSIX) vers le chemin canonique. Le cache-hit (`canonical.exists()`) est vérifié **avant** toute lecture de la table `repair_locks` — aucune fenêtre où un fichier partiel serait indexé. Confirmé par le test e2e (artefact réutilisé, jamais de corruption observée). |
| **b** | Verrou "repair en cours" par clé | 🔴 **PARTIEL — trou réel** | Le cas concurrence "normale" marche (test ci-dessous, exécuté par moi : 2 jobs simultanés → 1 seul repair réel, `repair_cache_hit` correct sur les deux). Mais **verrou mort non géré** : reproduit en isolant `get_or_repair` avec une ligne `repair_locks` `in_progress` orpheline — le job attaché boucle **indéfiniment** (`time.sleep(0.2)` en boucle sans jamais sortir), aucun timeout. Voir §2. |
| **c** | Hash de cache NON intégral, calculé 1x | ✅ **CONFORME** | `hashing.py::cache_hash` = taille + N échantillons, O(1) vis-à-vis de la taille. Appelé **uniquement** dans `media_registry.register_media` (donc à `POST /api/media`/`POST /api/references`), jamais recalculé à la création d'un job (`job_manager.run_job_worker` lit `source["cache_hash"]` déjà stocké). |
| **d** | Annulation propre via killpg | ✅ **CONFORME** | `runner.py` : `Popen(start_new_session=True)`, lecture non bloquante (`select`) pour sonder l'annulation même si l'outil est silencieux, `_kill_group` = SIGTERM puis SIGKILL du **groupe** via `os.getpgid`/`os.killpg`. Le `finally` de `run_tool` tue systématiquement le groupe si le process est encore vivant (couvre aussi les sorties par exception). `test_cancel.py` exécuté par moi : annulation en 0,58 s, enfant confirmé mort. Pas de fuite de thread : `run_tool` est synchrone dans le process worker, pas de thread additionnel créé. |
| **e** | Confinement des chemins + pas d'auth | ✅ **CONFORME** | `security.py::confine` : `Path(user_path).resolve()` (suit les symlinks) puis `relative_to(root)` (pas de comparaison de préfixe de chaîne — donc pas de bypass du style `media_root_evil/`). Testé mentalement contre : chemin absolu hors racine, `../..`, symlink pointant hors racine → tous rejetés (`ValueError` → `PathForbidden`). Aucune route/middleware d'auth dans `main.py` ou les routers : confirmé par grep, aucun `Depends` d'authentification nulle part. |

---

## 2. BLOQ-b-1 (nouveau) — Verrou "repair en cours" sans détection de staleness : deadlock permanent sur crash dur du worker

**Sévérité : BLOQUANT** (corrigible avant frontend, mais ne doit pas rester dans l'état actuel).

### Le mécanisme actuel

`cache.py::get_or_repair` :
- le propriétaire (`owner`) exécute `do_repair` dans un `try/except Exception` ; si ça lève, le `except` met `status='failed'` → un attaché en cours peut alors retenter l'acquisition (`_try_acquire` nettoie les verrous `'failed'`).
- un attaché (`attached`) boucle : `is_canceled()` → `canonical.exists()` → `_lock_status()` → si `None`/`failed`, il retente ; sinon `time.sleep(0.2)`.

Ce design suppose que **toute** sortie de l'owner passe par le `except Exception` du bloc Python. C'est faux dans trois cas réels sur ce projet :
1. **OOM-kill** du process worker par l'OS pendant `untrunc`/ffmpeg sur un gros rush (le use-case même du produit — rushs 4K de 30-80 Go, cf. Spike 01 §5).
2. **Crash dur** du `ProcessPoolExecutor` worker (segfault d'un outil natif, `BrokenProcessPool`).
3. Un simple `kill -9` du process API (redémarrage brutal, ce qui va arriver en Docker à chaque `docker restart`/OOM du conteneur).

Dans ces trois cas, la ligne `repair_locks` reste `status='in_progress'` **pour toujours** — rien ne la nettoie au redémarrage de l'app (`main.py::lifespan` appelle `init_db` qui ne fait que `CREATE TABLE IF NOT EXISTS`, aucun `UPDATE repair_locks SET status='failed' WHERE status='in_progress'` au démarrage), et aucun TTL/heartbeat n'existe sur la colonne `updated_at` (elle est écrite mais **jamais relue** pour une décision de staleness — vérifié par grep, `updated_at` n'apparaît dans aucune clause `WHERE`/comparaison).

### Preuve reproductible

J'ai isolé `cache.get_or_repair` (sans passer par HTTP/ProcessPool) : une ligne `repair_locks` `in_progress` avec un `owner_job_id` fictif est insérée manuellement (simulant un owner mort), puis un thread appelle `get_or_repair` sur la même clé avec `is_canceled=lambda: False`. Résultat, avec timeout de 5 s sur le join :

```
CONFIRMED: get_or_repair is stuck forever waiting on a dead in_progress lock (no staleness/timeout recovery)
```

Ce test **ne fait pas partie de la suite livrée** — ni `test_cancel.py` ni `tests/e2e.py` n'exercent ce chemin (le rapport Builder l'admet lui-même en §1.5 : *« logique d'attache codée »*, sans preuve testée — seule la preuve « cache-hit e2e » existe, qui est le chemin **sain**, pas le chemin de panne).

### Conséquence produit

Une fois qu'une clé de cache est dans cet état, **plus aucun repair pour ce triplet `(source_hash, method_id, reference_hash)` ne peut jamais aboutir** — chaque nouvelle tentative (nouvel onglet de tranche, nouveau job, retry utilisateur) devient un attaché qui boucle indéfiniment. Pas d'erreur visible côté utilisateur avant un moment (le job reste en `running`/`repair-attached` sans jamais échouer ni réussir), pas de mécanisme de récupération sans intervention manuelle en base (`DELETE FROM repair_locks WHERE cache_key=...`). Sur une appli qui tourne en local et qu'on relance régulièrement (Docker, dev, reboot), ce n'est pas un cas rarissime.

### Recommandation

Ajouter un TTL sur `repair_locks` : si `updated_at` est plus vieux qu'un seuil raisonnable (ex. 2× le temps max plausible d'un repair, ou plus simplement un heartbeat périodique de l'owner qui touche `updated_at` pendant le repair) **et** que le process `owner_job_id` correspondant n'est plus `running` en base `jobs`, traiter le verrou comme `failed` et le nettoyer. Option plus simple pour V1 : au démarrage de l'app (`lifespan`), tout verrou `in_progress` restant est nécessairement orphelin (aucun process n'a pu survivre à un redémarrage du conteneur `app` qui embarque le seul `ProcessPoolExecutor`) → `UPDATE repair_locks SET status='failed' WHERE status='in_progress'` au boot. Ça ne couvre pas l'OOM-kill *sans* redémarrage de l'app, donc un heartbeat/TTL reste souhaitable en complément, mais le nettoyage au boot est un fix à faible coût qui couvre déjà le cas le plus fréquent (crash + restart du conteneur).

---

## 3. Bugs réels additionnels

### MAJ-code-1 — `owner_job_id` vaut toujours la chaîne littérale `"?"`
**Sévérité : mineur (mais révélateur)**

`cache.py:137` : `role = _try_acquire(db_path, key, "?")`. Le vrai `job_id` n'est **jamais** passé — ni `get_or_repair` ni `pipeline.run_recovery` n'ont de paramètre `job_id` à faire transiter jusqu'à `_try_acquire`. Vérifié à l'exécution (test de concurrence ci-dessus) : la ligne `repair_locks` produite contient bien `'owner_job_id': '?'`.

Impact direct aujourd'hui : nul (le verrou fonctionne quand même, la colonne n'est utilisée par aucune logique). Mais c'est exactement la colonne qu'il faudrait pour implémenter la recommandation §2 (vérifier si le job owner est encore `running`) — et elle est actuellement inutilisable. À corriger en même temps que §2.

### MAJ-code-2 — Cache de tranche (`slice.py`) sans verrou, contrairement au cache de repair
**Sévérité : majeur**

`slice.py::extract_slice` : `if dst.exists(): return dst` puis écrit dans `dst.with_suffix(".partial.mp4")` — un nom de fichier **déterministe**, pas un dossier temporaire unique par job comme dans `cache.py`. Deux jobs simultanés visant exactement la même tranche (même `source_hash/method_id/reference_hash/scope/slice_kind` — ex. double-clic rapide sur le même onglet `SliceTabs`, ou un `POST /api/jobs` rejoué par le front après un timeout réseau) passent tous les deux le test `dst.exists()` (tous deux `False` au même instant), puis lancent chacun un `ffmpeg -y ... dst.partial.mp4` **sur le même chemin `.partial.mp4`** en parallèle. Deux process ffmpeg écrivant concurremment sur le même fichier (l'un avec `-y` qui tronque à l'ouverture) produisent un fichier corrompu ou incomplet pour celui qui perd la course au `os.replace` final — et comme `os.replace` est atomique mais ne vérifie *pas* que le contenu qu'il déplace est cohérent avec ce qu'un autre process a pu écrire entre-temps, le "perdant" peut écraser un `dst` déjà bon avec un fichier tronqué, ou lire un fichier partiellement écrit par l'autre process au moment de son propre passage ffmpeg → sortie invalide silencieusement servie en preview.

Ce n'est pas couvert par le non-négociable (b), qui porte explicitement sur le **repair**, pas la tranche — mais c'est la même classe de bug, sur un chemin de code moins bien protégé, et le produit encourage justement l'utilisateur à cliquer entre tranches rapidement. Le job-level dedup annoncé en `03 §4.3` (*« un job (…, scope, slice) déjà succeeded renvoie la tranche cachée »*) n'est d'ailleurs pas implémenté au niveau job non plus (voir §5) — chaque `POST /api/jobs` crée une ligne `jobs` neuve et un nouveau worker, quel que soit l'historique.

**Recommandation** : appliquer le même pattern que `cache.py` (tmp par UUID + verrou par clé de tranche), ou a minima un nom de fichier temporaire unique par job (`uuid4` au lieu de `.partial.mp4` fixe) pour éliminer la collision d'écriture — ça ne règle pas le gaspillage CPU du double calcul, mais ça élimine la corruption.

---

## 4. Autres observations (non bloquantes)

- **`tests/e2e.py` ne teste jamais réellement le chemin "attaché"** : `job1` est entièrement attendu (`_poll_job`, bloquant) avant que `job2` soit créé — donc `job2` obtient son cache-hit via `canonical.exists()` immédiat, pas via la boucle d'attache concurrente. J'ai comblé ce trou avec un test ad hoc (2 jobs vraiment simultanés) qui confirme que le chemin concurrent fonctionne pour le cas sain — mais ça aurait dû faire partie de la suite livrée, pas être découvert en review.
- **Chemin scratch codé en dur dans `tests/e2e.py`** (`E2E_SCRATCH` par défaut pointe vers `/private/tmp/.../counterpower-.../builder-18be692d521fc650/...`, un chemin de session Builder spécifique à sa propre machine/environnement). Fonctionne seulement parce que je l'ai surchargé via la variable d'env pour reproduire les tests — sinon le test échouerait sèchement (`FileNotFoundError` ou permission refusée) sur toute autre machine, y compris CI/DockerManager. À remplacer par `tempfile.mkdtemp()`.
- **Codes d'erreur `MDAT_MISSING`, `UNSUPPORTED_FORMAT`, `REFERENCE_INCOMPATIBLE`** déclarés dans `envelope.py` mais jamais utilisés nulle part dans le code (grep confirmé) — mort pour l'instant, cohérent avec le périmètre réduit de l'incrément (`/references/check` renvoie une confiance continue plutôt que `REFERENCE_INCOMPATIBLE`), mais à surveiller pour ne pas dériver du contrat `03 §6`.
- **Endpoints `03 §5` non livrés** (`/verdict`, `/logs`, `/download`, `/media/{id}/attempts`) : conforme à ce que `docs/impl/increment-01.md` annonce explicitement comme hors périmètre — pas une régression, juste un rappel que le contrat API n'est pas encore complet.
- **`_now()` dupliqué** dans `cache.py`, `media_registry.py`, `job_manager.py` — trivial, pas la peine d'abstraire pour 3 occurrences d'une ligne, mais à surveiller si un 4ᵉ module en a besoin.
- **Pas d'injection shell** : confirmé par grep exhaustif — aucun `shell=True`, `os.system`, `os.popen` ; tous les appels `subprocess.run`/`Popen` utilisent des listes `argv`. `Config.untrunc_cmd` est découpé via `shlex.split` (source = variable d'environnement contrôlée par l'opérateur, pas par une requête HTTP) : pas de surface d'injection utilisateur.
- **CORS / CSRF non discuté** : `main.py` n'ajoute aucun `CORSMiddleware` ni protection anti-CSRF. Le choix produit « V1 localhost only, aucune auth » (non-négociable e) est respecté à la lettre, mais une page web malveillante ouverte dans le même navigateur que l'utilisateur pourrait déclencher des `POST /api/jobs` ou `/api/media` vers `localhost:8000` sans que l'absence d'auth ne soit le facteur limitant (c'est le pattern d'attaque classique des apps "local only, no auth"). Pas discuté par l'archi ni par l'arbitrage Master — je le signale pour que la décision "pas d'auth" soit prise en connaissance de cause de ce risque résiduel, mais ne le classe pas bloquant vu le contexte mono-utilisateur local assumé.

---

## 5. Cohérence avec le contrat API `03`

- Enveloppe `{data, error, meta}` : conforme partout, `meta.request_id`/`timestamp` bien présents.
- `confidence` float 0..1 interne + mapping présentation (`confidence.py`) : conforme à l'arbitrage MAJ-14, bien isolé (le moteur ne lit jamais le label).
- `requires_reference` de la 1ʳᵉ méthode exposé par `/api/methods/applicable` : conforme MAJ-9, testé par e2e.
- Idempotence job-level (`03 §4.3` point 2, *"job déjà succeeded renvoie la tranche cachée"*) : **non implémentée** — chaque `POST /api/jobs` crée systématiquement une nouvelle ligne `jobs`/un nouveau worker, même pour une requête strictement identique à un job déjà `succeeded`. Le cache de fichier (`slice.py`) rend ça rapide malgré tout, mais ce n'est pas ce que documente `03`, et ça aggrave la fenêtre de course §3 (MAJ-code-2) puisque rien n'empêche deux requêtes concurrentes identiques d'être routées vers deux jobs/process distincts.
- Pas de sur-ingénierie notable : le découpage plugin/pipeline/cache/store reste proportionné à l'incrément, pas d'abstraction gratuite repérée.

---

## 6. Ce qui a été exécuté pour cette review (reproductible)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m tests.test_cancel                     # ✅ PASS
APP_UNTRUNC_CMD=../scripts/untrunc-docker.sh \
  .venv/bin/python -m tests.e2e                            # ✅ 19/19 PASS
```

Deux tests supplémentaires écrits pour cette review (non livrés dans le dépôt, résultats collés ci-dessus en §1/§2) :
1. 2 jobs HTTP réellement concurrents sur la même clé de cache (`1min`/`5min`, même source/méthode/référence) → exactement 1 repair réel, l'autre attaché correctement.
2. Appel direct de `cache.get_or_repair` avec une ligne `repair_locks` `in_progress` orpheline pré-insérée → confirme le deadlock permanent (§2).

---

## Recommandation d'exécution pour le Builder

1. **Avant de considérer l'incrément 1 terminé** : corriger BLOQ-b-1 — a minima, nettoyer les verrous `in_progress` orphelins au démarrage de l'app (`lifespan`), et faire circuler le vrai `job_id` jusqu'à `_try_acquire` (corrige MAJ-code-1 au passage, nécessaire pour toute détection de staleness plus fine ensuite).
2. **Avant l'exposition frontend des `SliceTabs`** (donc pas forcément blocant pour démarrer le frontend, mais avant de le brancher sur de vrais clics utilisateur rapides) : ajouter un verrou/nom de fichier temporaire unique sur `slice.py::extract_slice` (MAJ-code-2).
3. Remplacer le chemin scratch codé en dur de `tests/e2e.py` par `tempfile.mkdtemp()` pour que le test soit exécutable ailleurs que sur la machine du Builder.
4. Le reste (§4) est non bloquant, à traiter au fil de l'eau.

**REVIEW CODE TERMINÉE**
