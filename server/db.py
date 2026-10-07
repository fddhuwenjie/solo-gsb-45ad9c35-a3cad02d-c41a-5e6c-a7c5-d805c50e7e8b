"""SQLite connection management and schema initialisation."""
import os
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS question (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    stem        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS option (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    content     TEXT NOT NULL,
    UNIQUE(question_id, position)
);

-- Live-bank answer key, keyed by stable option id.  Sealed papers copy the
-- answer at seal time; editing this row never changes already-sealed papers.
CREATE TABLE IF NOT EXISTS bank_answer (
    question_id INTEGER PRIMARY KEY REFERENCES question(id) ON DELETE CASCADE,
    option_id   INTEGER NOT NULL REFERENCES option(id) ON DELETE CASCADE
);

-- Persisted arrangement draft: one row per paper ('A' / 'B').
CREATE TABLE IF NOT EXISTS paper_draft (
    paper      TEXT PRIMARY KEY CHECK(paper IN ('A', 'B')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS paper_draft_question (
    paper      TEXT NOT NULL,
    question_id INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    PRIMARY KEY(paper, question_id)
);
CREATE TABLE IF NOT EXISTS paper_draft_option (
    paper      TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    option_id  INTEGER NOT NULL,
    position   INTEGER NOT NULL,
    PRIMARY KEY(paper, question_id, option_id)
);

-- A sealed revision of the item bank.  Everything downstream references
-- snapshots, so later edits to the live bank never touch printed papers.
CREATE TABLE IF NOT EXISTS seal (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    version    INTEGER NOT NULL UNIQUE,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sealed_question (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seal_id     INTEGER NOT NULL REFERENCES seal(id) ON DELETE CASCADE,
    source_question_id INTEGER NOT NULL,
    stable_code TEXT NOT NULL,          -- e.g. 'Q3'
    stem        TEXT NOT NULL,
    correct_sealed_option_id INTEGER,   -- current answer (flipped by errata)
    UNIQUE(seal_id, source_question_id)
);
CREATE TABLE IF NOT EXISTS sealed_option (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sealed_question_id INTEGER NOT NULL
        REFERENCES sealed_question(id) ON DELETE CASCADE,
    source_option_id INTEGER NOT NULL,
    stable_code TEXT NOT NULL,          -- e.g. 'O7'
    content     TEXT NOT NULL,
    UNIQUE(sealed_question_id, source_option_id)
);

CREATE TABLE IF NOT EXISTS paper (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    seal_id INTEGER NOT NULL REFERENCES seal(id) ON DELETE CASCADE,
    name    TEXT NOT NULL CHECK(name IN ('A', 'B')),
    UNIQUE(seal_id, name)
);
CREATE TABLE IF NOT EXISTS paper_question (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id         INTEGER NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    sealed_question_id INTEGER NOT NULL
        REFERENCES sealed_question(id) ON DELETE CASCADE,
    number           INTEGER NOT NULL,
    UNIQUE(paper_id, number)
);
CREATE TABLE IF NOT EXISTS paper_option (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_question_id INTEGER NOT NULL
        REFERENCES paper_question(id) ON DELETE CASCADE,
    sealed_option_id INTEGER NOT NULL
        REFERENCES sealed_option(id) ON DELETE CASCADE,
    letter           TEXT NOT NULL CHECK(letter IN ('A','B','C','D')),
    UNIQUE(paper_question_id, letter),
    UNIQUE(paper_question_id, sealed_option_id)
);

-- Registered answer sheets: one sheet per examinee per seal version.  The
-- stored sealed_option_id pins each response to the sealed snapshot, so
-- later bank edits, other seal versions and errata never rewrite the
-- registered answers or the registered scores.
CREATE TABLE IF NOT EXISTS answer_sheet (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seal_id     INTEGER NOT NULL REFERENCES seal(id) ON DELETE CASCADE,
    paper       TEXT NOT NULL CHECK(paper IN ('A', 'B')),
    examinee    TEXT NOT NULL,
    total_score INTEGER NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(seal_id, examinee)
);
CREATE TABLE IF NOT EXISTS answer_sheet_item (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id          INTEGER NOT NULL REFERENCES answer_sheet(id) ON DELETE CASCADE,
    paper_question_id INTEGER NOT NULL REFERENCES paper_question(id) ON DELETE CASCADE,
    letter            TEXT CHECK(letter IN ('A','B','C','D')),  -- NULL = 空白
    sealed_option_id  INTEGER REFERENCES sealed_option(id),     -- NULL = 空白
    score             INTEGER NOT NULL CHECK(score IN (0, 1)),
    UNIQUE(sheet_id, paper_question_id)
);

-- Transcription corrections of a registered answer card.  A correction never
-- rewrites answer_sheet / answer_sheet_item: the registered letters and the
-- registered score stay forever as they were at registration time.  The
-- effective answer of a question is the newest correction item for it when
-- one exists, otherwise the original registered item.  Like errata, a whole
-- correction request is either applied together or refused with no trace.
CREATE TABLE IF NOT EXISTS answer_correction_batch (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sheet_id   INTEGER NOT NULL REFERENCES answer_sheet(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS answer_correction_item (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id          INTEGER NOT NULL
        REFERENCES answer_correction_batch(id) ON DELETE CASCADE,
    paper_question_id INTEGER NOT NULL REFERENCES paper_question(id) ON DELETE CASCADE,
    old_letter        TEXT CHECK(old_letter IN ('A','B','C','D')),  -- NULL = 空白
    new_letter        TEXT CHECK(new_letter IN ('A','B','C','D')),  -- NULL = 空白
    UNIQUE(batch_id, paper_question_id)
);

-- Erratum batch: all items succeed together or the whole request is refused.
CREATE TABLE IF NOT EXISTS erratum_batch (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seal_id    INTEGER NOT NULL REFERENCES seal(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS erratum_item (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id                 INTEGER NOT NULL
        REFERENCES erratum_batch(id) ON DELETE CASCADE,
    sealed_question_id       INTEGER NOT NULL
        REFERENCES sealed_question(id) ON DELETE CASCADE,
    new_sealed_option_id     INTEGER NOT NULL
        REFERENCES sealed_option(id),
    paper_a_old_letter       TEXT,
    paper_a_new_letter       TEXT,
    paper_b_old_letter       TEXT,
    paper_b_new_letter       TEXT
);

-- Released score batches: an immutable snapshot of every sheet registered at
-- publish time, graded against the answer key as of that same moment.  The
-- batch rows copy paper/examinee/total and per-question scores, so later
-- registrations, errata or bank edits never rewrite a published batch.
CREATE TABLE IF NOT EXISTS release_batch (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seal_id    INTEGER NOT NULL REFERENCES seal(id) ON DELETE CASCADE,
    batch_no   INTEGER NOT NULL,            -- per-seal sequence: 1, 2, 3...
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(seal_id, batch_no)
);
CREATE TABLE IF NOT EXISTS release_sheet (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id    INTEGER NOT NULL REFERENCES release_batch(id) ON DELETE CASCADE,
    paper       TEXT NOT NULL CHECK(paper IN ('A', 'B')),
    examinee    TEXT NOT NULL,
    total_score INTEGER NOT NULL,
    UNIQUE(batch_id, examinee)
);
CREATE TABLE IF NOT EXISTS release_item (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    release_sheet_id INTEGER NOT NULL REFERENCES release_sheet(id) ON DELETE CASCADE,
    number           INTEGER NOT NULL,      -- printed question number
    score            INTEGER NOT NULL CHECK(score IN (0, 1)),
    UNIQUE(release_sheet_id, number)
);
"""


def get_db():
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    db_path = app.config["DATABASE"]
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)
