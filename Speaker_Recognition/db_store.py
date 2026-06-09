"""
MySQL store for the Speaker Recognition module: speakers, their voiceprint
embeddings, and evaluation runs (so accuracy / EER can be tracked over time).

First-time setup (creates database + user, needs admin once):
    sudo mysql < Speaker_Recognition/db/setup.sql

Then (with the audio venv):
    ./.venv-audio/bin/python -m Speaker_Recognition.db_store init
    ./.venv-audio/bin/python -m Speaker_Recognition.db_store import-eval Speaker_Recognition/libri_mfcc_report.json
    ./.venv-audio/bin/python -m Speaker_Recognition.db_store import-profiles Speaker_Recognition/speaker_profiles.json --encoder mfcc
    ./.venv-audio/bin/python -m Speaker_Recognition.db_store show

Connection settings come from env (defaults in parens):
    GO2_DB_HOST (localhost)  GO2_DB_USER (go2)  GO2_DB_PASSWORD (go2pass)  GO2_DB_NAME (go2_speaker)
"""

import argparse
import json
import os
from pathlib import Path

import pymysql


def connect():
    return pymysql.connect(
        host=os.getenv("GO2_DB_HOST", "localhost"),
        user=os.getenv("GO2_DB_USER", "go2"),
        password=os.getenv("GO2_DB_PASSWORD", "Go2Speaker#2026"),
        database=os.getenv("GO2_DB_NAME", "go2_speaker"),
        charset="utf8mb4",
        autocommit=True,
    )


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS speakers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(128) NOT NULL UNIQUE,
        source VARCHAR(64) DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS embeddings (
        id INT AUTO_INCREMENT PRIMARY KEY,
        speaker_id INT NOT NULL,
        encoder VARCHAR(32) NOT NULL,
        dim INT NOT NULL,
        vector JSON NOT NULL,
        sample_count INT DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_speaker_encoder (speaker_id, encoder),
        FOREIGN KEY (speaker_id) REFERENCES speakers(id) ON DELETE CASCADE
    ) ENGINE=InnoDB
    """,
    """
    CREATE TABLE IF NOT EXISTS eval_runs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        dataset VARCHAR(255),
        encoder VARCHAR(32),
        threshold FLOAT,
        vad_precision FLOAT, vad_recall FLOAT, vad_f1 FLOAT,
        top1_accuracy FLOAT,
        eer FLOAT, eer_threshold FLOAT,
        best_threshold FLOAT, best_accuracy FLOAT,
        report JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB
    """,
]


def ensure_schema(conn):
    with conn.cursor() as cur:
        for stmt in SCHEMA:
            cur.execute(stmt)


def upsert_speaker(cur, name, source=None):
    cur.execute("INSERT IGNORE INTO speakers (name, source) VALUES (%s, %s)", (name, source))
    cur.execute("SELECT id FROM speakers WHERE name=%s", (name,))
    return cur.fetchone()[0]


def import_profiles(conn, profiles_path, encoder):
    data = json.loads(Path(profiles_path).read_text(encoding="utf-8"))
    profiles = data.get("profiles", [])
    n = 0
    with conn.cursor() as cur:
        for p in profiles:
            sid = upsert_speaker(cur, p["speaker_id"], source="enroll")
            vec = p["embedding"]
            cur.execute(
                """INSERT INTO embeddings (speaker_id, encoder, dim, vector, sample_count)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE dim=VALUES(dim), vector=VALUES(vector),
                       sample_count=VALUES(sample_count)""",
                (sid, encoder, len(vec), json.dumps(vec), int(p.get("sample_count", 1))),
            )
            n += 1
    print(f"Imported {n} speaker embeddings (encoder={encoder}).")


def import_eval(conn, report_path):
    r = json.loads(Path(report_path).read_text(encoding="utf-8"))
    vad = r.get("vad") or {}
    sid = r.get("identification") or {}
    eer = (sid.get("eer") or {})
    best = (sid.get("best_accuracy_point") or {})
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO eval_runs
               (dataset, encoder, threshold, vad_precision, vad_recall, vad_f1,
                top1_accuracy, eer, eer_threshold, best_threshold, best_accuracy, report)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                r.get("dataset"), r.get("encoder"), r.get("threshold"),
                vad.get("precision"), vad.get("recall"), vad.get("f1"),
                sid.get("top1_accuracy"),
                eer.get("eer"), eer.get("threshold"),
                best.get("threshold"), best.get("accuracy"),
                json.dumps(r),
            ),
        )
    print(f"Imported eval run from {report_path} (encoder={r.get('encoder')}).")


def show(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM speakers")
        n_spk = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM embeddings")
        n_emb = cur.fetchone()[0]
        print(f"speakers: {n_spk} | embeddings: {n_emb}\n")
        print("eval_runs:")
        cur.execute(
            """SELECT id, encoder, top1_accuracy, eer, vad_f1, created_at
               FROM eval_runs ORDER BY id DESC LIMIT 20"""
        )
        print(f"  {'id':>3} {'encoder':<12} {'top1':>7} {'EER':>7} {'vadF1':>7}  created")
        for row in cur.fetchall():
            i, enc, top1, eer, f1, ts = row
            top1 = f"{top1:.3f}" if top1 is not None else "  -  "
            eer = f"{eer:.3f}" if eer is not None else "  -  "
            f1 = f"{f1:.3f}" if f1 is not None else "  -  "
            print(f"  {i:>3} {str(enc):<12} {top1:>7} {eer:>7} {f1:>7}  {ts}")


def main():
    ap = argparse.ArgumentParser(description="MySQL store for the Speaker Recognition module.")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create tables if missing.")
    ie = sub.add_parser("import-eval", help="Insert an evaluation report JSON.")
    ie.add_argument("report")
    ip = sub.add_parser("import-profiles", help="Insert speaker embeddings from a profiles JSON.")
    ip.add_argument("profiles")
    ip.add_argument("--encoder", default="mfcc")
    sub.add_parser("show", help="Print stored speakers / embeddings / eval runs.")
    args = ap.parse_args()

    conn = connect()
    ensure_schema(conn)
    if args.command == "init":
        print("Schema ready.")
    elif args.command == "import-eval":
        import_eval(conn, args.report)
    elif args.command == "import-profiles":
        import_profiles(conn, args.profiles, args.encoder)
    elif args.command == "show":
        show(conn)
    conn.close()


if __name__ == "__main__":
    main()
