# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scripts.db import init_db, get_contacts, upsert_contact, upsert_project, set_project_members, get_projects

init_db()

# Fix 수아 -> 정수아
contacts = get_contacts()
for c in contacts:
    if c['name'] == '수아':
        c['name'] = '정수아'
        upsert_contact(c)
        print(f"Fixed: 수아 -> 정수아 (id={c['id']})")

# Reload contacts
contacts = get_contacts()
name_to_id = {c['name']: c['id'] for c in contacts}
# Also map by nickname
for c in contacts:
    if c.get('nicknames'):
        for nick in c['nicknames'].split(','):
            nick = nick.strip()
            if nick and nick not in name_to_id:
                name_to_id[nick] = c['id']

print("Contact name->id map (sample):", {k: v for k, v in list(name_to_id.items())[:10]})

def find_contact(name):
    if name in name_to_id:
        return name_to_id[name]
    # partial match
    for k, v in name_to_id.items():
        if name in k or k in name:
            return v
    print(f"  WARNING: contact not found: {name}")
    return None

# Seed IKEA +you
existing = get_projects()
existing_names = {p['name'] for p in existing}

if 'IKEA +you' not in existing_names:
    pid1 = upsert_project({'name': 'IKEA +you', 'client': 'IKEA', 'status': '진행중', 'description': 'IKEA +you 프로젝트'})
    print(f"Created project: IKEA +you (id={pid1})")
else:
    pid1 = next(p['id'] for p in existing if p['name'] == 'IKEA +you')
    print(f"Project already exists: IKEA +you (id={pid1})")

members1 = []
for name, role in [('노미소', 'IKEA 담당자'), ('정수아', 'IKEA 담당자'), ('김동석', 'DF 담당자'), ('김현수', 'DF 담당자')]:
    cid = find_contact(name)
    if cid:
        members1.append({'contact_id': cid, 'member_role': role})
        print(f"  +you member: {name} ({role})")
set_project_members(pid1, members1)

# Seed IKEA Run
if 'IKEA Run' not in existing_names:
    pid2 = upsert_project({'name': 'IKEA Run', 'client': 'IKEA', 'status': '진행중', 'description': 'IKEA Run 프로젝트'})
    print(f"Created project: IKEA Run (id={pid2})")
else:
    pid2 = next(p['id'] for p in existing if p['name'] == 'IKEA Run')
    print(f"Project already exists: IKEA Run (id={pid2})")

members2 = []
for name, role in [('신디', 'IKEA 담당자'), ('티프', 'IKEA 담당자'), ('김동석', 'DF 담당자'), ('김현수', 'DF 담당자')]:
    cid = find_contact(name)
    if cid:
        members2.append({'contact_id': cid, 'member_role': role})
        print(f"  Run member: {name} ({role})")
set_project_members(pid2, members2)

print("\nDone! Projects seeded.")
