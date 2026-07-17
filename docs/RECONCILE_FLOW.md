# Reconcile Script Flow

ASCII flowcharts showing the decision logic in `scripts/reconcile_sessions.py`.
Flows #1-#7 cover the default orphan-handling mode; Flow #8 covers `--merge-drift`.

## 1. Main Pipeline

```
 START
   |
   v
 ┌─────────────────────────┐
 │  Show DRY RUN banner     │
 │  (if --dry-run)          │
 └────────────┬─────────────┘
              v
 ┌─────────────────────────┐
 │  Scan archive            │
 │  - Count projects        │
 │  - Count sessions        │
 │  - Find orphan UUID dirs │
 └────────────┬─────────────┘
              |
        ┌─────┴─────┐
        │ Orphans?   │
        └─────┬──────┘
         no   |   yes
     ┌────────┴────────┐
     v                 v
  "Archive        ┌──────────────────┐
   is clean"      │ Categorize each   │
     |            │ orphan folder     │
     |            └────────┬─────────┘
     |                     v
     |            ┌──────────────────┐
     |            │ Compute move plan │
     |            │ (resolve targets, │
     |            │  detect dupes,    │
     |            │  extract session  │
     |            │  timestamps)      │
     |            └────────┬─────────┘
     |                     v
     |            ┌──────────────────┐
     |            │ Display:          │
     |            │  - Category table │
     |            │  - Move plan      │
     |            │  - Summary        │
     |            └────────┬─────────┘
     |                     v
     |            ┌──────────────────┐
     |            │ Per-group prompts │
     |            │ (see Flow #4)     │
     |            └────────┬─────────┘
     |                     |
     └──────────┬──────────┘
                v
       ┌────────┴──────────────┐
       │ Fix project folder     │
       │ mtimes for affected    │
       │ projects (see Flow #7) │
       └────────┬──────────────┘
                v
       ┌────────┴─────────┐
       │ Archive changed?  │
       │ (any files moved, │
       │  replaced, or     │
       │  deleted)          │
       └────────┬──────────┘
          no    |    yes
     ┌──────────┴──────────┐
     v                     v
  "Reindex:           ┌────────────────┐
   skipped            │ Rebuild project │
   (no changes)"      │ + master index  │
     |                │ (show deltas)   │
     |                └───────┬────────┘
     └──────────┬─────────────┘
                v
         ┌───────────────┐
         │ Print report   │
         └───────────────┘
```

> **`--merge-drift` addendum:** in drift mode a drift stage runs between the
> per-group prompts and the mtime-fix step; its `drift_changed` result also feeds
> the archive-changed check that gates reindexing. See
> [8. Drift Mode](#8-drift-mode---merge-drift).

## 2. Orphan Folder Categorization

```
  Orphan UUID folder
         |
         v
  ┌──────────────┐
  │ Has .jsonl?   │
  └──────┬───────┘
    yes  |   no
   ┌─────┴──────┐
   v            v
 CAT A      ┌──────────────┐
 (JSONL)    │ Has .html?    │
   |        └──────┬───────┘
   |          yes  |   no
   |         ┌─────┴──────┐
   |         v            v
   |       CAT B     ┌──────────┐
   |       (HTML)    │ Empty?    │
   |         |       └────┬─────┘
   |         |       yes  |  no
   |         |      ┌─────┴─────┐
   |         |      v           v
   |         |    CAT C       CAT D
   |         |    (Empty)     (Other)
   v         v      v           v
 ┌─────┐ ┌─────┐ ┌──────┐ ┌────────────┐
 │Move │ │Move │ │Shown │ │Shown in    │
 │plan │ │plan │ │in    │ │UNRECOGNIZED│
 │entry│ │entry│ │EMPTY │ │group       │
 │     │ │     │ │group │ │            │
 └─────┘ └─────┘ └──────┘ └────────────┘
```

## 3. Target Resolution + Duplicate Detection

```
  Category A/B folder
         |
    ┌────┴─────────────┐
    │ Extract cwd from  │
    │ JSONL or HTML      │
    └────┬─────────────┘
         |
    ┌────┴────┐
    │ Found?  │
    └────┬────┘
    yes  |  no
   ┌─────┴──────┐
   v            v
 Derive      Target =
 project     "_UNKNOWN"
 name           |
   |            |
   v            |
 ┌────────────┐ |
 │ Match an   │ |
 │ existing   │ |
 │ project?   │ |
 └─────┬──────┘ |
  yes  |  no    |
  ┌────┴────┐   |
  v         v   |
 Use      Mark  |
 existing "new  |
 name    project"|
  |         |   |
  └────┬────┘   |
       v        |
  target_dir =  |
  archive/      |
  project/uuid  |
       |        |
       └───┬────┘
           v
    ┌──────┴───────┐
    │ target_dir   │
    │ exists?      │
    └──────┬───────┘
      no   |   yes
    ┌──────┴───────────┐
    v                  v
  ┌──────┐    ┌────────────────────┐
  │ MOVE │    │ Compare orphan vs  │
  │ group│    │ organized copy     │
  └──────┘    └────────┬───────────┘
                       v
              ┌────────┴─────────┐
              │ Which is bigger?  │
              └────────┬─────────┘
           ┌───────────┼───────────┐
           v           v           v
        Orphan >    Equal      Organized >
           |           |           |
           v           v           v
       ┌────────┐ ┌────────┐ ┌────────┐
       │REPLACE │ │ SKIP   │ │ SKIP   │
       │group   │ │(ident.)│ │(org.   │
       │(+delta)│ │        │ │better) │
       └────────┘ └────────┘ └────────┘
                       |           |
                       v           v
                  Prompted to move
                  orphan to
                  _DELETE/duplicates/
```

## 4. Per-Group Confirmation Flow

Each group heading in the move plan IS the action question.
Declining one skips it and continues to the next.

```
  ┌───────────────────────────────────────────┐
  │ Move plan displayed with all groups        │
  │ (headings are the action questions)        │
  └─────────────────────┬─────────────────────┘
                        v
                ┌───────┴────────┐
           ┌────┤ REPLACE group  ├────┐
           │    │ non-empty?     │    │
           │    └────────────────┘    │
           │no                    yes│
           │              ┌──────────┴──────────┐
           │              │ "Replace N sessions? │
           │              │ (old copies backed   │
           │              │ up to _DELETE/        │
           │              │ replaced/)"           │
           │              └──────────┬───────────┘
           │                   ┌────┴────┐
           │                   │ yes  no │
           │                   └────┬────┘
           │                ┌──────┴──────┐
           │                v             v
           │            Process      "Skipped."
           │            replaces
           │            (backup old
           │            to _DELETE/
           │            replaced/)
           └───────┬────────┴─────────────┘
                   v
                ┌──┴─────────┐
           ┌────┤ MOVE group ├────┐
           │    │ non-empty? │    │
           │    └────────────┘    │
           │no                yes│
           │              ┌──────┴──────┐
           │              │"Move N      │
           │              │ sessions?"  │
           │              └──────┬──────┘
           │                ┌────┴────┐
           │                │ yes  no │
           │                └────┬────┘
           │             ┌──────┴──────┐
           │             v             v
           │         Process      "Skipped."
           └───────┬─────┴─────────────┘
                   v
                ┌──┴──────────────┐
           ┌────┤ UNKNOWN group   ├────┐
           │    │ non-empty?      │    │
           │    └─────────────────┘    │
           │no                     yes│
           │              ┌───────────┴──────────┐
           │              │"Move N to _UNKNOWN?" │
           │              └───────────┬──────────┘
           │                   ┌─────┴────┐
           │                   │ yes   no │
           │                   └─────┬────┘
           │                ┌────────┴──────┐
           │                v               v
           │            Process        "Skipped."
           └───────┬────────┴───────────────┘
                   v
                ┌──┴──────────────────┐
           ┌────┤ DUPLICATES          ├────┐
           │    │ non-empty?          │    │
           │    └─────────────────────┘    │
           │no                         yes│
           │              ┌───────────────┴───────┐
           │              │"Move N duplicates     │
           │              │ to _DELETE?"           │
           │              └───────────────┬───────┘
           │                   ┌──────────┴────┐
           │                   │ yes        no │
           │                   └──────┬────────┘
           │                ┌─────────┴────────┐
           │                v                  v
           │         Move to _DELETE/     "Skipped."
           │         duplicates/
           └───────┬────────┴──────────────────┘
                   v
                ┌──┴──────────────────┐
           ┌────┤ EMPTY folders       ├────┐
           │    │ non-empty?          │    │
           │    └─────────────────────┘    │
           │no                         yes│
           │              ┌───────────────┴───────┐
           │              │"Move N empty folders  │
           │              │ to _DELETE?"           │
           │              └───────────────┬───────┘
           │                   ┌──────────┴────┐
           │                   │ yes        no │
           │                   └──────┬────────┘
           │                ┌─────────┴────────┐
           │                v                  v
           │         Move to _DELETE/     "Skipped."
           │         empty/
           └───────┬────────┴──────────────────┘
                   v
                ┌──┴──────────────────┐
           ┌────┤ UNRECOGNIZED        ├────┐
           │    │ non-empty?          │    │
           │    └─────────────────────┘    │
           │no                         yes│
           │              ┌───────────────┴───────┐
           │              │"Move N unrecognized   │
           │              │ folders to _DELETE?"   │
           │              └───────────────┬───────┘
           │                   ┌──────────┴────┐
           │                   │ yes        no │
           │                   └──────┬────────┘
           │                ┌─────────┴────────┐
           │                v                  v
           │         Move to _DELETE/     "Skipped."
           │         unrecognized/
           └───────┬────────┴──────────────────┘
                   v
              Continue to
              reindex step
              (only if archive changed)
```

> **`--merge-drift` addendum:** after the six orphan groups above, drift mode asks
> ONE combined confirmation -- "Apply N drift actions and drain M empty folders?"
> (the drain clause appears only when empty folders exist) -- not a per-group
> prompt. See [8. Drift Mode](#8-drift-mode---merge-drift).

## 5. Soft-Delete (_DELETE) Structure

```
  _DELETE/
  ├── duplicates/            orphan copies where organized version was kept
  ├── empty/                 empty orphan folders
  ├── unrecognized/          orphan folders with non-session files
  ├── replaced/              old organized copies overwritten by newer orphans
  ├── drift-dedupe/<wrong>/  (--merge-drift) same-size drift copies removed from the wrong project
  └── drift-empty-projects/  (--merge-drift) project folders left empty after drift moves

  Collision handling:
  ┌──────────────────────────────────────┐
  │ _DELETE/<subfolder>/<name> exists?   │
  └──────────┬───────────────────────────┘
        no   |   yes
  ┌──────────┴──────────┐
  v                     v
  Move to            Try <name>-1
  _DELETE/            Then <name>-2
  <subfolder>/        ... until free
  <name>
```

## 6. Group Assignment Summary

```
 ┌──────────────────────┬──────────────────────────────────────────────────┐
 │ Group                │ Condition + Action                               │
 ├──────────────────────┼──────────────────────────────────────────────────┤
 │ Replace N sessions?  │ Target dir exists, orphan JSONL is larger        │
 │                      │ Shows: +delta, age (from JSONL timestamp)        │
 │                      │ Old copy -> _DELETE/replaced/                    │
 │                      │ Orphan -> project dir                            │
 ├──────────────────────┼──────────────────────────────────────────────────┤
 │ Move N sessions?     │ Target dir does NOT exist                        │
 │                      │ Shows: age, (new project) tag if applicable      │
 │                      │ Orphan -> project dir                            │
 ├──────────────────────┼──────────────────────────────────────────────────┤
 │ Move N to _UNKNOWN?  │ No cwd extractable from JSONL/HTML              │
 │                      │ Shows: age                                       │
 │                      │ Orphan -> _UNKNOWN/                              │
 ├──────────────────────┼──────────────────────────────────────────────────┤
 │ Move N duplicates    │ Target dir exists, organized copy is same        │
 │ to _DELETE?          │ size or larger                                   │
 │                      │ Shows: age                                       │
 │                      │ Orphan -> _DELETE/duplicates/                    │
 ├──────────────────────┼──────────────────────────────────────────────────┤
 │ Move N empty folders │ Orphan folder contains no files                  │
 │ to _DELETE?          │ Orphan -> _DELETE/empty/                         │
 ├──────────────────────┼──────────────────────────────────────────────────┤
 │ Move N unrecognized  │ Orphan folder has files but no .jsonl/.html      │
 │ folders to _DELETE?  │ Orphan -> _DELETE/unrecognized/                  │
 └──────────────────────┴──────────────────────────────────────────────────┘

 Drift groups (only with --merge-drift; ONE combined confirmation, not per-group):

   MOVE              session cwd derives to a different project, no collision
                     -> relocated to the correct project dir
   DEDUPE_IDENTICAL  same-size copy already in the correct project
                     (size = equality proxy; contents not byte-compared)
                     -> wrong copy to _DELETE/drift-dedupe/<wrong-project>/
   CONFLICT          same UUID but differing size (treated as differing content)
                     -> both copies left in place, reported, never auto-resolved
   Drain empties     project folder emptied of sessions by drift moves
                     -> folder to _DELETE/drift-empty-projects/

 Notes:
 - Nothing is permanently deleted; all removals go to _DELETE/<subfolder>/
 - REPLACE backs up the OLD organized copy to _DELETE/replaced/
 - Ages derived from JSONL internal timestamps (falls back to file mtime)
 - --dry-run skips all actions and reindexing
 - --yes auto-confirms all prompts
 - Reindex only runs when the archive actually changed
 - Groups with zero entries are not shown and not prompted
```

## 7. Project Folder Mtime Correction

Two paths trigger project folder mtime correction:

```
 ┌───────────────────────────────────────────────────────┐
 │                 Trigger                                │
 └───────────────────────┬───────────────────────────────┘
                         |
           ┌─────────────┴─────────────┐
           v                           v
 ┌───────────────────┐       ┌───────────────────┐
 │ Normal reconcile  │       │ --fix-mtimes flag  │
 │ (after moves)     │       │ (bulk correction)  │
 └─────────┬─────────┘       └─────────┬─────────┘
           v                           v
 ┌───────────────────┐       ┌───────────────────┐
 │ Scope: AFFECTED   │       │ Scope: ALL         │
 │ projects only     │       │ projects + _UNKNOWN │
 │ (from report.     │       │                     │
 │  projects_affected)│       │ Also fixes each    │
 └─────────┬─────────┘       │ session folder     │
           |                  │ first via          │
           |                  │ fix_session_mtime()│
           |                  └─────────┬─────────┘
           └─────────────┬──────────────┘
                         v
              ┌──────────┴───────────┐
              │  fix_project_mtime() │
              │  for each project    │
              └──────────┬───────────┘
                         v
              ┌──────────────────────┐
              │ For each session     │
              │ subfolder:           │
              │  Find .jsonl file    │
              │  extract_last_       │
              │  timestamp()         │
              │  (ISO 8601 from      │
              │  JSONL content,      │
              │  NOT file mtime)     │
              │  Track max timestamp │
              └──────────┬───────────┘
                         v
                ┌────────┴────────┐
                │ max_ts > 0?     │
                └────────┬────────┘
              no  ┌──────┴──────┐  yes
                  v             v
              Return None   Set project folder
              (no valid     mtime = max_ts
              sessions)     via os.utime()
```

## 8. Drift Mode (`--merge-drift`)

Orphan handling (Flows #1-#7) moves stray UUID folders INTO projects. Drift mode
is a different problem: it re-derives each session's correct project from the
session's own JSONL `cwd` and moves sessions BETWEEN projects when the parent
folder name is wrong (e.g. produced by an older, buggy resolver). It runs after
the orphan groups and before the mtime-fix step.

```
 For each session under each non-"_" project folder:
   |
   v
 cwd present in the session JSONL?
   |
   +-- no  --> SKIP (left in place, logged with a reason)
   |
   +-- yes --> correct project = get_project_display_name(cwd)   [same encoding as Flow #3]
                 |
                 v
               already in the correct project?
                 |
                 +-- yes --> no-op
                 |
                 +-- no  --> same UUID already present in the correct project?
                               |
                               +-- no  --> MOVE  (relocate session to correct project)
                               |
                               +-- yes --> JSONL same size?
                                             |
                                             +-- yes --> DEDUPE_IDENTICAL
                                             |             wrong copy ->
                                             |             _DELETE/drift-dedupe/<wrong-project>/
                                             |
                                             +-- no  --> CONFLICT
                                                           both copies left in place,
                                                           reported, never auto-resolved

 After all sessions are classified:
   scan the WHOLE archive for non-"_" project folders now empty of session data
   (index.html and dotfiles ignored) -> drain to _DELETE/drift-empty-projects/
```

**Confirmation.** Drift mode asks ONE combined prompt -- `Apply N drift actions
and drain M empty folders?` -- not a per-group prompt. The "and drain M empty
folders" clause appears only when empty folders exist. `--yes` skips it;
`--dry-run` previews the plan plus the empty-candidate count and changes nothing.

**Idempotent.** The whole-archive rescan (not just touched folders) means a
re-run after a partial run still finishes draining any leftover empty folders.

**Nothing permanently deleted.** As everywhere else, DEDUPE and drain are
soft-deletes to `_DELETE/` subfolders; CONFLICT is never auto-resolved.
