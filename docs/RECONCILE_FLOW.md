# Reconcile Script Flow

ASCII flowcharts showing the decision logic in `scripts/reconcile_sessions.py`.

## 1. Main Pipeline

```
 START
   |
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
     |            │  detect dupes)    │
     |            └────────┬─────────┘
     |                     v
     |            ┌──────────────────┐
     |            │ Display:          │
     |            │  - Category table │
     |            │  - Move plan      │
     |            │  - EMPTY group    │
     |            │  - UNRECOGNIZED   │
     |            │  - DRY RUN banner │
     |            └────────┬─────────┘
     |                     v
     |            ┌──────────────────┐
     |            │ Per-group prompts │
     |            │ (see Flow #4)     │
     |            └────────┬─────────┘
     |                     |
     └──────────┬──────────┘
                v
          ┌─────┴──────┐
          │ --dry-run?  │
          └─────┬──────┘
           yes  |   no
      ┌─────────┴──────────┐
      v                    v
  "Reindex:           ┌─────────────┐
   skipped            │ Rebuild all  │
   (dry run)"         │ index.html   │
      |               └──────┬──────┘
      └──────────┬───────────┘
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
 │plan │ │plan │ │in    │ │[UNRECOG-   │
 │entry│ │entry│ │[EMPTY│ │NIZED]      │
 │     │ │     │ │]group│ │group       │
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
 project     "unknown-project"
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
                  to _DELETE
```

## 4. Per-Group Confirmation Flow

Every group shown in the move plan gets its own confirmation prompt.
Declining one skips it and continues to the next.

```
  ┌───────────────────────────────────────────┐
  │ Full move plan displayed (all groups)      │
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
           │              │ up to _DELETE)"       │
           │              └──────────┬───────────┘
           │                   ┌────┴────┐
           │                   │ yes  no │
           │                   └────┬────┘
           │                ┌──────┴──────┐
           │                v             v
           │            Process      "Skipped:
           │            replaces      N not
           │            (backup old   replaced"
           │            to _DELETE)       |
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
           │         Process      "Skipped"
           │             |             |
           └───────┬─────┴─────────────┘
                   v
                ┌──┴──────────────┐
           ┌────┤ UNKNOWN group   ├────┐
           │    │ non-empty?      │    │
           │    └─────────────────┘    │
           │no                     yes│
           │              ┌───────────┴──────────┐
           │              │"Move N to            │
           │              │ unknown-project?"    │
           │              └───────────┬──────────┘
           │                   ┌─────┴────┐
           │                   │ yes   no │
           │                   └─────┬────┘
           │                ┌────────┴──────┐
           │                v               v
           │            Process        "Skipped"
           │                |               |
           └───────┬────────┴───────────────┘
                   v
                ┌──┴──────────────────┐
           ┌────┤ ALREADY ORGANIZED   ├────┐
           │    │ (duplicates)        │    │
           │    │ non-empty?          │    │
           │    └─────────────────────┘    │
           │no                         yes│
           │              ┌───────────────┴───────┐
           │              │"Move N duplicate      │
           │              │ orphans to _DELETE?"   │
           │              └───────────────┬───────┘
           │                   ┌──────────┴────┐
           │                   │ yes        no │
           │                   └──────┬────────┘
           │                ┌─────────┴────────┐
           │                v                  v
           │         Move orphans to      "Skipped:
           │         _DELETE/              left in
           │                |              place"
           │                |                  |
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
           │         Move to _DELETE/     "Skipped"
           │                |                  |
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
           │         Move to _DELETE/     "Skipped"
           │                |                  |
           └───────┬────────┴──────────────────┘
                   v
              Continue to
              reindex step
```

## 5. Soft-Delete (_DELETE) Mechanics

```
  Folder to soft-delete
         |
         v
  ┌──────────────────┐
  │ _DELETE/ dir      │
  │ exists?           │
  └──────┬───────────┘
    no   |   yes
   ┌─────┴──────┐
   v            |
 Create         |
 _DELETE/       |
   |            |
   └─────┬──────┘
         v
  ┌──────────────────┐
  │ _DELETE/<name>    │
  │ exists?           │
  └──────┬───────────┘
    no   |   yes
   ┌─────┴──────────┐
   v                v
 Move to         ┌────────────────┐
 _DELETE/<name>  │ Try <name>-1   │
   |             │ Then <name>-2  │
   |             │ Then <name>-3  │
   |             │ ... until free │
   |             └────────┬──────┘
   |                      v
   |              Move to
   |              _DELETE/<name>-N
   |                      |
   └──────────┬───────────┘
              v
         Return final
         destination path
```

## 6. Group Assignment Summary

```
 ┌──────────────────────┬──────────────────────────────────────────────┐
 │ Group                │ Condition                                    │
 ├──────────────────────┼──────────────────────────────────────────────┤
 │ [REPLACE]            │ Target dir exists, orphan JSONL is larger    │
 │                      │ Shows: +delta, age                           │
 │                      │ Action: backup old to _DELETE, move orphan   │
 │                      │ Prompt: "Replace N sessions?"                │
 ├──────────────────────┼──────────────────────────────────────────────┤
 │ [MOVE]               │ Target dir does NOT exist                    │
 │                      │ Shows: age, (new project) tag if applicable  │
 │                      │ Action: move orphan into project dir         │
 │                      │ Prompt: "Move N sessions?"                   │
 ├──────────────────────┼──────────────────────────────────────────────┤
 │ [SKIP - UNKNOWN]     │ No cwd extractable from JSONL/HTML           │
 │                      │ Shows: age                                   │
 │                      │ Action: move to unknown-project/             │
 │                      │ Prompt: "Move N to unknown-project?"         │
 ├──────────────────────┼──────────────────────────────────────────────┤
 │ [SKIP - ALREADY      │ Target dir exists, organized copy is same    │
 │  ORGANIZED]          │ size or larger                               │
 │                      │ Shows: age                                   │
 │                      │ Action: move orphan to _DELETE               │
 │                      │ Prompt: "Move N duplicate orphans to         │
 │                      │  _DELETE?"                                   │
 ├──────────────────────┼──────────────────────────────────────────────┤
 │ [EMPTY]              │ Orphan folder contains no files              │
 │                      │ Action: move to _DELETE                      │
 │                      │ Prompt: "Move N empty folders to _DELETE?"   │
 ├──────────────────────┼──────────────────────────────────────────────┤
 │ [UNRECOGNIZED]       │ Orphan folder has files but no .jsonl/.html  │
 │                      │ Action: move to _DELETE                      │
 │                      │ Prompt: "Move N unrecognized folders to      │
 │                      │  _DELETE?"                                   │
 └──────────────────────┴──────────────────────────────────────────────┘

 Notes:
 - Nothing is permanently deleted; all removals go to _DELETE/
 - REPLACE backs up the OLD organized copy to _DELETE before overwriting
 - --dry-run skips all actions and reindexing
 - --yes auto-confirms all prompts
 - Groups with zero entries are not shown and not prompted
```
