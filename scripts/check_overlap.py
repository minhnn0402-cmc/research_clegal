import json
from collections import Counter


all_ids = []
for i in range(1, 6):
    with open(f'data/chunk_{i}_ids.json') as f:
        all_ids.extend(json.load(f))

counter = Counter(all_ids)
duplicates = [id for id, count in counter.items() if count > 1]
print(f"Duplicates: {len(duplicates)}")