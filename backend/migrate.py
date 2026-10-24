import mysql.connector
src = mysql.connector.connect(host='127.0.0.1', port=33309, user='root', password='Aman@#$4041', database='resume_analyzer_restore_test')
dst = mysql.connector.connect(host='127.0.0.1', port=3306, user='root', password='Aman@#4041', database='resume_analyzer')
scur = src.cursor()
dcur = dst.cursor()
cols = ['title', 'company', 'location', 'work_mode', 'description', 'requirements', 'source_url', 'posted_at', 'source_name', 'source_job_id', 'status', 'expires_at', 'last_seen_at', 'last_synced_at']
scur.execute(f'SELECT {",".join(cols)} FROM jobs')
rows = scur.fetchall()
placeholders = ','.join(['%s'] * len(cols))
sql = f'INSERT IGNORE INTO jobs ({",".join(cols)}) VALUES ({placeholders})'
dcur.executemany(sql, rows)
dst.commit()
print('Migrated', dcur.rowcount, 'rows')
src.close()
dst.close()