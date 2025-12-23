import time
from typing import List, Dict
from sqlalchemy.orm import Session
from database import SessionLocal, Product
import config
from search import get_embedding

# Mock D365 API Response
MOCK_D365_PRODUCTS = [
    {"ItemId": "P001", "Name": "Marine Grade Plywood", "Description": "High quality plywood for hull construction", "Price": 150.0},
    {"ItemId": "P002", "Name": "Stainless Steel Bolt M10", "Description": "M10 bolt, 316 grade stainless steel", "Price": 5.0},
    {"ItemId": "P003", "Name": "Teak Wood Plank", "Description": "Premium teak for decking", "Price": 1200.0},
    {"ItemId": "P004", "Name": "Engine Oil 5W30", "Description": "Synthetic engine oil for marine engines", "Price": 80.0},
]

def fetch_d365_products() -> List[Dict]:
    # Simulate API call
    # response = requests.get(f"{config.D365_API_URL}/products", headers=...)
    return MOCK_D365_PRODUCTS

def sync_products_from_d365():
    print("Starting D365 Product Sync...")
    session: Session = SessionLocal()
    try:
        products = fetch_d365_products()
        for p in products:
            d365_id = p["ItemId"]
            name = p["Name"]
            desc = p["Description"]
            price = p["Price"]
            
            # Check if exists
            existing = session.query(Product).filter(Product.d365_id == d365_id).first()
            
            # Generate embedding
            text_to_embed = f"{name} {desc}"
            vector = get_embedding(text_to_embed)
            
            if existing:
                # Update if needed (simplified: always update for now)
                existing.name = name
                existing.description = desc
                existing.price = price
                existing.embedding = vector
                print(f"Updated: {name}")
            else:
                new_product = Product(
                    d365_id=d365_id,
                    name=name,
                    description=desc,
                    price=price,
                    embedding=vector
                )
                session.add(new_product)
                print(f"Added: {name}")
        
        session.commit()
        print("Sync Completed.")
    except Exception as e:
        print(f"Sync Error: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == "__main__":
    # For manual run
    from database import init_db
    init_db()
    sync_products_from_d365()
