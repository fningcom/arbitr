import hashlib

def generate_id(field1: str, field2: str, field3: str) -> str:
    combined = f"{field1}-{field2}-{field3}"
    return hashlib.md5(combined.encode()).hexdigest()  # Можно заменить на sha256()

field1 = "30.01.2025"
field3 = "А40-17586/2025"
field2 = "Ходатайство (заявление) о переходе к рассмотрению дела по общим правилам искового производства"

unique_id = generate_id(field1, field2, field3)
print(unique_id)


