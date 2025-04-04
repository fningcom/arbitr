import sqlite3

# Создание или подключение к базе данных
conn = sqlite3.connect("parser.db")
cursor = conn.cursor()

# Создание таблицы участников
cursor.execute('''
    CREATE TABLE IF NOT EXISTS participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_number TEXT UNIQUE,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Создание таблицы дел
cursor.execute('''
   CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_date TEXT,
            case_number TEXT,
            lawyer TEXT,
            next_hearing TEXT,
            plaintiff TEXT,
            defendant TEXT,
            iskod TEXT,
            final_judgment TEXT,
            chronology TEXT,
            established TEXT,
            determined TEXT,
            pdf TEXT,
            added_date TEXT  
        )
''')

conn.commit()
conn.close()
