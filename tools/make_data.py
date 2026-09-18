"""Writes the sample CSVs in data/.

Seeded, so re-running it reproduces the same files byte for byte and the numbers
in the README stay true.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20260917
DATA = Path(__file__).resolve().parent.parent / "data"

CITIES = ["Lahore", "Karachi", "Islamabad", "Faisalabad", "Multan", "Peshawar", "Quetta"]
FIRST = ["Ayesha", "Bilal", "Hamza", "Sana", "Noor", "Imran", "Zara", "Usman", "Fatima", "Rizwan",
         "Maryam", "Tariq", "Hina", "Adeel", "Sadia", "Kamran", "Iqra", "Faisal", "Rabia", "Junaid",
         "Areeba", "Shahid", "Mehwish", "Asad", "Lubna"]
LAST = ["Khan", "Ahmed", "Malik", "Sheikh", "Butt", "Qureshi", "Raza", "Chaudhry", "Farooq", "Siddiqui"]
CATEGORIES = {
    "Keyboards": [("Mechanical keyboard", 14500), ("Low-profile keyboard", 9800), ("Numpad", 2400)],
    "Displays": [("27\" 1440p monitor", 68000), ("24\" 1080p monitor", 34000), ("Monitor arm", 7900)],
    "Audio": [("Studio headphones", 21500), ("USB microphone", 18700), ("Desk speakers", 12300)],
    "Storage": [("1TB NVMe drive", 19900), ("2TB external SSD", 31500), ("SD card reader", 3100)],
    "Desk": [("Standing desk", 92000), ("Desk mat", 3600), ("Cable tray", 2800)],
}


def main() -> None:
    random.seed(SEED)
    DATA.mkdir(exist_ok=True)

    customers = []
    for i in range(1, 26):
        name = f"{FIRST[i - 1]} {random.choice(LAST)}"
        # A few customers have no recorded city, so the sample data exercises NULL.
        city = "" if i in (7, 19) else random.choice(CITIES)
        customers.append({
            "id": i,
            "name": name,
            "city": city,
            "signup_date": (date(2024, 1, 5) + timedelta(days=random.randint(0, 700))).isoformat(),
            "newsletter": random.choice(["yes", "no"]),
        })

    products = []
    pid = 1
    for category, items in CATEGORIES.items():
        for title, price in items:
            products.append({"id": pid, "name": title, "category": category, "price": price,
                             "in_stock": random.randint(0, 60)})
            pid += 1

    orders = []
    items_rows = []
    order_id = 1
    item_id = 1
    for _ in range(60):
        customer = random.choice(customers)
        placed = date(2025, 1, 1) + timedelta(days=random.randint(0, 600))
        status = random.choices(["shipped", "delivered", "cancelled", "pending"], [5, 6, 1, 2])[0]
        orders.append({
            "id": order_id,
            "customer_id": customer["id"],
            "placed_on": placed.isoformat(),
            "status": status,
            # Cancelled orders never shipped, so the column is empty for them.
            "shipped_on": "" if status in ("cancelled", "pending")
            else (placed + timedelta(days=random.randint(1, 6))).isoformat(),
        })
        for product in random.sample(products, random.randint(1, 4)):
            quantity = random.randint(1, 3)
            items_rows.append({
                "id": item_id,
                "order_id": order_id,
                "product_id": product["id"],
                "quantity": quantity,
                "unit_price": product["price"],
            })
            item_id += 1
        order_id += 1

    write("customers.csv", customers)
    write("products.csv", products)
    write("orders.csv", orders)
    write("order_items.csv", items_rows)
    print(f"customers {len(customers)}  products {len(products)}  orders {len(orders)}  order_items {len(items_rows)}")


def write(name: str, rows: list[dict]) -> None:
    path = DATA / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
