"""Local dual-paper printing & answer-verification web app.

Run:  gunicorn server:app   (see Dockerfile / docker-compose.yml)
"""
import os
import sqlite3

from flask import Flask, g, jsonify, render_template, request

from .db import get_db, init_app

app = Flask(__name__)
app.config["DATABASE"] = os.environ.get(
    "DATABASE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "exam.db")
)
app.config["JSON_AS_ASCII"] = False
init_app(app)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return jsonify({"ok": False, "error": err.message}), err.status


@app.errorhandler(404)
def _handle_404(err):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "接口不存在"}), 404
    return err, 404


def payload():
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(400, "请求体必须是 JSON")
    return data


def require_text(data, key, label):
    val = data.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ApiError(400, f"{label}不能为空")
    return val.strip()


def fetch_questions(db):
    """Return live bank questions with options and usage counters."""
    questions = [dict(r) for r in db.execute(
        """SELECT q.id, q.stem,
                  (SELECT COUNT(DISTINCT s.id)
                     FROM sealed_question sq
                     JOIN seal s ON s.id = sq.seal_id
                    WHERE sq.source_question_id = q.id) AS seal_count
             FROM question q ORDER BY q.id"""
    ).fetchall()]
    for q in questions:
        q["options"] = [dict(r) for r in db.execute(
            "SELECT id, question_id, position, content FROM option "
            "WHERE question_id = ? ORDER BY position", (q["id"],)
        ).fetchall()]
        ans = db.execute(
            "SELECT option_id FROM bank_answer WHERE question_id = ?", (q["id"],)
        ).fetchone()
        q["correct_option_id"] = ans["option_id"] if ans else None
    return questions


# ---------------------------------------------------------------------------
# question bank
# ---------------------------------------------------------------------------

@app.get("/api/questions")
def list_questions():
    return jsonify({"ok": True, "questions": fetch_questions(get_db())})


@app.post("/api/questions")
def create_question():
    data = payload()
    stem = require_text(data, "stem", "题干")
    options = data.get("options")
    if not isinstance(options, list) or len(options) != 4:
        raise ApiError(400, "必须提供四个选项")
    texts = []
    for i, opt in enumerate(options):
        if not isinstance(opt, str) or not opt.strip():
            raise ApiError(400, f"第 {i + 1} 个选项内容不能为空")
        texts.append(opt.strip())
    correct = data.get("correct_position")
    if not isinstance(correct, int) or not 0 <= correct <= 3:
        raise ApiError(400, "正确选项位置必须是 0~3")

    db = get_db()
    cur = db.execute("INSERT INTO question (stem) VALUES (?)", (stem,))
    qid = cur.lastrowid
    option_ids = []
    for i, text in enumerate(texts):
        oid = db.execute(
            "INSERT INTO option (question_id, position, content) VALUES (?, ?, ?)",
            (qid, i, text),
        ).lastrowid
        option_ids.append(oid)
    db.execute(
        "INSERT INTO bank_answer (question_id, option_id) VALUES (?, ?)",
        (qid, option_ids[correct]),
    )
    db.commit()
    q = next(q for q in fetch_questions(db) if q["id"] == qid)
    return jsonify({"ok": True, "question": q})


@app.put("/api/questions/<int:qid>")
def update_question(qid):
    data = payload()
    db = get_db()
    row = db.execute("SELECT id FROM question WHERE id = ?", (qid,)).fetchone()
    if row is None:
        raise ApiError(404, "题目不存在")
    stem = require_text(data, "stem", "题干")
    texts = data.get("options")
    if not isinstance(texts, list) or len(texts) != 4:
        raise ApiError(400, "必须提供四个选项")
    clean = []
    for i, opt in enumerate(texts):
        if not isinstance(opt, str) or not opt.strip():
            raise ApiError(400, f"第 {i + 1} 个选项内容不能为空")
        clean.append(opt.strip())
    correct = data.get("correct_position")
    if not isinstance(correct, int) or not 0 <= correct <= 3:
        raise ApiError(400, "正确选项位置必须是 0~3")

    existing = db.execute(
        "SELECT id FROM option WHERE question_id = ? ORDER BY position", (qid,)
    ).fetchall()
    db.execute("UPDATE question SET stem = ? WHERE id = ?", (stem, qid))
    for i, text in enumerate(clean):
        db.execute("UPDATE option SET content = ? WHERE id = ?", (text, existing[i]["id"]))
    db.execute(
        "UPDATE bank_answer SET option_id = ? WHERE question_id = ?",
        (existing[correct]["id"], qid),
    )
    db.commit()
    q = next(q for q in fetch_questions(db) if q["id"] == qid)
    return jsonify({"ok": True, "question": q})


@app.delete("/api/questions/<int:qid>")
def delete_question(qid):
    db = get_db()
    row = db.execute("SELECT id FROM question WHERE id = ?", (qid,)).fetchone()
    if row is None:
        raise ApiError(404, "题目不存在")
    db.execute("DELETE FROM question WHERE id = ?", (qid,))
    db.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# arrangement drafts (A / B)
# ---------------------------------------------------------------------------

def normalize_draft(db, paper, raw):
    """Validate/coerce a draft body into {questions:[{id, options:[ids]}]}.

    Unknown question/option ids and options of other questions are dropped;
    a question missing its four options falls back to bank order.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("questions"), list):
        raise ApiError(400, f"{paper} 卷草稿格式应为 {{questions: [...]}}")
    bank = {q["id"]: q for q in fetch_questions(db)}
    seen = set()
    result = []
    for item in raw["questions"]:
        if not isinstance(item, dict):
            raise ApiError(400, f"{paper} 卷草稿条目格式错误")
        qid = item.get("id")
        if not isinstance(qid, int) or qid not in bank or qid in seen:
            continue
        seen.add(qid)
        opt_ids = item.get("options")
        valid = (
            isinstance(opt_ids, list)
            and len(opt_ids) == 4
            and len(set(opt_ids)) == 4
            and all(o["id"] in opt_ids for o in bank[qid]["options"])
        )
        ordered = list(opt_ids) if valid else [o["id"] for o in bank[qid]["options"]]
        result.append({"id": qid, "options": ordered})
    return {"questions": result}


def save_draft(db, paper, draft):
    db.execute("INSERT INTO paper_draft (paper) VALUES (?) "
               "ON CONFLICT(paper) DO UPDATE SET updated_at = datetime('now')", (paper,))
    db.execute("DELETE FROM paper_draft_question WHERE paper = ?", (paper,))
    db.execute("DELETE FROM paper_draft_option WHERE paper = ?", (paper,))
    for pos, q in enumerate(draft["questions"]):
        db.execute(
            "INSERT INTO paper_draft_question (paper, question_id, position) VALUES (?, ?, ?)",
            (paper, q["id"], pos),
        )
        for opos, oid in enumerate(q["options"]):
            db.execute(
                "INSERT INTO paper_draft_option (paper, question_id, option_id, position) "
                "VALUES (?, ?, ?, ?)",
                (paper, q["id"], oid, opos),
            )


def load_draft(db, paper):
    rows = db.execute(
        "SELECT question_id, position FROM paper_draft_question "
        "WHERE paper = ? ORDER BY position",
        (paper,),
    ).fetchall()
    questions = []
    bank = {q["id"]: q for q in fetch_questions(db)}
    for r in rows:
        if r["question_id"] not in bank:
            continue
        opt_rows = db.execute(
            "SELECT option_id FROM paper_draft_option WHERE paper = ? AND question_id = ? "
            "ORDER BY position", (paper, r["question_id"])
        ).fetchall()
        opt_ids = [x["option_id"] for x in opt_rows]
        valid = (
            len(opt_ids) == 4
            and len(set(opt_ids)) == 4
            and all(o["id"] in opt_ids for o in bank[r["question_id"]]["options"])
        )
        if not valid:
            opt_ids = [o["id"] for o in bank[r["question_id"]]["options"]]
        questions.append({"id": r["question_id"], "options": opt_ids})
    return {"questions": questions}


@app.get("/api/draft/<paper>")
def get_draft(paper):
    if paper not in ("A", "B"):
        raise ApiError(404, "卷别只支持 A / B")
    db = get_db()
    draft = load_draft(db, paper)
    # fill in bank questions never arranged yet, in bank order
    arranged = {q["id"] for q in draft["questions"]}
    for q in fetch_questions(db):
        if q["id"] not in arranged:
            draft["questions"].append({"id": q["id"], "options": [o["id"] for o in q["options"]]})
    return jsonify({"ok": True, "paper": paper, "draft": draft})


@app.put("/api/draft/<paper>")
def put_draft(paper):
    if paper not in ("A", "B"):
        raise ApiError(404, "卷别只支持 A / B")
    db = get_db()
    draft = normalize_draft(db, paper, payload())
    save_draft(db, paper, draft)
    db.commit()
    return jsonify({"ok": True, "draft": draft})


# ---------------------------------------------------------------------------
# seals
# ---------------------------------------------------------------------------

@app.post("/api/seals")
def create_seal():
    data = payload()
    note = (data.get("note") or "").strip() if isinstance(data.get("note"), str) else ""
    db = get_db()

    # Source of truth: persisted drafts (optionally overridden in the body).
    body = data.get("papers") if isinstance(data.get("papers"), dict) else {}
    drafts = {}
    for paper in ("A", "B"):
        if paper in body:
            drafts[paper] = normalize_draft(db, paper, body[paper])
        else:
            drafts[paper] = load_draft(db, paper)

    for paper in ("A", "B"):
        if not drafts[paper]["questions"]:
            raise ApiError(400, f"{paper} 卷至少要包含一道题")
    ids_a = [q["id"] for q in drafts["A"]["questions"]]
    ids_b = [q["id"] for q in drafts["B"]["questions"]]
    if set(ids_a) != set(ids_b) or len(ids_a) != len(set(ids_a)):
        raise ApiError(400, "A、B 两卷必须包含相同的题目集合（顺序可以不同）")

    # Pre-flight: every bank question must still have an answer on record.
    for item in drafts["A"]["questions"]:
        ans = db.execute(
            "SELECT option_id FROM bank_answer WHERE question_id = ?", (item["id"],)
        ).fetchone()
        if ans is None:
            raise ApiError(400, f"题目 Q{item['id']} 缺少正确答案，无法封存")

    version = (db.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM seal").fetchone()["v"])
    cur = db.execute("INSERT INTO seal (version, note) VALUES (?, ?)", (version, note))
    seal_id = cur.lastrowid

    try:
        # Build one shared snapshot (question + options + answer) per bank item.
        snapshots = {}  # source question id -> {"sq_id":, "options": {src_oid: so_id}}
        for item in drafts["A"]["questions"]:
            qrow = db.execute("SELECT stem FROM question WHERE id = ?", (item["id"],)).fetchone()
            sq_id = db.execute(
                "INSERT INTO sealed_question (seal_id, source_question_id, stable_code, stem) "
                "VALUES (?, ?, ?, ?)",
                (seal_id, item["id"], f"Q{item['id']}", qrow["stem"]),
            ).lastrowid
            option_by_id = {}
            for src_oid in item["options"]:
                orow = db.execute("SELECT content FROM option WHERE id = ?", (src_oid,)).fetchone()
                so_id = db.execute(
                    "INSERT INTO sealed_option (sealed_question_id, source_option_id, "
                    "stable_code, content) VALUES (?, ?, ?, ?)",
                    (sq_id, src_oid, f"O{src_oid}", orow["content"]),
                ).lastrowid
                option_by_id[src_oid] = so_id

            answer_row = db.execute(
                "SELECT option_id FROM bank_answer WHERE question_id = ?", (item["id"],)
            ).fetchone()
            db.execute(
                "UPDATE sealed_question SET correct_sealed_option_id = ? WHERE id = ?",
                (option_by_id[answer_row["option_id"]], sq_id),
            )
            snapshots[item["id"]] = {"sq_id": sq_id, "options": option_by_id}

        # Each paper maps the shared snapshots to its own numbers and A-D letters.
        for paper in ("A", "B"):
            paper_id = db.execute(
                "INSERT INTO paper (seal_id, name) VALUES (?, ?)", (seal_id, paper)
            ).lastrowid
            for number, item in enumerate(drafts[paper]["questions"], start=1):
                snap = snapshots[item["id"]]
                pq_id = db.execute(
                    "INSERT INTO paper_question (paper_id, sealed_question_id, number) "
                    "VALUES (?, ?, ?)",
                    (paper_id, snap["sq_id"], number),
                ).lastrowid
                for letter, src_oid in zip("ABCD", item["options"]):
                    db.execute(
                        "INSERT INTO paper_option (paper_question_id, sealed_option_id, letter) "
                        "VALUES (?, ?, ?)",
                        (pq_id, snap["options"][src_oid], letter),
                    )
        db.commit()
    except sqlite3.DatabaseError:
        db.rollback()
        raise ApiError(500, "封存写入失败，已回滚，未生成新版本")
    return jsonify({"ok": True, "seal_id": seal_id, "version": version})


def _seal_summary(db, seal_row):
    s = dict(seal_row)
    s["question_count"] = db.execute(
        "SELECT COUNT(*) c FROM sealed_question WHERE seal_id = ?", (s["id"],)
    ).fetchone()["c"]
    s["erratum_count"] = db.execute(
        "SELECT COUNT(*) c FROM erratum_batch WHERE seal_id = ?", (s["id"],)
    ).fetchone()["c"]
    return s


@app.get("/api/seals")
def list_seals():
    db = get_db()
    seals = [_seal_summary(db, r) for r in db.execute(
        "SELECT id, version, note, created_at FROM seal ORDER BY version DESC"
    ).fetchall()]
    return jsonify({"ok": True, "seals": seals})


def _build_seal_detail(db, seal_id):
    seal = db.execute(
        "SELECT id, version, note, created_at FROM seal WHERE id = ?", (seal_id,)
    ).fetchone()
    if seal is None:
        raise ApiError(404, "封存卷不存在")
    detail = _seal_summary(db, seal)
    detail["papers"] = {}
    for paper_name in ("A", "B"):
        prow = db.execute(
            "SELECT id FROM paper WHERE seal_id = ? AND name = ?", (seal_id, paper_name)
        ).fetchone()
        questions_out = []
        pq_rows = db.execute(
            "SELECT id, number, sealed_question_id FROM paper_question "
            "WHERE paper_id = ? ORDER BY number", (prow["id"],)
        ).fetchall()
        for pq in pq_rows:
            sq = db.execute(
                "SELECT id, source_question_id, stable_code, stem, correct_sealed_option_id "
                "FROM sealed_question WHERE id = ?", (pq["sealed_question_id"],)
            ).fetchone()
            options = []
            for po in db.execute(
                """SELECT po.letter, so.id AS sealed_option_id, so.source_option_id,
                          so.stable_code, so.content
                     FROM paper_option po
                     JOIN sealed_option so ON so.id = po.sealed_option_id
                    WHERE po.paper_question_id = ? ORDER BY po.letter""",
                (pq["id"],)
            ).fetchall():
                od = dict(po)
                od["is_correct"] = (po["sealed_option_id"] == sq["correct_sealed_option_id"])
                options.append(od)
            qd = dict(sq)
            qd["number"] = pq["number"]
            qd["options"] = options
            qd["correct_letter"] = next(
                (o["letter"] for o in options if o["is_correct"]), None
            )
            questions_out.append(qd)
        detail["papers"][paper_name] = {"name": paper_name, "questions": questions_out}
    return detail


@app.get("/api/seals/<int:seal_id>")
def get_seal(seal_id):
    return jsonify({"ok": True, "seal": _build_seal_detail(get_db(), seal_id)})


# ---------------------------------------------------------------------------
# errata
# ---------------------------------------------------------------------------

def _errata(db, seal_id):
    # letter -> sealed option stable code, per paper per question
    letter_codes = {"A": {}, "B": {}}
    for pname in ("A", "B"):
        for r in db.execute(
            """SELECT pq.sealed_question_id, po.letter, so.stable_code
                 FROM paper p
                 JOIN paper_question pq ON pq.paper_id = p.id
                 JOIN paper_option po ON po.paper_question_id = pq.id
                 JOIN sealed_option so ON so.id = po.sealed_option_id
                WHERE p.seal_id = ? AND p.name = ?""",
            (seal_id, pname),
        ).fetchall():
            letter_codes[pname].setdefault(r["sealed_question_id"], {})[r["letter"]] = r["stable_code"]

    batches = []
    for b in db.execute(
        "SELECT id, reason, created_at FROM erratum_batch WHERE seal_id = ? ORDER BY id",
        (seal_id,),
    ).fetchall():
        items = []
        for ei in db.execute(
            """SELECT ei.id, ei.sealed_question_id, ei.new_sealed_option_id,
                      ei.paper_a_old_letter, ei.paper_a_new_letter,
                      ei.paper_b_old_letter, ei.paper_b_new_letter,
                      sq.source_question_id, sq.stable_code AS question_code,
                      so_new.stable_code AS new_option_code
                 FROM erratum_item ei
                 JOIN sealed_question sq ON sq.id = ei.sealed_question_id
                 JOIN sealed_option so_new ON so_new.id = ei.new_sealed_option_id
                WHERE ei.batch_id = ? ORDER BY ei.id""",
            (b["id"],),
        ).fetchall():
            d = dict(ei)
            sq_id = d["sealed_question_id"]
            d["paper_a_old_option_code"] = letter_codes["A"].get(sq_id, {}).get(d["paper_a_old_letter"])
            d["paper_a_new_option_code"] = letter_codes["A"].get(sq_id, {}).get(d["paper_a_new_letter"])
            d["paper_b_old_option_code"] = letter_codes["B"].get(sq_id, {}).get(d["paper_b_old_letter"])
            d["paper_b_new_option_code"] = letter_codes["B"].get(sq_id, {}).get(d["paper_b_new_letter"])
            items.append(d)
        bd = dict(b)
        bd["items"] = items
        batches.append(bd)
    return batches


@app.get("/api/seals/<int:seal_id>/errata")
def list_errata(seal_id):
    db = get_db()
    if db.execute("SELECT 1 FROM seal WHERE id = ?", (seal_id,)).fetchone() is None:
        raise ApiError(404, "封存卷不存在")
    return jsonify({"ok": True, "batches": _errata(db, seal_id)})


@app.post("/api/seals/<int:seal_id>/errata")
def create_errata(seal_id):
    data = payload()
    reason = data.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    items_raw = data.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise ApiError(400, "勘误至少包含一条修正")

    db = get_db()
    seal = db.execute("SELECT id FROM seal WHERE id = ?", (seal_id,)).fetchone()
    if seal is None:
        raise ApiError(404, "封存卷不存在")

    # ---- phase 1: validate everything, write nothing ---------------------
    sealed_questions = {
        r["id"]: dict(r) for r in db.execute(
            "SELECT id, source_question_id, stable_code, correct_sealed_option_id "
            "FROM sealed_question WHERE seal_id = ?", (seal_id,)
        ).fetchall()
    }
    sealed_options = {}   # sealed_option_id -> row
    options_of_question = {}  # sq_id -> {sealed_option_id: row}
    for r in db.execute(
        """SELECT so.id, so.sealed_question_id, so.source_option_id, so.stable_code
             FROM sealed_option so
            WHERE so.sealed_question_id IN
                  (SELECT id FROM sealed_question WHERE seal_id = ?)""",
        (seal_id,),
    ).fetchall():
        d = dict(r)
        sealed_options[d["id"]] = d
        options_of_question.setdefault(d["sealed_question_id"], {})[d["id"]] = d

    # paper mapping: sq_id -> {letter: sealed_option_id}
    paper_map = {"A": {}, "B": {}}
    for pname in ("A", "B"):
        for r in db.execute(
            """SELECT pq.sealed_question_id, po.letter, po.sealed_option_id
                 FROM paper p
                 JOIN paper_question pq ON pq.paper_id = p.id
                 JOIN paper_option po ON po.paper_question_id = pq.id
                WHERE p.seal_id = ? AND p.name = ?""",
            (seal_id, pname),
        ).fetchall():
            paper_map[pname].setdefault(r["sealed_question_id"], {})[r["letter"]] = r["sealed_option_id"]

    prepared = []
    seen = set()
    for idx, it in enumerate(items_raw, start=1):
        if not isinstance(it, dict):
            raise ApiError(400, f"第 {idx} 条勘误格式错误")
        sq_id = it.get("sealed_question_id")
        new_so_id = it.get("new_sealed_option_id")
        if not isinstance(sq_id, int) or sq_id not in sealed_questions:
            raise ApiError(400, f"第 {idx} 条：题目不属于本次封存卷")
        if not isinstance(new_so_id, int) or new_so_id not in sealed_options:
            raise ApiError(400, f"第 {idx} 条（{sealed_questions[sq_id]['stable_code']}）：选项不属于封存题目")
        if new_so_id not in options_of_question[sq_id]:
            raise ApiError(400, f"第 {idx} 条（{sealed_questions[sq_id]['stable_code']}）：选项不属于封存题目")
        if sq_id in seen:
            raise ApiError(400, f"第 {idx} 条：{sealed_questions[sq_id]['stable_code']} 重复提交")
        sq = sealed_questions[sq_id]
        if new_so_id == sq["correct_sealed_option_id"]:
            raise ApiError(400, f"第 {idx} 条（{sq['stable_code']}）：新答案与原答案一致，无需勘误")
        missing = [p for p in ("A", "B") if sq_id not in paper_map[p]]
        if missing:
            raise ApiError(400,
                f"第 {idx} 条（{sq['stable_code']}）：{'、'.join(missing)} 卷缺少该题映射，整次拒绝")

        def letters(pname):
            mapping = paper_map[pname][sq_id]
            old = next(l for l, so in mapping.items() if so == sq["correct_sealed_option_id"])
            new = next(l for l, so in mapping.items() if so == new_so_id)
            return old, new

        a_old, a_new = letters("A")
        b_old, b_new = letters("B")
        prepared.append({
            "sq": sq, "new_so_id": new_so_id,
            "a": (a_old, a_new), "b": (b_old, b_new),
        })
        seen.add(sq_id)

    # ---- phase 2: commit --------------------------------------------------
    try:
        batch_id = db.execute(
            "INSERT INTO erratum_batch (seal_id, reason) VALUES (?, ?)", (seal_id, reason)
        ).lastrowid
        for p in prepared:
            db.execute(
                """INSERT INTO erratum_item
                   (batch_id, sealed_question_id, new_sealed_option_id,
                    paper_a_old_letter, paper_a_new_letter,
                    paper_b_old_letter, paper_b_new_letter)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (batch_id, p["sq"]["id"], p["new_so_id"],
                 p["a"][0], p["a"][1], p["b"][0], p["b"][1]),
            )
            db.execute(
                "UPDATE sealed_question SET correct_sealed_option_id = ? WHERE id = ?",
                (p["new_so_id"], p["sq"]["id"]),
            )
        db.commit()
    except sqlite3.DatabaseError as exc:
        db.rollback()
        raise ApiError(500, f"勘误写入失败，已回滚：{exc}")

    return jsonify({
        "ok": True,
        "batch_id": batch_id,
        "applied": [
            {
                "question_code": p["sq"]["stable_code"],
                "A": {"old": p["a"][0], "new": p["a"][1]},
                "B": {"old": p["b"][0], "new": p["b"][1]},
            }
            for p in prepared
        ],
    })


# ---------------------------------------------------------------------------
# answer sheets (registration & post-errata review)
# ---------------------------------------------------------------------------

def _printed_paper(db, seal_id, paper):
    """Printed questions of one paper: number -> row, plus letter -> sealed option."""
    questions = {}
    for r in db.execute(
        """SELECT pq.id AS pq_id, pq.number, pq.sealed_question_id
             FROM paper p
             JOIN paper_question pq ON pq.paper_id = p.id
            WHERE p.seal_id = ? AND p.name = ?""",
        (seal_id, paper),
    ).fetchall():
        questions[r["number"]] = dict(r)
    letters = {}  # pq_id -> {letter: sealed_option_id}
    for r in db.execute(
        """SELECT po.paper_question_id, po.letter, po.sealed_option_id
             FROM paper_option po
            WHERE po.paper_question_id IN
                  (SELECT pq.id FROM paper_question pq
                     JOIN paper p ON p.id = pq.paper_id
                    WHERE p.seal_id = ? AND p.name = ?)""",
        (seal_id, paper),
    ).fetchall():
        letters.setdefault(r["paper_question_id"], {})[r["letter"]] = r["sealed_option_id"]
    return questions, letters


def _effective_letters(db, sheet_id):
    """Effective answer per paper_question_id of one card.

    Registered letters are the base; every correction group (oldest first)
    overlays its items, so the newest group wins per question.  A letter of
    None means an effective blank.  Registered rows are never modified.
    """
    effective = {
        r["paper_question_id"]: r["letter"]
        for r in db.execute(
            "SELECT paper_question_id, letter FROM answer_sheet_item WHERE sheet_id = ?",
            (sheet_id,),
        ).fetchall()
    }
    rows = db.execute(
        """SELECT ci.paper_question_id, ci.new_letter
             FROM sheet_correction_item ci
             JOIN sheet_correction c ON c.id = ci.correction_id
            WHERE c.sheet_id = ?
            ORDER BY c.id, ci.id""",
        (sheet_id,),
    ).fetchall()
    for r in rows:
        effective[r["paper_question_id"]] = r["new_letter"]
    return effective


def _option_code_map(db, seal_id, paper):
    """{(paper_question_id, letter): sealed option stable code} for a paper."""
    code_map = {}
    for r in db.execute(
        """SELECT po.paper_question_id, po.letter, so.stable_code
             FROM paper p
             JOIN paper_question pq ON pq.paper_id = p.id
             JOIN paper_option po ON po.paper_question_id = pq.id
             JOIN sealed_option so ON so.id = po.sealed_option_id
            WHERE p.seal_id = ? AND p.name = ?""",
        (seal_id, paper),
    ).fetchall():
        code_map[(r["paper_question_id"], r["letter"])] = r["stable_code"]
    return code_map


def _correction_history(db, sheet_id, code_map):
    """Correction groups of one card, with before/after letters and codes."""
    groups = []
    for g in db.execute(
        "SELECT id, reason, created_at FROM sheet_correction "
        "WHERE sheet_id = ? ORDER BY id",
        (sheet_id,),
    ).fetchall():
        items = []
        for ci in db.execute(
            """SELECT ci.paper_question_id, pq.number, ci.old_letter, ci.new_letter
                 FROM sheet_correction_item ci
                 JOIN paper_question pq ON pq.id = ci.paper_question_id
                WHERE ci.correction_id = ? ORDER BY pq.number""",
            (g["id"],),
        ).fetchall():
            items.append({
                "number": ci["number"],
                "old_letter": ci["old_letter"],
                "new_letter": ci["new_letter"],
                "old_option_code": code_map.get((ci["paper_question_id"], ci["old_letter"])),
                "new_option_code": code_map.get((ci["paper_question_id"], ci["new_letter"])),
            })
        groups.append({
            "id": g["id"], "reason": g["reason"], "created_at": g["created_at"],
            "items": items,
        })
    return groups


@app.post("/api/seals/<int:seal_id>/sheets")
def create_sheet(seal_id):
    data = payload()
    paper = data.get("paper")
    if paper not in ("A", "B"):
        raise ApiError(400, "卷别只支持 A / B")
    examinee = require_text(data, "examinee", "考生编号")
    answers = data.get("answers")
    if not isinstance(answers, list):
        raise ApiError(400, "answers 应为逐题作答列表")

    db = get_db()
    if db.execute("SELECT 1 FROM seal WHERE id = ?", (seal_id,)).fetchone() is None:
        raise ApiError(404, "封存卷不存在")
    printed, letters = _printed_paper(db, seal_id, paper)

    # ---- validate the whole card first; any problem refuses everything ----
    cleaned = {}  # number -> letter (None = 空白)
    for idx, item in enumerate(answers, start=1):
        if not isinstance(item, dict):
            raise ApiError(400, f"第 {idx} 条作答格式错误，整张拒绝")
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int):
            raise ApiError(400, f"第 {idx} 条作答：题号格式错误，整张拒绝")
        if number not in printed:
            raise ApiError(400, f"题号 {number} 不在 {paper} 卷印出的题号中（多余题号），整张拒绝")
        if number in cleaned:
            raise ApiError(400, f"题号 {number} 重复作答，整张拒绝")
        letter = item.get("letter")
        if letter is None or (isinstance(letter, str) and not letter.strip()):
            cleaned[number] = None
        elif isinstance(letter, str) \
                and letter.strip().upper() in letters[printed[number]["pq_id"]]:
            cleaned[number] = letter.strip().upper()
        else:
            raise ApiError(400, f"第 {number} 题：作答字母 {letter!r} 不属于该题选项，整张拒绝")
    missing = [n for n in sorted(printed) if n not in cleaned]
    if missing:
        raise ApiError(400, "缺少题号 " + "、".join(map(str, missing)) + " 的作答，整张拒绝")

    if db.execute(
        "SELECT 1 FROM answer_sheet WHERE seal_id = ? AND examinee = ?",
        (seal_id, examinee),
    ).fetchone() is not None:
        raise ApiError(409, f"考生 {examinee} 在本封存版本已登记过答题卡，不能重复登记")

    # ---- grade against the current key and store in one transaction -------
    correct_of = {
        r["id"]: r["correct_sealed_option_id"]
        for r in db.execute(
            "SELECT id, correct_sealed_option_id FROM sealed_question WHERE seal_id = ?",
            (seal_id,),
        ).fetchall()
    }
    try:
        sheet_id = db.execute(
            "INSERT INTO answer_sheet (seal_id, paper, examinee, total_score) VALUES (?, ?, ?, 0)",
            (seal_id, paper, examinee),
        ).lastrowid
        total = 0
        for number in sorted(cleaned):
            pq = printed[number]
            letter = cleaned[number]
            so_id = letters[pq["pq_id"]][letter] if letter else None
            score = 1 if so_id is not None and so_id == correct_of[pq["sealed_question_id"]] else 0
            total += score
            db.execute(
                """INSERT INTO answer_sheet_item
                   (sheet_id, paper_question_id, letter, sealed_option_id, score)
                   VALUES (?, ?, ?, ?, ?)""",
                (sheet_id, pq["pq_id"], letter, so_id, score),
            )
        db.execute("UPDATE answer_sheet SET total_score = ? WHERE id = ?", (total, sheet_id))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ApiError(409, f"考生 {examinee} 在本封存版本已登记过答题卡，不能重复登记")
    except sqlite3.DatabaseError:
        db.rollback()
        raise ApiError(500, "登记写入失败，已回滚，未留下记录")
    return jsonify({"ok": True, "sheet_id": sheet_id, "total_score": total})


@app.post("/api/seals/<int:seal_id>/sheets/<int:sheet_id>/corrections")
def create_correction(seal_id, sheet_id):
    data = payload()
    reason = data.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    items_raw = data.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise ApiError(400, "更正至少包含一条修正")

    db = get_db()

    # BEGIN IMMEDIATE serialises corrections against errata and releases:
    # the whole group is validated against and written to one database state,
    # so it lands either wholly inside a concurrent publish's snapshot or
    # wholly in the next batch.
    try:
        db.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        raise ApiError(409, "另一个写入操作正在进行，请稍后重试")
    try:
        sheet = db.execute(
            "SELECT id, paper FROM answer_sheet WHERE id = ? AND seal_id = ?",
            (sheet_id, seal_id),
        ).fetchone()
        if sheet is None:
            db.rollback()
            raise ApiError(404, "答题卡不存在")
        paper = sheet["paper"]
        printed, letters = _printed_paper(db, seal_id, paper)

        # Effective answers right now (registered overlaid with older groups).
        effective = _effective_letters(db, sheet_id)

        # ---- validate the whole group first; any flaw refuses all --------
        prepared = []   # (pq_id, number, old, new)
        seen = set()
        for idx, it in enumerate(items_raw, start=1):
            if not isinstance(it, dict):
                db.rollback()
                raise ApiError(400, f"第 {idx} 条更正格式错误，整次拒绝")
            number = it.get("number")
            if isinstance(number, bool) or not isinstance(number, int):
                db.rollback()
                raise ApiError(400, f"第 {idx} 条更正：题号格式错误，整次拒绝")
            if number not in printed:
                db.rollback()
                raise ApiError(
                    400, f"题号 {number} 不在 {paper} 卷印出的题号中，整次拒绝")
            if number in seen:
                db.rollback()
                raise ApiError(400, f"题号 {number} 重复提交，整次拒绝")
            seen.add(number)
            pq_id = printed[number]["pq_id"]
            letter = it.get("letter")
            if letter is None or (isinstance(letter, str) and not letter.strip()):
                new = None
            elif isinstance(letter, str) \
                    and letter.strip().upper() in letters[pq_id]:
                new = letter.strip().upper()
            else:
                db.rollback()
                raise ApiError(
                    400, f"第 {number} 题：更正字母 {letter!r} 不属于该题选项，整次拒绝")
            prepared.append((pq_id, number, effective[pq_id], new))

        if all(old == new for _, _, old, new in prepared):
            db.rollback()
            raise ApiError(400, "整组更正与当前作答完全相同，整次拒绝且不留记录")

        # ---- write the group (registered answers stay untouched) ---------
        group_id = db.execute(
            "INSERT INTO sheet_correction (sheet_id, reason) VALUES (?, ?)",
            (sheet_id, reason),
        ).lastrowid
        for pq_id, _number, old, new in prepared:
            db.execute(
                "INSERT INTO sheet_correction_item "
                "(correction_id, paper_question_id, old_letter, new_letter) "
                "VALUES (?, ?, ?, ?)",
                (group_id, pq_id, old, new),
            )
        db.commit()
    except ApiError:
        raise
    except sqlite3.DatabaseError as exc:
        db.rollback()
        raise ApiError(500, f"更正写入失败，已回滚：{exc}")

    return jsonify({
        "ok": True,
        "correction_id": group_id,
        "applied": [
            {"number": number, "old": old, "new": new}
            for _, number, old, new in prepared
        ],
    })


@app.get("/api/seals/<int:seal_id>/sheets/<int:sheet_id>/corrections")
def list_corrections(seal_id, sheet_id):
    db = get_db()
    sheet = db.execute(
        "SELECT id, paper FROM answer_sheet WHERE id = ? AND seal_id = ?",
        (sheet_id, seal_id),
    ).fetchone()
    if sheet is None:
        raise ApiError(404, "答题卡不存在")
    code_map = _option_code_map(db, seal_id, sheet["paper"])
    groups = _correction_history(db, sheet_id, code_map)
    return jsonify({"ok": True, "corrections": groups})


# Current score is computed in Python from the effective answers (registered
# letter overlaid with every correction group, newest wins) graded against
# the current (possibly errata-updated) answer key.  Registered data is only
# ever read, never rewritten.
@app.get("/api/seals/<int:seal_id>/sheets")
def list_sheets(seal_id):
    db = get_db()
    if db.execute("SELECT 1 FROM seal WHERE id = ?", (seal_id,)).fetchone() is None:
        raise ApiError(404, "封存卷不存在")
    correct_of = {
        r["id"]: r["correct_sealed_option_id"]
        for r in db.execute(
            "SELECT id, correct_sealed_option_id FROM sealed_question WHERE seal_id = ?",
            (seal_id,),
        ).fetchall()
    }
    sheets = [dict(r) for r in db.execute(
        """SELECT s.id, s.paper, s.examinee, s.total_score, s.created_at,
                  (SELECT COUNT(*) FROM sheet_correction c WHERE c.sheet_id = s.id)
                      AS correction_count
             FROM answer_sheet s WHERE s.seal_id = ? ORDER BY s.id""",
        (seal_id,),
    ).fetchall()]
    # one shared letter -> sealed-option map per paper
    paper_meta = {p: _printed_paper(db, seal_id, p) for p in ("A", "B")}
    for sh in sheets:
        _printed, letters = paper_meta[sh["paper"]]
        pq_to_sq = {pq: v["sealed_question_id"] for pq, v in _printed.items()}
        current_total = 0
        for pq_id, letter in _effective_letters(db, sh["id"]).items():
            so_id = letters[pq_id][letter] if letter else None
            if so_id is not None and so_id == correct_of[pq_to_sq[pq_id]]:
                current_total += 1
        sh["current_total"] = current_total
    return jsonify({"ok": True, "sheets": sheets})


@app.get("/api/seals/<int:seal_id>/sheets/<int:sheet_id>")
def get_sheet(seal_id, sheet_id):
    db = get_db()
    sheet = db.execute(
        "SELECT id, paper, examinee, total_score, created_at "
        "FROM answer_sheet WHERE id = ? AND seal_id = ?",
        (sheet_id, seal_id),
    ).fetchone()
    if sheet is None:
        raise ApiError(404, "答题卡不存在")
    printed, letters = _printed_paper(db, seal_id, sheet["paper"])
    code_map = _option_code_map(db, seal_id, sheet["paper"])
    correct_of = {
        r["id"]: r["correct_sealed_option_id"]
        for r in db.execute(
            "SELECT id, correct_sealed_option_id FROM sealed_question WHERE seal_id = ?",
            (seal_id,),
        ).fetchall()
    }

    # Registered per-question rows in printed-number order.
    reg = {}
    for r in db.execute(
        """SELECT i.paper_question_id, i.letter, i.score
             FROM answer_sheet_item i
            WHERE i.sheet_id = ?""",
        (sheet_id,),
    ).fetchall():
        reg[r["paper_question_id"]] = r

    # Effective answers = registered overlaid with corrections (newest wins).
    effective = _effective_letters(db, sheet_id)

    items = []
    changes = []
    current_total = 0
    for number in sorted(printed):
        pq_id = printed[number]["pq_id"]
        sq_id = printed[number]["sealed_question_id"]
        row = reg[pq_id]
        eff_letter = effective[pq_id]
        eff_so = letters[pq_id][eff_letter] if eff_letter else None
        current = 1 if (eff_so is not None and eff_so == correct_of[sq_id]) else 0
        current_total += current
        reg_letter = row["letter"]
        reg_so = letters[pq_id][reg_letter] if reg_letter else None
        item = {
            "number": number,
            "letter": reg_letter,
            "option_code": code_map.get((pq_id, reg_letter)),
            "registered_score": row["score"],
            "effective_letter": eff_letter,
            "effective_option_code": code_map.get((pq_id, eff_letter)),
            "current_score": current,
            "corrected": reg_letter != eff_letter,
        }
        items.append(item)
        # 复核相对【登记分数】的逐题变化：可能来自勘误，也可能来自更正。
        if current != row["score"]:
            changes.append({
                "number": number,
                "letter": reg_letter,
                "effective_letter": eff_letter,
                "corrected": reg_letter != eff_letter,
                "before": row["score"], "after": current,
            })

    groups = _correction_history(db, sheet_id, code_map)
    return jsonify({
        "ok": True,
        "sheet": {
            "id": sheet["id"], "paper": sheet["paper"], "examinee": sheet["examinee"],
            "total_score": sheet["total_score"], "current_total": current_total,
            "created_at": sheet["created_at"],
            "correction_count": len(groups),
        },
        "items": items,
        "changes": changes,
        "corrections": groups,
    })


# ---------------------------------------------------------------------------
# score release batches
# ---------------------------------------------------------------------------

def _release_summary(db, batch_row):
    d = dict(batch_row)
    d["sheet_count"] = db.execute(
        "SELECT COUNT(*) c FROM release_sheet WHERE batch_id = ?", (d["id"],)
    ).fetchone()["c"]
    return d


@app.post("/api/seals/<int:seal_id>/releases")
def create_release(seal_id):
    db = get_db()
    if db.execute("SELECT 1 FROM seal WHERE id = ?", (seal_id,)).fetchone() is None:
        raise ApiError(404, "封存卷不存在")

    # BEGIN IMMEDIATE takes the write lock up front: the roster, the answer
    # key, every correction group and every per-question score are read and
    # snapshotted inside one transaction, so a registration, erratum or
    # correction racing the publish lands either wholly in this batch or
    # wholly in the next one — never an old roster graded by a newer key.
    try:
        db.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        raise ApiError(409, "另一个写入操作正在进行，请稍后重试")
    try:
        correct_of = {
            r["id"]: r["correct_sealed_option_id"]
            for r in db.execute(
                "SELECT id, correct_sealed_option_id FROM sealed_question WHERE seal_id = ?",
                (seal_id,),
            ).fetchall()
        }
        sheets = db.execute(
            "SELECT id, paper, examinee FROM answer_sheet "
            "WHERE seal_id = ? ORDER BY paper, examinee",
            (seal_id,),
        ).fetchall()
        if not sheets:
            db.rollback()
            raise ApiError(400, "本封存版本尚未登记任何答题卡，拒绝发布成绩批次")

        batch_no = db.execute(
            "SELECT COALESCE(MAX(batch_no), 0) + 1 AS n FROM release_batch WHERE seal_id = ?",
            (seal_id,),
        ).fetchone()["n"]
        batch_id = db.execute(
            "INSERT INTO release_batch (seal_id, batch_no) VALUES (?, ?)",
            (seal_id, batch_no),
        ).lastrowid

        for sh in sheets:
            rs_id = db.execute(
                "INSERT INTO release_sheet (batch_id, paper, examinee, total_score) "
                "VALUES (?, ?, ?, 0)",
                (batch_id, sh["paper"], sh["examinee"]),
            ).lastrowid
            # effective answers: registered letters overlaid with every
            # correction group accepted before this transaction
            printed, letters = _printed_paper(db, seal_id, sh["paper"])
            pq_to_sq = {pq: v["sealed_question_id"] for pq, v in printed.items()}
            effective = _effective_letters(db, sh["id"])
            total = 0
            for number in sorted(printed):
                pq_id = printed[number]["pq_id"]
                letter = effective[pq_id]
                so_id = letters[pq_id][letter] if letter else None
                score = 1 if (so_id is not None
                              and so_id == correct_of[pq_to_sq[pq_id]]) else 0
                total += score
                db.execute(
                    "INSERT INTO release_item (release_sheet_id, number, score) VALUES (?, ?, ?)",
                    (rs_id, number, score),
                )
            db.execute("UPDATE release_sheet SET total_score = ? WHERE id = ?", (total, rs_id))
        db.commit()
    except ApiError:
        raise
    except sqlite3.DatabaseError:
        db.rollback()
        raise ApiError(500, "发布写入失败，已回滚，未生成批次")
    return jsonify({
        "ok": True, "batch_id": batch_id, "batch_no": batch_no,
        "sheet_count": len(sheets),
    })


@app.get("/api/seals/<int:seal_id>/releases")
def list_releases(seal_id):
    db = get_db()
    if db.execute("SELECT 1 FROM seal WHERE id = ?", (seal_id,)).fetchone() is None:
        raise ApiError(404, "封存卷不存在")
    batches = [_release_summary(db, r) for r in db.execute(
        "SELECT id, batch_no, created_at FROM release_batch "
        "WHERE seal_id = ? ORDER BY batch_no DESC",
        (seal_id,),
    ).fetchall()]
    return jsonify({"ok": True, "batches": batches})


def _release_sheets(db, batch_id):
    """Sheets of one batch: paper/examinee order, items in printed-number order."""
    sheets = []
    for sh in db.execute(
        "SELECT id, paper, examinee, total_score FROM release_sheet "
        "WHERE batch_id = ? ORDER BY paper, examinee",
        (batch_id,),
    ).fetchall():
        d = dict(sh)
        d["items"] = [dict(r) for r in db.execute(
            "SELECT number, score FROM release_item "
            "WHERE release_sheet_id = ? ORDER BY number",
            (sh["id"],),
        ).fetchall()]
        sheets.append(d)
    return sheets


@app.get("/api/seals/<int:seal_id>/releases/<int:batch_id>")
def get_release(seal_id, batch_id):
    db = get_db()
    batch = db.execute(
        "SELECT id, batch_no, created_at FROM release_batch WHERE id = ? AND seal_id = ?",
        (batch_id, seal_id),
    ).fetchone()
    if batch is None:
        raise ApiError(404, "发布批次不存在")
    sheets = _release_sheets(db, batch_id)

    # Person-by-person comparison against the previous batch.  Both batches
    # are immutable snapshots, so the diff is recomputed deterministically.
    diff = None
    prev = db.execute(
        "SELECT id, batch_no FROM release_batch "
        "WHERE seal_id = ? AND batch_no < ? ORDER BY batch_no DESC LIMIT 1",
        (seal_id, batch["batch_no"]),
    ).fetchone()
    if prev is not None:
        prev_by_examinee = {s["examinee"]: s for s in _release_sheets(db, prev["id"])}
        new_examinees = []
        changes = []
        totals = []
        for sh in sheets:
            old = prev_by_examinee.get(sh["examinee"])
            if old is None:
                new_examinees.append({"examinee": sh["examinee"], "paper": sh["paper"]})
                continue
            old_scores = {it["number"]: it["score"] for it in old["items"]}
            person_changes = [
                {
                    "examinee": sh["examinee"], "paper": sh["paper"],
                    "number": it["number"],
                    "before": old_scores.get(it["number"]), "after": it["score"],
                }
                for it in sh["items"]
                if old_scores.get(it["number"]) != it["score"]
            ]
            if person_changes:
                changes.extend(person_changes)
                totals.append({
                    "examinee": sh["examinee"], "paper": sh["paper"],
                    "before": old["total_score"], "after": sh["total_score"],
                })
        diff = {
            "previous_batch_no": prev["batch_no"],
            "new_examinees": new_examinees,
            "changes": changes,
            "totals": totals,
        }
    return jsonify({
        "ok": True,
        "batch": _release_summary(db, batch),
        "sheets": sheets,
        "diff": diff,
    })


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

@app.get("/")
def page_home():
    return render_template("index.html", active="home")


@app.get("/questions")
def page_questions():
    return render_template("index.html", active="questions")


@app.get("/arrange")
def page_arrange():
    return render_template("index.html", active="arrange")


@app.get("/seals")
def page_seals():
    return render_template("index.html", active="seals")


@app.get("/seals/<int:seal_id>")
def page_seal_detail(seal_id):
    return render_template("index.html", active="seals")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
