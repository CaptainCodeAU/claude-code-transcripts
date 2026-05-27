# Reconcile Script Flow

ASCII flowcharts showing the decision logic in `scripts/reconcile_sessions.py`.

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

## 5. Soft-Delete (_DELETE) Structure

```
  _DELETE/
  ├── duplicates/      orphan copies where organized version was kept
  ├── empty/           empty orphan folders
  ├── unrecognized/    orphan folders with non-session files
  └── replaced/        old organized copies overwritten by newer orphans

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

 Notes:
 - Nothing is permanently deleted; all removals go to _DELETE/<subfolder>/
 - REPLACE backs up the OLD organized copy to _DELETE/replaced/
 - Ages derived from JSONL internal timestamps (falls back to file mtime)
 - --dry-run skips all actions and reindexing
 - --yes auto-confirms all prompts
 - Reindex only runs when the archive actually changed
 - Groups with zero entries are not shown and not prompted
```
