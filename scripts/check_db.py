# -*- coding: utf-8 -*-
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sqlite3

con = sqlite3.connect('output/tiro.db')
con.row_factory = sqlite3.Row

print("=== contacts with 수아 ===")
for r in con.execute("SELECT id, name, nicknames, organization FROM contacts WHERE name LIKE '%수아%'").fetchall():
    print(dict(r))

print("\n=== projects ===")
for r in con.execute("SELECT id, name, client, status FROM projects").fetchall():
    print(dict(r))

print("\n=== project_members ===")
for r in con.execute("""
    SELECT pm.project_id, p.name as proj, c.name as contact, pm.member_role
    FROM project_members pm
    JOIN projects p ON p.id = pm.project_id
    JOIN contacts c ON c.id = pm.contact_id
    ORDER BY pm.project_id, pm.member_role
""").fetchall():
    print(dict(r))
